"""Compatibility adapters: API and scheduler submit/query durable Worker jobs."""
import time

from storage.repositories.analysis_jobs import get_analysis_repository, TERMINAL


def _repository():
    repository = get_analysis_repository()
    if repository is None:
        raise RuntimeError("PostgreSQL analysis repository is not configured")
    return repository


def start_analysis(enabled_ups: list[dict], requested_by: str = "system") -> str | None:
    job, created = _repository().enqueue(enabled_ups, requested_by, int(time.time()))
    return job["id"] if created else None


def get_running_task_id() -> str | None:
    job = _repository().active()
    return job["id"] if job else None


def get_progress(task_id: str) -> dict | None:
    job = _repository().get(task_id)
    if job is None:
        return None
    summary = job["result_summary"]
    return {
        **job["progress"], "task_id": job["id"], "status": job["status"],
        "done": job["status"] in TERMINAL, "started_at": job["started_at"],
        "finished_at": job["finished_at"], "error": job["error"],
        "warnings": summary.get("warnings", []),
        "calendar_job_id": summary.get("calendar_job_id"),
        **{key: summary[key] for key in ("up_obs_ts", "up_obs_rows",
           "video_obs_snapshot_ts", "video_obs_snapshot_fields") if key in summary},
    }
