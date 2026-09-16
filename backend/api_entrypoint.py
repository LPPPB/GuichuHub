"""Production WSGI entrypoint for the HTTP API.

The API process only wires already-migrated PostgreSQL repositories.  It never
creates tables, invokes Alembic, or creates legacy runtime files.
"""

from storage.health import PostgresReadinessService
from storage.migrations import alembic_heads
from storage.runtime import configure_postgres_runtime


runtime = configure_postgres_runtime("api")
heads = alembic_heads()
if len(heads) != 1:
    raise RuntimeError("Alembic must have exactly one head")

from app import app


app.config["READINESS_SERVICE"] = PostgresReadinessService.from_session_factory(
    runtime.sessions, expected_revision=heads[0], worker_id="worker",
)


__all__ = ["app"]
