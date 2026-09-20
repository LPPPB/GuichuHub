"""Explicit maintenance-only Alembic upgrade command."""

from __future__ import annotations

import os
import argparse

from sqlalchemy import text

from storage.migrations import alembic_heads, upgrade_database
from storage.postgres import create_session_factory
from storage.settings import DatabaseSettings


def migrate() -> str:
    settings = DatabaseSettings.from_environment(os.environ, "migration")
    heads = alembic_heads()
    if len(heads) != 1:
        raise RuntimeError("Alembic must have exactly one head")
    upgrade_database(settings.url.render_as_string(hide_password=False))
    sessions = create_session_factory(settings)
    with sessions() as session:
        revision = session.execute(text("SELECT version_num FROM app.alembic_version")).scalar_one_or_none()
    if revision != heads[0]:
        raise RuntimeError("Alembic revision verification failed")
    return revision


if __name__ == "__main__":
    argparse.ArgumentParser(description="Upgrade PostgreSQL to the current Alembic head").parse_args()
    migrate()
