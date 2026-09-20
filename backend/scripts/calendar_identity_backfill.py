"""Reconcile legacy calendar-video identity before revision 0002.

This is intentionally a bounded, resumable maintenance job rather than an
Alembic data migration: existing 0001 databases may contain an unbounded
history of duplicate ``bvid`` rows.  New empty databases need not run it.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from sqlalchemy import text

from storage.postgres import create_engine


BACKFILL_NAME = "calendar_identity_v1"


def run_calendar_identity_backfill(
    database_url: str, *, batch_size: int = 500, max_steps: int | None = None
) -> bool:
    """Preserve calendar authors and collapse one bounded BVID page per step."""
    if batch_size <= 0:
        raise ValueError("batch size must be positive")
    engine = create_engine(database_url, pool_pre_ping=True)

    def step() -> bool | None:
        """Return completion, or None while another runner owns the row lock."""
        with engine.begin() as connection:
            connection.execute(text("""
                INSERT INTO app.backfill_progress(name, cursor, status, updated_at)
                VALUES (:name, CAST(:cursor AS JSONB), 'running', :now)
                ON CONFLICT (name) DO NOTHING
            """), {"name": BACKFILL_NAME, "cursor": json.dumps({}), "now": int(time.time())})
            progress = connection.execute(text("""
                SELECT cursor, status FROM app.backfill_progress
                WHERE name = :name
                FOR UPDATE SKIP LOCKED
            """), {"name": BACKFILL_NAME}).mappings().first()
            if progress is None:
                return None
            if progress["status"] == "completed":
                return True
            after_bvid = str((progress["cursor"] or {}).get("after_bvid", ""))
            bvids = connection.execute(
                text("""
                    SELECT DISTINCT bvid
                    FROM app.calendar_videos
                    WHERE bvid > :after_bvid
                    ORDER BY bvid
                    LIMIT :batch_size
                """),
                {"after_bvid": after_bvid, "batch_size": batch_size},
            ).scalars().all()
            for bvid in bvids:
                connection.execute(text("""
                    INSERT INTO app.calendar_video_authors(
                        bvid, mid, last_seen_at, missing_count, status
                    )
                    SELECT bvid, mid, last_seen_at, missing_count, status
                    FROM app.calendar_videos
                    WHERE bvid = :bvid
                    ON CONFLICT (bvid, mid) DO NOTHING
                """), {"bvid": bvid})
                best = connection.execute(text("""
                    SELECT mid, pub_date, pub_date_str, views, title, fetched_at
                    FROM app.calendar_videos
                    WHERE bvid = :bvid
                    ORDER BY views DESC, fetched_at DESC, mid
                    LIMIT 1
                """), {"bvid": bvid}).mappings().one()
                keep_mid = connection.execute(text("""
                    SELECT min(mid) FROM app.calendar_videos WHERE bvid = :bvid
                """), {"bvid": bvid}).scalar_one()
                connection.execute(text("""
                    UPDATE app.calendar_videos
                    SET pub_date = :pub_date, pub_date_str = :pub_date_str,
                        views = :views, title = :title, fetched_at = :fetched_at
                    WHERE bvid = :bvid AND mid = :keep_mid
                """), {**best, "bvid": bvid, "keep_mid": keep_mid})
                connection.execute(text("""
                    DELETE FROM app.calendar_videos
                    WHERE bvid = :bvid AND mid <> :keep_mid
                """), {"bvid": bvid, "keep_mid": keep_mid})
            completed = not bvids
            next_cursor = {"after_bvid": after_bvid if completed else bvids[-1]}
            connection.execute(text("""
                UPDATE app.backfill_progress
                SET cursor = CAST(:cursor AS JSONB),
                    status = :status,
                    updated_at = :now
                WHERE name = :name
            """), {
                "name": BACKFILL_NAME,
                "cursor": json.dumps(next_cursor),
                "status": "completed" if completed else "running",
                "now": int(time.time()),
            })
            return completed

    try:
        steps = 0
        while max_steps is None or steps < max_steps:
            completed = step()
            if completed is None:
                return False
            steps += 1
            if completed:
                return True
        return False
    finally:
        engine.dispose()


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reconcile legacy calendar identity before revision 0002")
    parser.add_argument("--database-url-file", required=True, type=Path)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--max-steps", type=int, default=1)
    return parser.parse_args()


if __name__ == "__main__":
    args = _arguments()
    url = args.database_url_file.read_text(encoding="utf-8").strip()
    if not url.startswith("postgresql"):
        raise SystemExit("PostgreSQL database URL is required")
    complete = run_calendar_identity_backfill(
        url, batch_size=args.batch_size, max_steps=args.max_steps
    )
    raise SystemExit(0 if complete else 1)
