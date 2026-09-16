"""PostgreSQL authentication repository contracts."""

import subprocess
import time

import pytest
from sqlalchemy import create_engine, text

from storage.migrations import upgrade_database
from storage.repositories.auth import AuthRepository


@pytest.fixture(scope="module")
def auth_repository():
    container_id = subprocess.check_output(
        [
            "docker", "run", "--rm", "-d", "-e", "POSTGRES_PASSWORD=test-password",
            "-e", "POSTGRES_DB=kichu_test", "-p", "127.0.0.1::5432", "postgres:16-alpine",
        ],
        text=True,
    ).strip()
    try:
        port = subprocess.check_output(
            ["docker", "port", container_id, "5432/tcp"], text=True
        ).strip().rsplit(":", 1)[1]
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
        upgrade_database(url)
        yield AuthRepository.from_url(url)
    finally:
        try:
            from storage import auth_store
            auth_store.configure_auth_repository(None)
        except ImportError:
            pass
        subprocess.run(["docker", "stop", container_id], check=False)


def test_session_result_never_contains_cookie(auth_repository):
    token = auth_repository.create_session(
        "visitor", 1, "admin", "face", {"SESSDATA": "secret"}, now=100,
    )

    assert auth_repository.get_session(token, now=101) == {
        "token": token, "visitor_id": "visitor", "mid": 1, "name": "admin",
        "face": "face", "created_at": 100, "expires_at": 100 + 30 * 24 * 3600,
    }


def test_last_admin_cannot_be_removed(auth_repository):
    auth_repository.add_admin_account(1, "admin", "face", "bootstrap", now=100)

    assert auth_repository.remove_admin_account(1) == (False, "LAST_ADMIN")


def test_legacy_auth_store_uses_configured_postgresql_repository(auth_repository):
    from storage import auth_store

    auth_store.configure_auth_repository(auth_repository)
    token = auth_store.create_session("visitor-2", 2, "admin", "face", {"SESSDATA": "secret"})

    assert auth_repository.get_session(token, now=int(time.time()))["visitor_id"] == "visitor-2"
    assert "cookies" not in auth_store.get_session(token)
