"""PostgreSQL authentication repository contracts."""

import time

import pytest

from storage.migrations import upgrade_database
from storage.repositories.auth import AuthRepository


@pytest.fixture
def auth_repository(clean_postgres_data, postgres_url):
    upgrade_database(postgres_url)
    repository = AuthRepository.from_url(postgres_url)
    try:
        yield repository
    finally:
        from storage import auth_store
        auth_store.configure_auth_repository(None)
        repository._sessions.kw["bind"].dispose()


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


def test_legacy_admin_store_uses_configured_postgresql_repository(auth_repository):
    from storage import auth_store

    auth_store.configure_auth_repository(auth_repository)
    row, error = auth_store.add_admin_account(8, "管理员", "face", "bootstrap")

    assert error is None
    assert row in auth_repository.list_admin_accounts()
    assert auth_store.is_admin_mid(8) is True


def test_legacy_credential_handoff_uses_configured_postgresql_repository(auth_repository):
    from storage import auth_store

    auth_store.configure_auth_repository(auth_repository)
    handoff_id = auth_store.request_collector_cookie_update({"SESSDATA": "secret"}, "admin")

    assert auth_repository.pending_collector_action()["id"] == handoff_id
    assert auth_store.complete_collector_action(handoff_id) is True


def test_session_cleanup_and_recent_logins_use_postgresql(auth_repository):
    auth_repository.create_session("visitor-a", 11, "A", "", {}, now=100)
    auth_repository.create_session("visitor-b", 22, "B", "", {}, now=200)

    mids = [row["mid"] for row in auth_repository.list_recent_logins()]
    assert mids.index(22) < mids.index(11)
    token = auth_repository.create_session("visitor-c", 33, "C", "", {}, now=300)
    assert auth_repository.delete_session(token) is True
    assert auth_repository.purge_expired_sessions(now=31 * 24 * 3600 + 101) >= 2
