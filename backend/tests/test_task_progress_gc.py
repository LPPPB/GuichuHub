"""Durable replacement for obsolete in-memory GC: retain task history."""
from jobs.up_trends_jobs import get_progress


def _failed_job(repo, now):
    job, _ = repo.enqueue([{"mid": 1, "name": "A"}], "test", now)
    claim = repo.claim("worker", now)
    repo.finish(job["id"], "worker", claim["fencing_token"], now, "failed", {},
                {"code": "collection_failed", "message": "分析失败"})
    return job["id"]


def test_finished_job_remains_queryable_after_old_gc_window(postgres_runtime):
    job_id = _failed_job(postgres_runtime.analysis_jobs, 1)
    progress = get_progress(job_id)
    assert progress is not None and progress["done"] is True
    assert progress["status"] == "failed"


def test_query_does_not_delete_old_history(postgres_runtime):
    repo = postgres_runtime.analysis_jobs
    old_id = _failed_job(repo, 1)
    recent_id = _failed_job(repo, 10000)
    get_progress(recent_id)
    assert get_progress(old_id)["status"] == "failed"


def test_running_job_is_not_mistaken_for_terminal(postgres_runtime):
    repo = postgres_runtime.analysis_jobs
    job, _ = repo.enqueue([{"mid": 1}], "test", 1)
    repo.claim("worker", 2)
    assert get_progress(job["id"])["done"] is False


def test_history_is_not_capped_to_five_jobs(postgres_runtime):
    ids = [_failed_job(postgres_runtime.analysis_jobs, 10 + i) for i in range(10)]
    assert all(get_progress(job_id)["done"] for job_id in ids)


def test_unknown_task_is_none(postgres_runtime):
    assert get_progress("unknown") is None


def test_progress_does_not_copy_full_collector_result(postgres_runtime):
    job_id = _failed_job(postgres_runtime.analysis_jobs, 1)
    progress = get_progress(job_id)
    assert progress is not None and "result" not in progress
