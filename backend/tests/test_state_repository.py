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
        try:
            from storage import tracked_ups
            tracked_ups.configure_state_repository(None)
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


def test_approving_tracking_request_adds_one_tracked_up_atomically(state_repository):
    request_id = state_repository.create_tracking_request(
        99, "visitor", {"name": "UP99"}, "reason", now=100,
    )

    assert state_repository.review_tracking_request(request_id, "approve", now=101) == {
        "added_to_pool": True,
    }
    assert state_repository.tracked_mids() == [99]


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


def test_legacy_tracked_up_store_uses_configured_postgresql_repository(state_repository):
    from storage import tracked_ups

    tracked_ups.configure_state_repository(state_repository)
    tracked_ups.save_tracked_list([{"mid": 701, "name": "UP701", "enabled": True}], updated_at=100)

    assert state_repository.tracked_mids() == [701]
    assert tracked_ups.load_tracked_list()["ups"] == [{"mid": 701, "name": "UP701", "enabled": True}]


def test_legacy_tracked_up_config_uses_configured_postgresql_repository(state_repository):
    from storage import tracked_ups

    tracked_ups.configure_state_repository(state_repository)
    tracked_ups.save_config({"refresh_hours": 6})

    assert state_repository.load_tracked_list()["config"] == {"refresh_hours": 6}
    assert tracked_ups.load_config() == {"refresh_hours": 6}


def test_legacy_tracking_request_approval_uses_postgresql_repository(state_repository):
    from storage import tracked_ups

    tracked_ups.configure_state_repository(state_repository)
    request, error = tracked_ups.add_up_request(801, {"name": "UP801"}, "reason", "visitor-801")
    assert error is None

    result, error = tracked_ups.review_up_request(request["id"], "approve")

    assert error is None
    assert result["added_to_pool"] is True
    assert 801 in state_repository.tracked_mids()


def test_legacy_tracking_request_rejection_uses_postgresql_repository(state_repository):
    from storage import tracked_ups

    tracked_ups.configure_state_repository(state_repository)
    request, error = tracked_ups.add_up_request(802, {"name": "UP802"}, "reason", "visitor-802")
    assert error is None

    result, error = tracked_ups.review_up_request(request["id"], "reject", "not suitable")

    assert error is None
    assert result["added_to_pool"] is False
    assert 802 not in state_repository.tracked_mids()


def test_legacy_tracking_request_withdrawal_uses_postgresql_repository(state_repository):
    from storage import tracked_ups

    tracked_ups.configure_state_repository(state_repository)
    request, error = tracked_ups.add_up_request(803, {"name": "UP803"}, "reason", "visitor-803")
    assert error is None

    assert tracked_ups.withdraw_up_request(request["id"], "visitor-803") is None
    assert tracked_ups.withdraw_up_request(request["id"], "visitor-803") == "NOT_FOUND"
    assert 803 not in state_repository.tracked_mids()


def test_tracking_request_lists_use_postgresql_repository(state_repository):
    from storage import tracked_ups

    tracked_ups.configure_state_repository(state_repository)
    mine, error = tracked_ups.add_up_request(804, {"name": "UP804"}, "reason", "visitor-804")
    other, error = tracked_ups.add_up_request(805, {"name": "UP805"}, "reason", "visitor-805")
    assert error is None

    assert [item["id"] for item in tracked_ups.get_my_up_requests("visitor-804")["pending"]] == [mine["id"]]
    assert {item["id"] for item in tracked_ups.list_all_up_requests()["pending"]} >= {mine["id"], other["id"]}


def test_tracking_request_duplicate_mid_is_rejected_in_postgresql(state_repository):
    from storage import tracked_ups

    tracked_ups.configure_state_repository(state_repository)
    request, error = tracked_ups.add_up_request(806, {"name": "UP806"}, "reason", "visitor-a")
    assert error is None

    duplicate, error = tracked_ups.add_up_request(806, {"name": "UP806"}, "reason", "visitor-b")

    assert duplicate is None
    assert error == "DUPLICATE"
