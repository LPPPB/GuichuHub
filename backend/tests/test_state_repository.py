"""PostgreSQL dashboard state and favorites repository contracts."""

import pytest

from storage.migrations import upgrade_database
from storage.repositories.state import StateRepository


@pytest.fixture
def state_repository(clean_postgres_data, postgres_url):
    upgrade_database(postgres_url)
    repository = StateRepository.from_url(postgres_url)
    try:
        yield repository
    finally:
        from storage import database, tracked_ups
        database.configure_state_repository(None)
        tracked_ups.configure_state_repository(None)
        repository._sessions.kw["bind"].dispose()


@pytest.fixture(autouse=True)
def isolate_state_tables(state_repository, monkeypatch):
    from storage import cache
    from storage.models import (
        dashboard_state, favorites, tracked_up_settings, tracked_ups,
        tracking_requests, worker_heartbeats,
    )

    with state_repository._sessions.begin() as session:
        for table in (
            tracking_requests, tracked_ups, tracked_up_settings,
            favorites, dashboard_state, worker_heartbeats,
        ):
            session.execute(table.delete())
    monkeypatch.setattr(cache, "_data_cache", None)
    monkeypatch.setattr(cache, "_data_cache_version", None, raising=False)


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


def test_dashboard_cache_refreshes_after_postgresql_state_change(state_repository, monkeypatch):
    from storage import cache, database

    database.configure_state_repository(state_repository)
    monkeypatch.setattr(cache, "_data_cache", None)
    monkeypatch.setattr(cache, "_data_cache_version", None, raising=False)
    first = {"hot_videos": [{"bvid": "BV1"}]}
    second = {"hot_videos": [{"bvid": "BV2"}]}
    state_repository.save_dashboard(first, now=100)

    assert cache.get_data() == first

    state_repository.save_dashboard(second, now=101)

    assert cache.get_data() == second


def test_favorites_are_owner_scoped_and_mutable(state_repository):
    favorite = state_repository.add_favorite("video", {"bvid": "BV1"}, "1", now=100)

    assert state_repository.get_favorites(owner="1") == [favorite]
    assert state_repository.get_favorites(owner="2") == []
    assert state_repository.update_favorite(favorite["id"], ["梗"], "note", "1")["notes"] == "note"
    assert state_repository.remove_favorite(favorite["id"], "1") is True


def test_legacy_favorites_are_claimed_in_postgresql(state_repository):
    from storage import database

    database.configure_state_repository(state_repository)
    unowned = state_repository.add_favorite("video", {"bvid": "BV1"}, None, now=100)
    admin_owned = state_repository.add_favorite("video", {"bvid": "BV2"}, "admin", now=101)
    other_owner = state_repository.add_favorite("video", {"bvid": "BV3"}, "7", now=102)

    assert database.migrate_legacy_favorites(42) == 2
    assert {item["id"] for item in state_repository.get_favorites(owner="42")} == {
        unowned["id"], admin_owned["id"],
    }
    assert state_repository.get_favorites(owner="7") == [other_owner]


def test_approving_tracking_request_adds_one_tracked_up_atomically(state_repository):
    request_id = state_repository.create_tracking_request(
        99, "visitor", {"name": "UP99"}, "reason", now=100,
    )

    result = state_repository.review_tracking_request(request_id, "approve", now=101)
    assert result["added_to_pool"] is True
    assert result["request"]["id"] == request_id
    assert result["request"]["status"] == "approved"
    assert result["pool_up"]["mid"] == 99
    assert state_repository.tracked_mids() == [99]


def test_tracking_request_advisory_lock_supports_bigint_up_ids(state_repository):
    mid = 5_000_000_000
    request_id = state_repository.create_tracking_request(
        mid, "bigint-visitor", {"name": "large id"}, "reason", now=100,
    )

    state_repository.review_tracking_request(request_id, "approve", now=101)

    assert state_repository.tracked_mids() == [mid]


def test_tracking_request_rejection_preserves_reason_in_postgresql(state_repository):
    from storage import tracked_ups

    tracked_ups.configure_state_repository(state_repository)
    request, error = tracked_ups.add_up_request(9981, {"name": "UP"}, "review", "visitor")
    assert error is None

    result, error = tracked_ups.review_up_request(request["id"], "reject", "out of scope")

    assert error is None
    assert result["request"]["status"] == "rejected"
    assert result["request"]["reject_reason"] == "out of scope"
    assert result["added_to_pool"] is False


