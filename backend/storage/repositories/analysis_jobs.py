"""Durable UP analysis ownership and atomic core commits, without network I/O."""
import uuid

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from storage.models import up_analysis_jobs as jobs, up_observations, video_snapshot_documents, worker_heartbeats

ACTIVE = ("queued", "running", "finalizing")
TERMINAL = ("succeeded", "partial", "failed")
_repository = None


def configure_analysis_repository(repository):
    global _repository
    _repository = repository


def get_analysis_repository():
    return _repository


class LostAnalysisLease(RuntimeError):
    """The caller no longer owns this live job; it must stop writing."""


class AnalysisJobRepository:
    def __init__(self, sessions, business):
        self._sessions = sessions
        self._business = business

    @staticmethod
    def _id(job_id):
        try:
            return str(uuid.UUID(str(job_id)))
        except (ValueError, TypeError, AttributeError):
            return None

    @staticmethod
    def _active_query():
        return select(jobs).where(jobs.c.status.in_(ACTIVE)).order_by(jobs.c.created_at).limit(1)

    def get(self, job_id: str) -> dict | None:
        job_id = self._id(job_id)
        if job_id is None:
            return None
        with self._sessions() as session:
            row = session.execute(select(jobs).where(jobs.c.id == job_id)).mappings().first()
            return dict(row) if row else None

    def active(self) -> dict | None:
        with self._sessions() as session:
            row = session.execute(self._active_query()).mappings().first()
            return dict(row) if row else None

    def worker_available(self, now: int) -> bool:
        with self._sessions() as session:
            heartbeat = session.scalar(select(func.max(worker_heartbeats.c.heartbeat_at)))
            return heartbeat is not None and now - heartbeat <= 120

    def enqueue(self, roster: list[dict], requested_by: str, now: int) -> tuple[dict, bool]:
        if not roster:
            raise ValueError("没有已启用的UP主")
        with self._sessions.begin() as session:
            session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended("up-analysis", 0))))
            active = session.execute(self._active_query()).mappings().first()
            if active:
                return dict(active), False
            progress = {"total": len(roster), "current": 0, "current_up": "等待 Worker 执行", "eta_seconds": 0}
            row = session.execute(insert(jobs).values(
                id=str(uuid.uuid4()), requested_by=requested_by, roster=roster,
                progress=progress, status="queued", created_at=now, updated_at=now,
            ).returning(jobs)).mappings().one()
            return dict(row), True

    def claim(self, worker_id: str, now: int, lease_seconds: int = 120) -> dict | None:
        with self._sessions.begin() as session:
            row = session.execute(select(jobs).where(or_(
                jobs.c.status == "queued",
                and_(jobs.c.status.in_(("running", "finalizing")), jobs.c.lease_until <= now),
            )).order_by(jobs.c.created_at).with_for_update(skip_locked=True).limit(1)).mappings().first()
            if not row:
                return None
            if row["attempts"] >= 3:
                session.execute(update(jobs).where(jobs.c.id == row["id"]).values(
                    status="failed", finished_at=now, updated_at=now, lease_until=None,
                    error={"code": "attempts_exhausted", "message": "任务多次中断，已停止，请检查 Worker 后重新提交"},
                ))
                return None
            batch_ts = row["batch_ts"]
            if batch_ts is None:
                # Batch timestamps are existing observation keys; never overwrite
                # a previous job (or a legacy batch) submitted in the same second.
                last_ts = max(session.scalar(select(func.max(table.c.ts))) or 0
                              for table in (up_observations, video_snapshot_documents))
                last_ts = max(last_ts, session.scalar(select(func.max(jobs.c.batch_ts))) or 0)
                batch_ts = max(now, last_ts + 1)
            claimed = session.execute(update(jobs).where(jobs.c.id == row["id"]).values(
                status="finalizing" if row["status"] == "finalizing" else "running",
                started_at=row["started_at"] if row["started_at"] is not None else now,
                updated_at=now, worker_id=worker_id, lease_until=now + lease_seconds,
                fencing_token=row["fencing_token"] + 1, attempts=row["attempts"] + 1,
                batch_ts=batch_ts,
            ).returning(jobs)).mappings().one()
            return dict(claimed)

    @staticmethod
    def _owned(session, job_id, worker_id, token, now):
        row = session.execute(select(jobs).where(
            jobs.c.id == job_id, jobs.c.worker_id == worker_id,
            jobs.c.fencing_token == token, jobs.c.status.in_(("running", "finalizing")),
            jobs.c.lease_until > now,
        ).with_for_update()).mappings().first()
        if not row:
            raise LostAnalysisLease("analysis job lease lost")
        return dict(row)

    def renew(self, job_id: str, worker_id: str, token: int, now: int) -> bool:
        with self._sessions.begin() as session:
            renewed = session.execute(update(jobs).where(
                jobs.c.id == job_id, jobs.c.worker_id == worker_id,
                jobs.c.fencing_token == token, jobs.c.status.in_(("running", "finalizing")),
                jobs.c.lease_until > now,
            ).values(lease_until=now + 120, updated_at=now))
            return renewed.rowcount == 1

    def update_progress(self, job_id: str, worker_id: str, token: int, now: int, progress: dict) -> None:
        with self._sessions.begin() as session:
            self._owned(session, job_id, worker_id, token, now)
            session.execute(update(jobs).where(jobs.c.id == job_id).values(progress=progress, updated_at=now))

    def commit_core(self, job_id: str, worker_id: str, token: int, now: int, result: dict) -> dict:
        with self._sessions.begin() as session:
            row = self._owned(session, job_id, worker_id, token, now)
            if row["status"] != "running":
                raise LostAnalysisLease("core data already committed")
            analysis = result.get("analysis", {})
            summary = analysis.get("summary", {})
            fields = {key: analysis.get(key, []) for key in (
                "timeline", "hot_videos", "all_videos", "content_types", "keyword_cloud",
            )}
            fields["pool_summary"] = {key: summary.get(key, 0) for key in (
                "total_views", "total_videos", "avg_views_per_video",
            )}
            up_count = self._business._write_up_observations(
                session, row["batch_ts"], result.get("up_trends", []),
                analysis.get("play_ranking"), analysis.get("creator_ranking"),
            )
            field_count = self._business._write_snapshot_batch(session, row["batch_ts"], fields)
            saved = {"up_obs_ts": row["batch_ts"], "up_obs_rows": up_count,
                     "video_obs_snapshot_ts": row["batch_ts"], "video_obs_snapshot_fields": field_count}
            updated = session.execute(update(jobs).where(jobs.c.id == job_id).values(
                status="finalizing", result_summary=saved, updated_at=now,
            ).returning(jobs)).mappings().one()
            return dict(updated)

    def finish(self, job_id: str, worker_id: str, token: int, now: int, status: str,
               summary: dict, error: dict | None = None) -> None:
        if status not in TERMINAL:
            raise ValueError("invalid analysis terminal status")
        with self._sessions.begin() as session:
            row = self._owned(session, job_id, worker_id, token, now)
            if status in ("succeeded", "partial") and row["status"] != "finalizing":
                raise ValueError("core data must be committed before success")
            progress = dict(row["progress"])
            progress["eta_seconds"] = 0
            if row["status"] == "finalizing":
                progress["current"] = progress["total"]
            session.execute(update(jobs).where(jobs.c.id == job_id).values(
                status=status, result_summary=summary, error=error, progress=progress,
                updated_at=now, finished_at=now, lease_until=None,
            ))
