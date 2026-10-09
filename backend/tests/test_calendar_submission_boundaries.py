"""Pure submissions, durable followups and scope-serialized manual retries."""
from concurrent.futures import ThreadPoolExecutor

import pytest

import jobs.calendar_jobs as calendar
import storage.tracked_ups as tracked
from tests.test_calendar_api import client, _admin_headers


@pytest.fixture
def calendar_runtime(postgres_runtime, monkeypatch):
    tracked.save_tracked_list([{"mid": 1, "name": "A", "enabled": True},
                             {"mid": 2, "name": "B", "enabled": True}])
    monkeypatch.setattr(calendar, "ensure_calendar_worker", lambda: None)
    return postgres_runtime


def _fail(repo, job_id, now):
    repo.fail_calendar_job_items(job_id, "request_failed", "失败", now)
    repo.finish_calendar_job(job_id, "failed", now, "失败")


def test_enqueue_never_starts_consumer(calendar_runtime, monkeypatch):
    def forbidden():
        raise AssertionError("enqueue must not start an API calendar consumer")
    monkeypatch.setattr(calendar, "ensure_calendar_worker", forbidden)
    job, created = calendar.enqueue_calendar_job(mode="recent", days=7)
    assert created and job["status"] == "queued"
    assert calendar.enqueue_baseline_jobs([1])


@pytest.mark.parametrize("status", ["failed", "partial"])
def test_failed_job_does_not_block_new_submission(calendar_runtime, status):
    repo = calendar_runtime.business
    first, _ = repo.enqueue_calendar_job("recent", [{"mid": 1}], 100,
                                         days=7, dedupe_key="scope", dedupe_window_seconds=1800)
    repo.finish_calendar_job(first["id"], status, 101)
    second, created = repo.enqueue_calendar_job("recent", [{"mid": 1}], 102,
                                                days=7, dedupe_key="scope", dedupe_window_seconds=1800)
    assert created and second["id"] != first["id"]
    assert repo.calendar_job(first["id"])["status"] == status


def test_success_window_and_analysis_followup_have_distinct_dedupe(calendar_runtime):
    repo = calendar_runtime.business
    first, _ = repo.enqueue_calendar_job("recent", [{"mid": 1}], 100,
                                         days=7, dedupe_key="analysis:uuid", dedupe_forever=True)
    repo.finish_calendar_job(first["id"], "failed", 101)
    second, created = repo.enqueue_calendar_job("recent", [{"mid": 1}], 10000,
                                                days=7, dedupe_key="analysis:uuid", dedupe_forever=True)
    assert not created and second["id"] == first["id"]
    good, _ = repo.enqueue_calendar_job("recent", [{"mid": 1}], 10001,
                                        days=7, dedupe_key="recent", dedupe_window_seconds=1800)
    repo.finish_calendar_job(good["id"], "succeeded", 10002)
    reused, created = repo.enqueue_calendar_job("recent", [{"mid": 1}], 10003,
                                                 days=7, dedupe_key="recent", dedupe_window_seconds=1800)
    assert not created and reused["id"] == good["id"]


def test_manual_scope_normalizes_mids_and_serializes(calendar_runtime, monkeypatch):
    monkeypatch.setattr(calendar.time, "time", lambda: 100)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(calendar.enqueue_manual_calendar_job, mode="recent", days=7,
                               mids=mids, requested_by="admin") for mids in ([1, 2], [2, 1, 1])]
        results = [f.result() for f in futures]
    assert len({job["id"] for job, _ in results}) == 1
    assert sum(created for _, created in results) == 1


def test_manual_retry_cooldown_and_parent_are_preserved(client, postgres_runtime, monkeypatch):
    tracked.save_tracked_list([{"mid": 1, "name": "A", "enabled": True}])
    clock = [100]
    monkeypatch.setattr(calendar.time, "time", lambda: clock[0])
    first = client.post("/api/up-trends/calendar/backfill", json={"mode": "recent", "days": 7}, headers=_admin_headers())
    assert first.status_code == 202
    first_id = first.json["job_id"]
    _fail(postgres_runtime.business, first_id, 101)
    clock[0] = 159
    route = f"/api/up-trends/calendar/jobs/{first_id}/retry"
    early = client.post(route, headers=_admin_headers())
    assert early.status_code == 429 and early.json["retry_after"] == 1
    assert early.headers["Retry-After"] == "1"
    clock[0] = 160
    retried = client.post(route, headers=_admin_headers())
    assert retried.status_code == 202
    assert retried.json["job_id"] != first_id
    assert retried.json["data"]["parent_job_id"] == first_id
    assert calendar.get_calendar_job(first_id)["status"] == "failed"
    busy = client.post(route, headers=_admin_headers())
    assert busy.status_code == 409 and busy.json["busy"] is True
    assert busy.json["job_id"] == retried.json["job_id"]


def test_worker_analysis_queues_real_calendar_without_starting_it(calendar_runtime, monkeypatch):
    from jobs import up_analysis_worker as worker
    from tests.test_analysis_job_repository import RESULT, ROSTER
    import collectors.bilibili_user as collector
    monkeypatch.setattr(worker.time, "time", lambda: 100)
    monkeypatch.setattr(collector, "analyze_tracked_ups_with_progress", lambda *_: RESULT)
    def forbidden():
        raise AssertionError("followup must only enqueue")
    monkeypatch.setattr(calendar, "ensure_calendar_worker", forbidden)
    job, _ = calendar_runtime.analysis_jobs.enqueue(ROSTER, "test", 99)
    worker.run_analysis_once("worker")
    saved = calendar_runtime.analysis_jobs.get(job["id"])
    assert saved["status"] == "succeeded"
    followup = calendar.get_calendar_job(saved["result_summary"]["calendar_job_id"])
    assert followup["status"] == "queued"
    assert followup["dedupe_key"] == f"analysis:{job['id']}"


def test_calendar_worker_error_does_not_persist_raw_exception(calendar_runtime, monkeypatch):
    import collectors.bilibili_auth as auth
    import collectors.calendar_backfill as backfill
    monkeypatch.setattr(auth, "get_cookie_str", lambda: "test-cookie")
    def fail(**kwargs):
        raise RuntimeError("PRIVATE_URL_SECRET_MARKER")
    monkeypatch.setattr(backfill, "backfill_calendar", fail)
    job, _ = calendar.enqueue_calendar_job(mode="recent", days=7)
    claim = calendar._claim_next_job("worker")
    calendar._execute_job(claim, "worker")
    saved = calendar.get_calendar_job(job["id"])
    assert saved["status"] == "failed"
    assert "PRIVATE_URL_SECRET_MARKER" not in str(saved)
    assert saved["items"][0]["error_code"] == "job_error"
