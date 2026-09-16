"""Resumable framework for explicit, idempotent PostgreSQL backfill jobs."""

from __future__ import annotations

import argparse
import importlib
import time
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import sessionmaker

from storage.models import backfill_progress


def run_resumable_backfill(session_factory, name: str, step, max_steps: int | None = None) -> bool:
    """Run bounded idempotent steps, persisting the cursor after every step.

    ``step(cursor)`` returns ``(next_cursor, completed)``.  A restart receives
    the last committed cursor; expensive work therefore stays out of Alembic.
    Individual steps must tolerate replay of work between their own side effect
    and the following cursor checkpoint.
    """
    if not name:
        raise ValueError("backfill name is required")
    count = 0
    while max_steps is None or count < max_steps:
        with session_factory.begin() as session:
            progress = session.execute(select(backfill_progress).where(
                backfill_progress.c.name == name,
            ).with_for_update()).mappings().first()
            if progress is not None and progress["status"] == "completed":
                return True
            cursor = dict(progress["cursor"]) if progress is not None else {}
            if progress is None:
                session.execute(insert(backfill_progress).values(
                    name=name, cursor=cursor, status="running", updated_at=int(time.time()),
                ))

        next_cursor, completed = step(cursor)
        if not isinstance(next_cursor, dict):
            raise ValueError("backfill step must return a JSON object cursor")
        with session_factory.begin() as session:
            session.execute(backfill_progress.update().where(
                backfill_progress.c.name == name,
            ).values(cursor=next_cursor, status="completed" if completed else "running",
                     updated_at=int(time.time())))
        count += 1
        if completed:
            return True
    return False


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one explicit resumable PostgreSQL backfill")
    parser.add_argument("--database-url-file", required=True, type=Path)
    parser.add_argument("--name", required=True)
    parser.add_argument("--handler", required=True, help="module:function accepting a cursor")
    parser.add_argument("--max-steps", type=int, default=1)
    return parser.parse_args()


if __name__ == "__main__":
    args = _arguments()
    url = args.database_url_file.read_text(encoding="utf-8").strip()
    if not url.startswith("postgresql"):
        raise SystemExit("PostgreSQL database URL is required")
    module_name, function_name = args.handler.split(":", 1)
    step = getattr(importlib.import_module(module_name), function_name)
    sessions = sessionmaker(bind=create_engine(url, pool_pre_ping=True), expire_on_commit=False)
    raise SystemExit(0 if run_resumable_backfill(sessions, args.name, step, args.max_steps) else 1)
