"""Alembic baseline integration tests against a disposable PostgreSQL 16 container."""

import os
import subprocess
import time

import pytest
from sqlalchemy import create_engine, inspect, text

from storage.models import Base
from storage.migrations import alembic_heads, upgrade_database


def test_alembic_has_one_postgresql_baseline_head():
    """Adding an unmerged Alembic revision must fail the release gate."""
    assert alembic_heads() == ["0001_postgresql_v3_baseline"]


@pytest.fixture(scope="module")
def postgres_url():
    container_id = subprocess.check_output(
        [
            "docker", "run", "--rm", "-d", "-e", "POSTGRES_PASSWORD=test-password",
            "-e", "POSTGRES_DB=kichu_test", "-p", "127.0.0.1::5432", "postgres:16-alpine",
        ],
        text=True,
    ).strip()
    try:
        port_line = subprocess.check_output(
            ["docker", "port", container_id, "5432/tcp"], text=True
        ).strip()
        port = port_line.rsplit(":", 1)[1]
        url = f"postgresql+psycopg://postgres:test-password@127.0.0.1:{port}/kichu_test"
        engine = create_engine(url)
        for _ in range(30):
            try:
                with engine.connect() as connection:
                    connection.execute(text("SELECT 1"))
                break
            except Exception:
                time.sleep(1)
        else:
            pytest.fail("disposable PostgreSQL did not become ready")
        yield url
    finally:
        subprocess.run(["docker", "stop", container_id], check=False)


def test_empty_postgres_upgrades_to_baseline(postgres_url):
    """Removing schema creation from the Alembic revision must fail this initialization contract."""
    upgrade_database(postgres_url)

    engine = create_engine(postgres_url)
    inspector = inspect(engine)
    assert {"app", "auth"} <= set(inspector.get_schema_names())
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM app.alembic_version")).scalar_one() == "0001_postgresql_v3_baseline"
    assert {"videos", "dashboard_state", "worker_heartbeats"} <= set(inspector.get_table_names(schema="app"))
    assert {"admin_accounts", "browser_sessions", "collector_credential_handoffs"} <= set(inspector.get_table_names(schema="auth"))
