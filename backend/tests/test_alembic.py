"""Alembic baseline integration tests against a disposable PostgreSQL 16 container."""

from sqlalchemy import create_engine, inspect, text

from storage.models import Base
from storage.migrations import alembic_heads, upgrade_database


def test_alembic_has_one_postgresql_baseline_head():
    """Adding an unmerged Alembic revision must fail the release gate."""
    assert alembic_heads() == ["0004_radar_v2"]


def test_empty_postgres_upgrades_to_baseline(empty_postgres_url):
    """Removing schema creation from the Alembic revision must fail this initialization contract."""
    upgrade_database(empty_postgres_url)

    engine = create_engine(empty_postgres_url)
    inspector = inspect(engine)
    assert {"app", "auth"} <= set(inspector.get_schema_names())
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM app.alembic_version")).scalar_one() == "0004_radar_v2"
    assert {"videos", "dashboard_state", "worker_heartbeats"} <= set(inspector.get_table_names(schema="app"))
    assert {"admin_accounts", "browser_sessions", "collector_credential_handoffs"} <= set(inspector.get_table_names(schema="auth"))
