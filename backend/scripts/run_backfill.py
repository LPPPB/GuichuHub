"""Resumable framework for explicit, idempotent PostgreSQL backfill jobs."""

from __future__ import annotations

import argparse
import importlib
import time
import uuid
from pathlib import Path

from sqlalchemy import or_, select
from storage.postgres import create_engine
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import sessionmaker

from storage.models import backfill_progress


def run_resumable_backfill(session_factory, name: str, step, max_steps: int | None = None,
                          *, now=time.time, lease_seconds: int = 300) -> bool:
    """Run bounded idempotent steps, persisting the cursor after every step.

    ``step(cursor)`` returns ``(next_cursor, completed)``.  A restart receives
    the last committed cursor; expensive work therefore stays out of Alembic.
    Individual steps must tolerate replay of work between their own side effect
    and the following cursor checkpoint.
    """
    if not name:
        raise ValueError("backfill name is required")
    if lease_seconds <= 0:
        raise ValueError("backfill lease must be positive")
    if max_steps is not None and max_steps <= 0:
        return False
    owner = uuid.uuid4().hex
    with session_factory.begin() as session:
        session.execute(insert(backfill_progress).values(name=name, cursor={}, status="running", updated_at=int(now()))
                        .on_conflict_do_nothing(index_elements=[backfill_progress.c.name]))
        claim = session.execute(backfill_progress.update().where(
            backfill_progress.c.name == name, backfill_progress.c.status != "completed",
            or_(backfill_progress.c.claim_owner.is_(None), backfill_progress.c.lease_until <= int(now())),
        ).values(claim_owner=owner, lease_until=int(now()) + lease_seconds,
                 fencing_token=backfill_progress.c.fencing_token + 1, updated_at=int(now()))
          .returning(backfill_progress.c.cursor, backfill_progress.c.fencing_token)).mappings().first()
        if claim is None:
            return session.execute(select(backfill_progress.c.status).where(backfill_progress.c.name == name)).scalar_one() == "completed"
    cursor, fence = dict(claim["cursor"]), claim["fencing_token"]
    owned = (backfill_progress.c.name == name, backfill_progress.c.claim_owner == owner,
             backfill_progress.c.fencing_token == fence)
    count = 0
    try:
        while max_steps is None or count < max_steps:
            next_cursor, completed = step(cursor)
            if not isinstance(next_cursor, dict):
                raise ValueError("backfill step must return a JSON object cursor")
            with session_factory.begin() as session:
                changed = session.execute(backfill_progress.update().where(
                    *owned, backfill_progress.c.lease_until > int(now()),
                ).values(cursor=next_cursor, status="completed" if completed else "running",
                         updated_at=int(now()), lease_until=int(now()) + lease_seconds)).rowcount
                if changed != 1:
                    raise RuntimeError("backfill claim expired or was replaced; checkpoint rejected")
            cursor = next_cursor
            count += 1
            if completed:
                return True
        return False
    finally:
        with session_factory.begin() as session:
            session.execute(backfill_progress.update().where(*owned).values(claim_owner=None, lease_until=None))


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
