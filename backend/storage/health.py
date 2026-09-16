"""Readiness checks for PostgreSQL-backed API and Worker processes."""

from __future__ import annotations

import time

from sqlalchemy import text


class PostgresReadinessService:
    def __init__(self, probe, expected_revision: str, now=time.time, max_worker_age: int = 120):
        self._probe = probe
        self._expected_revision = expected_revision
        self._now = now
        self._max_worker_age = max_worker_age

    @classmethod
    def from_session_factory(cls, session_factory, expected_revision: str, worker_id: str | None = None):
        def probe():
            with session_factory() as session:
                session.execute(text("SELECT 1"))
                revision = session.execute(text("SELECT version_num FROM app.alembic_version")).scalar_one_or_none()
                statement = "SELECT MAX(heartbeat_at) FROM app.worker_heartbeats"
                params = {}
                if worker_id:
                    statement += " WHERE worker_id = :worker_id"
                    params["worker_id"] = worker_id
                heartbeat = session.execute(text(statement), params).scalar_one()
                return {"revision": revision, "worker_heartbeat": heartbeat}

        return cls(probe, expected_revision)

    def check(self) -> tuple[bool, str | None]:
        try:
            status = self._probe()
        except Exception:
            return False, "database_unavailable"
        if status.get("revision") != self._expected_revision:
            return False, "migration_not_current"
        heartbeat = status.get("worker_heartbeat")
        if heartbeat is None or self._now() - heartbeat > self._max_worker_age:
            return False, "worker_stale"
        return True, None
