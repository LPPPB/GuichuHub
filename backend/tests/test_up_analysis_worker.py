"""Submission is pure; the Worker saves core data and resumes finalization."""
import threading

import pytest
from sqlalchemy import func, select

from storage.models import up_observations
from tests.test_analysis_job_repository import ROSTER, RESULT


def test_start_analysis_only_persists_job(postgres_runtime, monkeypatch):
    import jobs.up_trends_jobs as jobs
    if hasattr(jobs, "_analysis_lock"):
        monkeypatch.setattr(jobs, "_analysis_lock", threading.Lock())
    def forbidden(*_args, **_kwargs):
        raise AssertionError("API submission must not start a collection thread")
    monkeypatch.setattr(threading.Thread, "start", forbidden)
    task_id = jobs.start_analysis(ROSTER)
    assert postgres_runtime.analysis_jobs.get(task_id)["status"] == "queued"
    assert jobs.start_analysis(ROSTER) is None
    assert jobs.get_running_task_id() == task_id


@pytest.fixture
def worker(postgres_runtime, monkeypatch):
    from jobs import up_analysis_worker
    monkeypatch.setattr(up_analysis_worker.time, "time", lambda: 100)
    import collectors.bilibili_user as collector
    monkeypatch.setattr(collector, "analyze_tracked_ups_with_progress", lambda *_: RESULT)
    import jobs.calendar_jobs as calendar
    monkeypatch.setattr(calendar, "enqueue_calendar_job", lambda **kwargs: ({"id": "calendar-one"}, True))
    return up_analysis_worker


def test_worker_commits_core_and_links_calendar(worker, postgres_runtime):
    job, _ = postgres_runtime.analysis_jobs.enqueue(ROSTER, "test", 99)
    assert worker.run_analysis_once("test-worker") is True
    saved = postgres_runtime.analysis_jobs.get(job["id"])
    assert saved["status"] == "succeeded"
    assert saved["result_summary"]["calendar_job_id"] == "calendar-one"
    assert saved["result_summary"]["video_obs_snapshot_fields"] == 6


def test_core_write_failure_does_not_report_success(worker, postgres_runtime, monkeypatch):
    job, _ = postgres_runtime.analysis_jobs.enqueue(ROSTER, "test", 99)
    def fail(*_args):
        raise RuntimeError("URL_SECRET_MARKER")
    monkeypatch.setattr(postgres_runtime.business, "_write_snapshot_batch", fail)
    worker.run_analysis_once("test-worker")
    saved = postgres_runtime.analysis_jobs.get(job["id"])
    assert saved["status"] == "failed"
    assert saved["error"]["code"] == "core_save_failed"
    assert "URL_SECRET_MARKER" not in str(saved)
    with postgres_runtime.sessions() as session:
        assert session.scalar(select(func.count()).select_from(up_observations)) == 0


def test_followup_failure_reports_partial_and_keeps_core(worker, postgres_runtime, monkeypatch):
    import jobs.calendar_jobs as calendar
    job, _ = postgres_runtime.analysis_jobs.enqueue(ROSTER, "test", 99)
    def fail(**_kwargs):
        raise RuntimeError("followup private failure")
    monkeypatch.setattr(calendar, "enqueue_calendar_job", fail)
    worker.run_analysis_once("test-worker")
    saved = postgres_runtime.analysis_jobs.get(job["id"])
    assert saved["status"] == "partial"
    assert saved["result_summary"]["warnings"][0]["code"] == "calendar_enqueue_failed"
    with postgres_runtime.sessions() as session:
        assert session.scalar(select(func.count()).select_from(up_observations)) == 1


def test_finalizing_resume_skips_collection(worker, postgres_runtime, monkeypatch):
    import collectors.bilibili_user as collector
    import jobs.calendar_jobs as calendar
    repo = postgres_runtime.analysis_jobs
    job, _ = repo.enqueue(ROSTER, "test", 1)
    claim = repo.claim("old", 2)
    repo.commit_core(job["id"], "old", claim["fencing_token"], 3, RESULT)
    monkeypatch.setattr(worker.time, "time", lambda: 122)
    def no_recollect(*_args):
        raise AssertionError("finalizing must not recollect")
    monkeypatch.setattr(collector, "analyze_tracked_ups_with_progress", no_recollect)
    def followup(**kwargs):
        assert kwargs["dedupe_key"] == f"analysis:{job['id']}"
        assert kwargs["dedupe_forever"] is True
        return {"id": "original-followup"}, False
    monkeypatch.setattr(calendar, "enqueue_calendar_job", followup)
    worker.run_analysis_once("new")
    assert repo.get(job["id"])["result_summary"]["calendar_job_id"] == "original-followup"


def test_heartbeat_runs_while_collector_has_no_progress(worker, postgres_runtime, monkeypatch):
    import collectors.bilibili_user as collector
    repo = postgres_runtime.analysis_jobs
    job, _ = repo.enqueue(ROSTER, "test", 99)
    renewed = threading.Event()
    original = repo.renew
    def renew(*args):
        result = original(*args)
        renewed.set()
        return result
    monkeypatch.setattr(repo, "renew", renew)
    monkeypatch.setattr(worker, "HEARTBEAT_SECONDS", 0.01)
    def collect(*_args):
        assert renewed.wait(3), "independent heartbeat must run without progress callback"
        return RESULT
    monkeypatch.setattr(collector, "analyze_tracked_ups_with_progress", collect)
    worker.run_analysis_once("worker")
    assert repo.get(job["id"])["status"] == "succeeded"


def test_collector_progress_is_durable(worker, postgres_runtime, monkeypatch):
    import collectors.bilibili_user as collector
    repo = postgres_runtime.analysis_jobs
    job, _ = repo.enqueue(ROSTER, "test", 99)
    def collect(roster, callback):
        callback(0, "A")
        assert repo.get(job["id"])["progress"]["current_up"] == "A"
        return RESULT
    monkeypatch.setattr(collector, "analyze_tracked_ups_with_progress", collect)
    worker.run_analysis_once("worker")
    assert repo.get(job["id"])["progress"]["current"] == 1


def test_consumer_start_is_idempotent(worker, monkeypatch):
    starts = []
    class FakeThread:
        def __init__(self, **kwargs):
            assert kwargs["name"] == "up-analysis-consumer"
        def start(self):
            starts.append(1)
        def is_alive(self):
            return True
    monkeypatch.setattr(worker, "_thread", None)
    monkeypatch.setattr(worker.threading, "Thread", FakeThread)
    worker.ensure_analysis_worker()
    worker.ensure_analysis_worker()
    assert starts == [1]
