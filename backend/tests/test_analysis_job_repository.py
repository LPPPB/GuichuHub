"""Durable mutual exclusion, ownership fencing and batch atomicity."""
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import func, select

from storage.models import up_observations, video_snapshot_documents

ROSTER = [{"mid": 1, "name": "A", "enabled": True}]
RESULT = {"up_trends": [{"mid": 1, "name": "A", "views": 9}],
          "analysis": {"summary": {"total_views": 9, "total_videos": 1}}}


@pytest.fixture
def repo(postgres_runtime):
    assert hasattr(postgres_runtime, "analysis_jobs"), "runtime must install durable analysis repository"
    return postgres_runtime.analysis_jobs


def test_concurrent_submit_has_one_global_active_job(repo):
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda n: repo.enqueue(ROSTER, f"caller:{n}", 100), range(6)))
    assert len({job["id"] for job, _ in results}) == 1
    assert sum(created for _, created in results) == 1
    assert repo.active()["status"] == "queued"


def test_new_repository_reads_existing_progress(repo, postgres_runtime):
    from storage.repositories.analysis_jobs import AnalysisJobRepository
    job, _ = repo.enqueue(ROSTER, "test", 100)
    claim = repo.claim("worker-a", 101)
    repo.update_progress(job["id"], "worker-a", claim["fencing_token"], 102,
                         {"total": 1, "current": 1, "current_up": "A", "eta_seconds": 0})
    fresh = AnalysisJobRepository(postgres_runtime.sessions, postgres_runtime.business)
    assert fresh.get(job["id"])["progress"]["current_up"] == "A"
    assert fresh.get("not-a-uuid") is None


def test_empty_roster_rejected_without_job(repo):
    with pytest.raises(ValueError):
        repo.enqueue([], "test", 100)
    assert repo.active() is None


def test_expired_claim_preserves_batch_time_and_rejects_old_owner(repo):
    from storage.repositories.analysis_jobs import LostAnalysisLease
    job, _ = repo.enqueue(ROSTER, "test", 100)
    first = repo.claim("worker-a", 101)
    assert repo.claim("worker-b", 220) is None
    second = repo.claim("worker-b", 221)
    assert second["fencing_token"] == first["fencing_token"] + 1
    assert second["batch_ts"] == first["batch_ts"]
    assert repo.renew(job["id"], "worker-a", first["fencing_token"], 222) is False
    with pytest.raises(LostAnalysisLease):
        repo.update_progress(job["id"], "worker-a", first["fencing_token"], 222, {})
    with pytest.raises(LostAnalysisLease):
        repo.commit_core(job["id"], "worker-a", first["fencing_token"], 222, RESULT)


def test_core_commit_after_lease_deadline_writes_nothing(repo, postgres_runtime):
    from storage.repositories.analysis_jobs import LostAnalysisLease
    job, _ = repo.enqueue(ROSTER, "test", 100)
    claim = repo.claim("worker", 101)
    with pytest.raises(LostAnalysisLease):
        repo.commit_core(job["id"], "worker", claim["fencing_token"], 221, RESULT)
    with postgres_runtime.sessions() as session:
        assert session.scalar(select(func.count()).select_from(up_observations)) == 0


def test_third_expired_attempt_becomes_failed(repo):
    job, _ = repo.enqueue(ROSTER, "test", 100)
    assert repo.claim("a", 101)["attempts"] == 1
    assert repo.claim("b", 221)["attempts"] == 2
    assert repo.claim("c", 341)["attempts"] == 3
    assert repo.claim("d", 461) is None
    assert repo.get(job["id"])["status"] == "failed"
    assert repo.active() is None


def test_core_saves_one_up_six_snapshots_and_finalizing_atomically(repo, postgres_runtime):
    job, _ = repo.enqueue(ROSTER, "test", 100)
    claim = repo.claim("worker", 101)
    saved = repo.commit_core(job["id"], "worker", claim["fencing_token"], 102, RESULT)
    assert saved["status"] == "finalizing"
    assert saved["result_summary"]["up_obs_rows"] == 1
    assert saved["result_summary"]["video_obs_snapshot_fields"] == 6
    with postgres_runtime.sessions() as session:
        assert session.scalar(select(func.count()).select_from(up_observations)) == 1
        assert session.scalar(select(func.count()).select_from(video_snapshot_documents)) == 6
    repo.finish(job["id"], "worker", claim["fencing_token"], 103, "succeeded", saved["result_summary"])
    assert repo.get(job["id"])["status"] == "succeeded"


def test_snapshot_error_rolls_back_up_rows_but_not_history(repo, postgres_runtime, monkeypatch):
    postgres_runtime.business.upsert_up_observations(9, [{"mid": 2, "name": "historic"}])
    job, _ = repo.enqueue(ROSTER, "test", 100)
    claim = repo.claim("worker", 101)
    def fail(*_args):
        raise RuntimeError("injected write failure")
    monkeypatch.setattr(postgres_runtime.business, "_write_snapshot_batch", fail)
    with pytest.raises(RuntimeError, match="injected"):
        repo.commit_core(job["id"], "worker", claim["fencing_token"], 102, RESULT)
    assert repo.get(job["id"])["status"] == "running"
    with postgres_runtime.sessions() as session:
        assert session.scalar(select(func.count()).select_from(up_observations)) == 1
        assert session.scalar(select(func.count()).select_from(video_snapshot_documents)) == 0


def test_finalizing_can_be_reclaimed_without_core_rewrite(repo):
    job, _ = repo.enqueue(ROSTER, "test", 100)
    first = repo.claim("a", 101)
    repo.commit_core(job["id"], "a", first["fencing_token"], 102, RESULT)
    recovered = repo.claim("b", 221)
    assert recovered["status"] == "finalizing"
    assert recovered["result_summary"]["up_obs_rows"] == 1


def test_terminal_job_cannot_be_overwritten(repo):
    from storage.repositories.analysis_jobs import LostAnalysisLease
    job, _ = repo.enqueue(ROSTER, "test", 100)
    claim = repo.claim("a", 101)
    repo.finish(job["id"], "a", claim["fencing_token"], 102, "failed", {}, {"code": "collection_failed", "message": "分析失败"})
    with pytest.raises(LostAnalysisLease):
        repo.finish(job["id"], "a", claim["fencing_token"], 103, "succeeded", {})


def test_same_second_next_batch_does_not_overwrite_previous(repo):
    job, _ = repo.enqueue(ROSTER, "test", 100)
    first = repo.claim("a", 101)
    saved = repo.commit_core(job["id"], "a", first["fencing_token"], 101, RESULT)
    repo.finish(job["id"], "a", first["fencing_token"], 101, "succeeded", saved["result_summary"])
    repo.enqueue(ROSTER, "next", 101)
    assert repo.claim("b", 101)["batch_ts"] > first["batch_ts"]
