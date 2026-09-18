"""Explicit PostgreSQL runtime wiring for API and Worker processes.

This module deliberately performs no database work.  It only reads the
role-specific protected URL file, builds a SQLAlchemy session factory, and
installs the existing storage adapters around PostgreSQL repositories.  DDL is
owned exclusively by the separate Alembic maintenance command.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from storage import auth_store, database, db, runtime_settings, tracked_ups
from storage.postgres import create_session_factory
from storage.repositories.auth import AuthRepository
from storage.repositories.business import BusinessRepository
from storage.repositories.state import StateRepository
from storage.settings import DatabaseSettings


@dataclass(frozen=True)
class PostgresRuntime:
    """Repositories installed for one independently configured process."""

    role: str
    sessions: object
    business: BusinessRepository
    auth: AuthRepository
    state: StateRepository


def configure_postgres_runtime(role: str, env: Mapping[str, str] | None = None) -> PostgresRuntime:
    """Install PostgreSQL-backed storage adapters without connecting or running DDL."""
    settings = DatabaseSettings.from_environment(os.environ if env is None else env, role)
    sessions = create_session_factory(settings)
    runtime = PostgresRuntime(
        role=role,
        sessions=sessions,
        business=BusinessRepository(sessions),
        auth=AuthRepository(sessions),
        state=StateRepository(sessions),
    )
    db.configure_business_repository(runtime.business)
    auth_store.configure_auth_repository(runtime.auth)
    database.configure_state_repository(runtime.state)
    runtime_settings.configure_runtime_settings_repository(runtime.state)
    tracked_ups.configure_state_repository(runtime.state)
    return runtime
