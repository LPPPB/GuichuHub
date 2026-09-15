"""Business time-series and calendar queue persistence."""

from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import sessionmaker

from storage.models import calendar_backfill_job_items, calendar_backfill_jobs, video_observations, videos


class BusinessRepository:
    def __init__(self, session_factory):
        self._sessions = session_factory

    @classmethod
    def from_url(cls, url: str) -> "BusinessRepository":
        engine = create_engine(url, pool_pre_ping=True)
        return cls(sessionmaker(bind=engine, expire_on_commit=False))

    def record_video(self, video: dict) -> None:
        row = {
            "bvid": video["bvid"], "mid": video.get("mid"), "title": video.get("title"),
            "tid": video.get("tid"), "tname": video.get("tname"), "pub_date": video.get("pub_date"),
            "duration": video.get("duration"), "first_seen": video["first_seen"],
            "source": video.get("source"), "observe_tier": video.get("observe_tier", "hot"), "pic": video.get("pic"),
        }
        statement = insert(videos).values(**row).on_conflict_do_update(
            index_elements=[videos.c.bvid],
            set_={key: value for key, value in row.items() if key not in {"bvid", "first_seen"} and value is not None},
        )
        with self._sessions.begin() as session:
            session.execute(statement)

    def record_observation(self, bvid: str, ts: int, metrics: dict) -> None:
        row = {"bvid": bvid, "ts": ts, "views": metrics.get("views"), "likes": metrics.get("likes")}
        statement = insert(video_observations).values(**row).on_conflict_do_update(
            index_elements=[video_observations.c.bvid, video_observations.c.ts], set_=row
        )
        with self._sessions.begin() as session:
            session.execute(statement)

    def video_trend(self, bvid: str, start_ts: int) -> list[dict]:
        with self._sessions() as session:
            rows = session.execute(
                select(video_observations.c.ts, video_observations.c.views, video_observations.c.likes)
                .where(video_observations.c.bvid == bvid, video_observations.c.ts >= start_ts)
                .order_by(video_observations.c.ts)
            ).mappings()
            return [dict(row) for row in rows]

    def enqueue_calendar_items(self, job_id: str, mids: list[int]) -> None:
        with self._sessions.begin() as session:
            session.execute(insert(calendar_backfill_jobs).values(
                id=job_id, mode="test", status="queued", payload={}, created_at=0, updated_at=0
            ).on_conflict_do_nothing(index_elements=[calendar_backfill_jobs.c.id]))
            session.execute(insert(calendar_backfill_job_items).values([
                {"job_id": job_id, "mid": mid, "status": "queued", "payload": {}} for mid in mids
            ]).on_conflict_do_nothing(index_elements=[calendar_backfill_job_items.c.job_id, calendar_backfill_job_items.c.mid]))

    def claim_calendar_item(self, worker_id: str) -> dict | None:
        with self._sessions.begin() as session:
            item = session.execute(
                select(calendar_backfill_job_items)
                .where(calendar_backfill_job_items.c.status == "queued")
                .order_by(calendar_backfill_job_items.c.job_id, calendar_backfill_job_items.c.mid)
                .with_for_update(skip_locked=True)
                .limit(1)
            ).mappings().first()
            if item is None:
                return None
            session.execute(
                calendar_backfill_job_items.update()
                .where(calendar_backfill_job_items.c.job_id == item["job_id"], calendar_backfill_job_items.c.mid == item["mid"])
                .values(status="running", worker_id=worker_id)
            )
            return {"job_id": item["job_id"], "mid": item["mid"], "worker_id": worker_id}
