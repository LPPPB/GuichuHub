"""PostgreSQL dashboard state and favorites repository contracts."""

import subprocess
import time

import pytest
from sqlalchemy import create_engine, text

from storage.migrations import upgrade_database
from storage.repositories.state import StateRepository


@pytest.fixture(scope="module")
def state_repository():
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
        yield StateRepository.from_url(url)
    finally:
        try:
            from storage import database
            database.configure_state_repository(None)
        except ImportError:
            pass
        subprocess.run(["docker", "stop", container_id], check=False)


def test_dashboard_state_upsert_replaces_one_current_snapshot(state_repository):
    state_repository.save_dashboard({"hot_videos": [{"bvid": "BV1"}]}, now=100)
    state_repository.save_dashboard({"hot_videos": [{"bvid": "BV2"}]}, now=101)

    assert state_repository.load_dashboard() == {"hot_videos": [{"bvid": "BV2"}]}


def test_dashboard_state_mutation_locks_and_updates_current_snapshot(state_repository):
    state_repository.save_dashboard({"counter": 1}, now=100)

    result = state_repository.update_dashboard(
        lambda payload: payload.update(counter=payload["counter"] + 1), now=101,
    )

    assert result == {"counter": 2}
    assert state_repository.load_dashboard() == {"counter": 2}


def test_favorites_are_owner_scoped_and_mutable(state_repository):
    favorite = state_repository.add_favorite("video", {"bvid": "BV1"}, "1", now=100)

    assert state_repository.get_favorites(owner="1") == [favorite]
    assert state_repository.get_favorites(owner="2") == []
    assert state_repository.update_favorite(favorite["id"], ["梗"], "note", "1")["notes"] == "note"
    assert state_repository.remove_favorite(favorite["id"], "1") is True


def test_legacy_state_store_uses_configured_postgresql_repository(state_repository):
    from storage import database

    database.configure_state_repository(state_repository)
    database.save_data({"hot_videos": [{"bvid": "BV9"}], "favorites": []})
    favorite = database.add_favorite("video", {"bvid": "BV9"}, owner="9")

    assert state_repository.load_dashboard()["hot_videos"] == [{"bvid": "BV9"}]
    assert state_repository.get_favorites(owner="9") == [favorite]
    assert database.get_favorites(owner="9") == [favorite]
    assert database.update_favorite(favorite["id"], tags=["梗"], notes="note", owner="9")["notes"] == "note"
    assert database.remove_favorite(favorite["id"], owner="9") is True