def test_tracked_up_removal_request_updates_postgresql_pool(state_repository):
    from storage import tracked_ups

    tracked_ups.configure_state_repository(state_repository)
    tracked_ups.save_tracked_list([{"mid": 9982, "name": "UP", "enabled": True}], updated_at=100)

    request, error = tracked_ups.add_up_request(
        9982, {"name": "UP"}, "stop tracking", "visitor", request_type="remove",
    )

    assert error is None
    assert {row["id"]: row["status"] for row in state_repository.tracking_requests_for()}[request["id"]] == "pending"
    result, error = tracked_ups.review_up_request(request["id"], "approve")
    assert error is None
    assert result["request"]["status"] == "approved"
    assert result["removed_from_pool"] is True
    assert result["added_to_pool"] is False
    assert state_repository.load_tracked_list()["ups"][0]["enabled"] is False


def test_tracking_request_validation_matches_existing_api_contract(state_repository):
    from storage import tracked_ups

    tracked_ups.configure_state_repository(state_repository)
    tracked_ups.save_tracked_list([{"mid": 9983, "name": "UP", "enabled": True}], updated_at=100)

    assert tracked_ups.add_up_request(9983, {}, "", "visitor")[1] == "ALREADY_TRACKED"
    assert tracked_ups.add_up_request(9983, {}, "", "visitor", "remove")[1] == "REASON_REQUIRED"
    assert tracked_ups.add_up_request(9984, {}, "", "visitor", "remove")[1] == "NOT_TRACKED"
    assert tracked_ups.add_up_request(9984, {}, "stop", "visitor", "remove")[1] == "NOT_TRACKED"
    assert tracked_ups.add_up_request(9985, {}, "", "visitor", "invalid")[1] == "INVALID_TYPE"


def test_tracking_request_pool_daily_and_pending_limits_are_enforced(state_repository, monkeypatch):
    from storage import tracked_ups

    tracked_ups.configure_state_repository(state_repository)
    now = 1_800_000_000
    monkeypatch.setattr(tracked_ups.time, "time", lambda: now)
    tracked_ups.save_tracked_list(
        [{"mid": 20000 + index, "enabled": True} for index in range(tracked_ups.TRACK_POOL_LIMIT)],
        updated_at=now,
    )
    assert tracked_ups.add_up_request(21000, {}, "", "pool-check")[1] == "POOL_FULL"

    tracked_ups.save_tracked_list([], updated_at=now)
    for mid in (22001, 22002, 22003):
        assert tracked_ups.add_up_request(mid, {}, "", "daily-check")[1] is None
    assert tracked_ups.add_up_request(22004, {}, "", "daily-check")[1] == "DAILY_LIMIT"

    tracked_ups.save_tracked_list([], updated_at=now)
    from storage.models import tracking_requests
    with state_repository._sessions.begin() as session:
        session.execute(tracking_requests.delete())
    for index in range(tracked_ups.REQUESTS_PENDING_LIMIT):
        request, error = tracked_ups.add_up_request(23000 + index, {}, "", f"queue-{index}")
        assert error is None, request
    assert tracked_ups.add_up_request(24000, {}, "", "queue-last")[1] == "QUEUE_FULL"


def test_approving_request_reenables_a_disabled_tracked_up(state_repository):
    from storage import tracked_ups

    tracked_ups.configure_state_repository(state_repository)
    tracked_ups.save_tracked_list([{"mid": 9986, "name": "UP", "enabled": False}], updated_at=100)
    request, error = tracked_ups.add_up_request(9986, {"name": "UP"}, "", "visitor")
    assert error is None
    assert {row["id"]: row["status"] for row in state_repository.tracking_requests_for()}[request["id"]] == "pending"

    result, error = tracked_ups.review_up_request(request["id"], "approve")

    assert error is None
    assert result["added_to_pool"] is True
    assert result["pool_up"]["enabled"] is True
    assert state_repository.load_tracked_list()["ups"][0]["enabled"] is True


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


def test_has_tracked_list_uses_postgres_without_legacy_files(state_repository, monkeypatch):
    from storage import tracked_ups

    tracked_ups.configure_state_repository(state_repository)
    state_repository.save_tracked_list([{"mid": 702, "name": "UP702", "enabled": True}], 100, {})
    assert tracked_ups.has_tracked_list() is True


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


def test_worker_heartbeat_upserts_postgresql_timestamp(state_repository):
    state_repository.record_worker_heartbeat("worker-1", 100, {"kind": "scheduler"})
    state_repository.record_worker_heartbeat("worker-1", 130, {"kind": "scheduler"})

    assert state_repository.worker_heartbeat("worker-1") == 130
