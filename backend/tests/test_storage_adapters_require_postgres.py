"""Persistent storage adapters fail closed instead of using file databases."""

import pytest

from storage import auth_store, cache, database, tracked_ups


def _close_legacy_auth_connection():
    thread_local = getattr(auth_store, "_thread_local", None)
    connection = getattr(thread_local, "conn", None)
    if connection is not None:
        connection.close()
        thread_local.conn = None


def test_auth_store_requires_postgres_without_sqlite_fallback(monkeypatch, tmp_path):
    auth_store.configure_auth_repository(None)
    auth_path = tmp_path / "auth.db"
    monkeypatch.setattr(auth_store, "AUTH_DB_PATH", str(auth_path), raising=False)

    try:
        with pytest.raises(RuntimeError, match="PostgreSQL"):
            auth_store.admin_count()
    finally:
        _close_legacy_auth_connection()

    assert not auth_path.exists()


def test_dashboard_state_requires_postgres_without_json_or_lock_files(monkeypatch, tmp_path):
    database.configure_state_repository(None)
    monkeypatch.setattr(database, "DATA_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(database, "STATE_FILENAME", "dashboard.json", raising=False)

    with pytest.raises(RuntimeError, match="PostgreSQL"):
        database.load_data()

    assert not (tmp_path / "dashboard.json").exists()
    assert not (tmp_path / "dashboard.json.lock").exists()


def test_tracked_up_state_requires_postgres_without_json_fallback(monkeypatch, tmp_path):
    tracked_ups.configure_state_repository(None)
    tracked_path = tmp_path / "tracked_ups.json"
    monkeypatch.setattr(tracked_ups, "TRACKED_FILE", str(tracked_path), raising=False)

    with pytest.raises(RuntimeError, match="PostgreSQL"):
        tracked_ups.load_tracked_list()

    assert not tracked_path.exists()


def test_dashboard_cache_persistence_requires_postgres(monkeypatch, tmp_path):
    database.configure_state_repository(None)
    cache._data_cache = None
    monkeypatch.setattr(database, "DATA_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(database, "STATE_FILENAME", "dashboard.json", raising=False)

    with pytest.raises(RuntimeError, match="PostgreSQL"):
        cache.persist_data({"hot_videos": [{"bvid": "BV1"}]})

    assert not (tmp_path / "dashboard.json").exists()
    assert not (tmp_path / "dashboard.json.lock").exists()


def test_test_runtime_configures_all_storage_adapters_to_postgresql(postgres_runtime):
    assert auth_store._auth_repository is postgres_runtime.auth
    assert database._state_repository is postgres_runtime.state
    assert tracked_ups._state_repository is postgres_runtime.state
