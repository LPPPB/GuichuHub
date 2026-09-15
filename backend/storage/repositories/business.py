"""Business time-series and calendar queue persistence."""

from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import sessionmaker

from storage.models import calendar_backfill_job_items, calendar_backfill_jobs, crawl_runs, up_observations, ups, video_observations, video_snapshot_documents, videos, word_observations


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

    def begin_crawl_run(self, trigger: str, started_at: int) -> int:
        with self._sessions.begin() as session:
            return session.execute(insert(crawl_runs).values(
                started_at=started_at, status="running", trigger_source=trigger, stats={}
            ).returning(crawl_runs.c.id)).scalar_one()

    def finish_crawl_run(self, run_id: int, status: str, stats: dict, finished_at: int) -> None:
        with self._sessions.begin() as session:
            session.execute(crawl_runs.update().where(crawl_runs.c.id == run_id).values(
                status=status, stats=stats, finished_at=finished_at
            ))

    def record_words(self, words: list[dict], ts: int, scope: str) -> None:
        rows = [{"word": word["word"], "count": word["count"], "ts": ts, "scope": scope} for word in words if word.get("word")]
        if not rows:
            return
        with self._sessions.begin() as session:
            session.execute(insert(word_observations).values(rows).on_conflict_do_update(
                index_elements=[word_observations.c.word, word_observations.c.ts, word_observations.c.scope],
                set_={"count": insert(word_observations).excluded.count},
            ))

    def word_rows(self, ts: int) -> list[dict]:
        with self._sessions() as session:
            return [dict(row) for row in session.execute(
                select(word_observations.c.word, word_observations.c.count, word_observations.c.scope)
                .where(word_observations.c.ts == ts).order_by(word_observations.c.word)
            ).mappings()]

    def crawl_run(self, run_id: int) -> dict:
        with self._sessions() as session:
            row = session.execute(select(crawl_runs.c.status, crawl_runs.c.stats).where(crawl_runs.c.id == run_id)).mappings().one()
            return dict(row)

    def upsert_snapshot_document(self, ts: int, field: str, payload: list | dict) -> int:
        item_count = len(payload) if isinstance(payload, list) else 1
        with self._sessions.begin() as session:
            session.execute(insert(video_snapshot_documents).values(
                ts=ts, field=field, payload=payload, item_count=item_count
            ).on_conflict_do_update(
                index_elements=[video_snapshot_documents.c.ts, video_snapshot_documents.c.field],
                set_={"payload": payload, "item_count": item_count},
            ))
        return item_count

    def snapshot_document(self, ts: int, field: str) -> dict:
        with self._sessions() as session:
            return dict(session.execute(
                select(video_snapshot_documents.c.payload, video_snapshot_documents.c.item_count)
                .where(video_snapshot_documents.c.ts == ts, video_snapshot_documents.c.field == field)
            ).mappings().one())

    def upsert_snapshot_batch(self, ts: int, fields: dict[str, list | dict]) -> int:
        rows = [
            {"ts": ts, "field": field, "payload": payload,
             "item_count": len(payload) if isinstance(payload, list) else 1}
            for field, payload in fields.items()
        ]
        with self._sessions.begin() as session:
            for row in rows:
                session.execute(insert(video_snapshot_documents).values(**row).on_conflict_do_update(
                    index_elements=[video_snapshot_documents.c.ts, video_snapshot_documents.c.field],
                    set_={"payload": row["payload"], "item_count": row["item_count"]},
                ))
        return len(rows)

    def upsert_up_observations(self, ts: int, observations: list[dict]) -> int:
        rows = [row for row in observations if row.get("mid") is not None]
        with self._sessions.begin() as session:
            for row in rows:
                session.execute(insert(ups).values(
                    mid=row["mid"], name=row.get("name"), face=row.get("face"), tracked=False
                ).on_conflict_do_nothing(index_elements=[ups.c.mid]))
                session.execute(insert(up_observations).values(
                    mid=row["mid"], ts=ts, payload=row
                ).on_conflict_do_update(
                    index_elements=[up_observations.c.mid, up_observations.c.ts], set_={"payload": row}
                ))
        return len(rows)

    def up_observation(self, mid: int, ts: int) -> dict:
        with self._sessions() as session:
            return dict(session.execute(
                select(up_observations.c.mid, up_observations.c.payload)
                .where(up_observations.c.mid == mid, up_observations.c.ts == ts)
            ).mappings().one())

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
