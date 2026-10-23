"""pytest 共享 fixture

替代 V1 每个测试文件的 sys.path.insert 自注入。
"""

import os
import sys
import subprocess
import tempfile
import time
import uuid

import pytest

# 把 backend/ 与仓库根目录加入 sys.path（替代 V1 每个测试文件的 sys.path.insert）。
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPOSITORY_ROOT = os.path.dirname(BACKEND_DIR)
sys.path.insert(0, REPOSITORY_ROOT)
sys.path.insert(0, BACKEND_DIR)


def _provision_postgres_database(server_url):
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    database_name = f"kichu_test_{uuid.uuid4().hex}"
    admin_engine = create_engine(server_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    database_url = make_url(server_url).set(database=database_name).render_as_string(
        hide_password=False,
    )
    return database_name, database_url, admin_engine


def _drop_postgres_database(database_name, admin_engine):
    from sqlalchemy import text

    with admin_engine.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'))
    admin_engine.dispose()


@pytest.fixture
def tmp_db(monkeypatch):
    """每测试独立临时 DB"""
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, 'test.db')
    monkeypatch.setenv('DB_PATH', db_path)
    yield db_path


@pytest.fixture(scope="session")
def postgres_server_url():
    """One disposable PostgreSQL 16 server shared by isolated test databases."""
    from sqlalchemy import create_engine, text

    # CI/container runners may supply a dedicated disposable PostgreSQL server.
    # Never use a production connection: this fixture creates and drops databases.
    external = os.environ.get("KICHU_TEST_POSTGRES_SERVER_URL")
    if external:
        from sqlalchemy.engine import make_url
        url = make_url(external)
        if url.username != "kichu_test_owner" or url.database != "postgres":
            pytest.fail("external test server must use the dedicated test owner and postgres database")
        engine = create_engine(external)
        for _ in range(30):
            try:
                with engine.connect() as connection:
                    connection.execute(text("SELECT 1"))
                break
            except Exception:
                time.sleep(1)
        else:
            pytest.fail("dedicated test PostgreSQL did not become ready")
        engine.dispose()
        yield external
        return

    container_id = subprocess.check_output(
        [
            "docker", "run", "--rm", "-d", "-e", "POSTGRES_USER=kichu_test_owner",
            "-e", "POSTGRES_PASSWORD=ephemeral-test-password", "-e", "POSTGRES_DB=postgres",
            "-p", "127.0.0.1::5432", "postgres:16-alpine",
        ],
        text=True,
    ).strip()
    try:
        port = subprocess.check_output(
            ["docker", "port", container_id, "5432/tcp"], text=True,
        ).strip().rsplit(":", 1)[1]
        url = f"postgresql+psycopg://kichu_test_owner:ephemeral-test-password@127.0.0.1:{port}/postgres"
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
        engine.dispose()
        yield url
    finally:
        subprocess.run(["docker", "stop", container_id], check=False)


@pytest.fixture(scope="session")
def postgres_url(postgres_server_url):
    """A migrated PostgreSQL database isolated to this pytest session."""
    from storage.migrations import upgrade_database

    database_name, database_url, admin_engine = _provision_postgres_database(postgres_server_url)
    upgrade_database(database_url)
    try:
        yield database_url
    finally:
        _drop_postgres_database(database_name, admin_engine)


@pytest.fixture
def empty_postgres_url(postgres_server_url):
    """A clean, unmigrated database for Alembic initialization contracts."""
    database_name, database_url, admin_engine = _provision_postgres_database(postgres_server_url)
    try:
        yield database_url
    finally:
        _drop_postgres_database(database_name, admin_engine)


@pytest.fixture
def clean_postgres_data(postgres_url):
    """Remove application rows without touching Alembic's version table."""
    from sqlalchemy import create_engine, text
    from storage.models import Base

    engine = create_engine(postgres_url)
    tables = sorted(
        Base.metadata.tables.values(),
        key=lambda table: len(table.foreign_keys),
        reverse=True,
    )
    identifiers = ", ".join(f'"{table.schema}"."{table.name}"' for table in tables)
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE TABLE {identifiers} RESTART IDENTITY CASCADE"))
    try:
        yield postgres_url
    finally:
        engine.dispose()


@pytest.fixture
def postgres_runtime(clean_postgres_data, tmp_path):
    """Install all compatibility adapters against a migrated disposable database."""
    from storage import auth_store, database, db, runtime_settings, tracked_ups
    from storage.runtime import configure_postgres_runtime

    url_file = tmp_path / "postgres-test-url"
    url_file.write_text(clean_postgres_data, encoding="utf-8")
    runtime = configure_postgres_runtime(
        "offline", {"KICHU_DATABASE_URL_FILE": str(url_file)},
    )
    # Repository tests use explicit synthetic epochs. Fresh-clock boundary
    # tests override this independently; production retains time.time.
    runtime.analysis_jobs._clock = lambda: 0
    try:
        yield runtime
    finally:
        from storage.repositories.analysis_jobs import configure_analysis_repository
        from jobs.collection_lock import configure_collection_lock
        configure_collection_lock(None)
        from storage.repositories.collection_state import configure_collection_repository
        configure_collection_repository(None)
        configure_analysis_repository(None)
        from storage.repositories.radar import configure_radar_repository
        configure_radar_repository(None)
        db.configure_business_repository(None)
        auth_store.configure_auth_repository(None)
        database.configure_state_repository(None)
        runtime_settings.configure_runtime_settings_repository(None)
        tracked_ups.configure_state_repository(None)
        runtime.sessions.kw["bind"].dispose()


@pytest.fixture
def client(postgres_runtime):
    """Flask test client"""
    from app import app
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c
