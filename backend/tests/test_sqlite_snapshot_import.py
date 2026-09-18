"""Offline SQLite/JSON snapshot import integration contracts."""

from contextlib import contextmanager
import json
import sqlite3

import pytest
from sqlalchemy import create_engine, text

from storage.migrations import upgrade_database


@contextmanager
def _target_trigger(postgres_url, name, table, body):
    """Install a test-only trigger that simulates a target-side mismatch."""
    engine = create_engine(postgres_url)
    with engine.begin() as connection:
        connection.execute(text(
            f"CREATE FUNCTION app.{name}() RETURNS trigger LANGUAGE plpgsql "
            f"AS $$ BEGIN {body} END; $$"
        ))
        connection.execute(text(
            f"CREATE TRIGGER {name} BEFORE INSERT ON app.{table} "
            f"FOR EACH ROW EXECUTE FUNCTION app.{name}()"
        ))
    try:
        yield
    finally:
        with engine.begin() as connection:
            connection.execute(text(f"DROP TRIGGER IF EXISTS {name} ON app.{table}"))
            connection.execute(text(f"DROP FUNCTION IF EXISTS app.{name}()"))
        engine.dispose()


def _import(postgres_url, snapshot_paths, report_path):
    from scripts.import_sqlite_snapshot import import_snapshot

    return import_snapshot(
        business_sqlite=snapshot_paths[0], auth_sqlite=snapshot_paths[1],
        dashboard_json=snapshot_paths[2], tracked_ups_json=snapshot_paths[3],
        database_url=postgres_url, report_path=report_path,
    )


@pytest.fixture
def snapshot_paths(tmp_path):
    business = tmp_path / "business.sqlite"
    with sqlite3.connect(business) as connection:
        connection.executescript("""
            CREATE TABLE videos (bvid TEXT PRIMARY KEY, mid INTEGER, title TEXT, tid INTEGER,
                tname TEXT, pub_date INTEGER, duration INTEGER, first_seen INTEGER, source TEXT,
                observe_tier TEXT, pic TEXT);
            CREATE TABLE ups (mid INTEGER PRIMARY KEY, name TEXT, face TEXT, tracked INTEGER);
            CREATE TABLE video_obs (bvid TEXT, ts INTEGER, views INTEGER, likes INTEGER,
                coins INTEGER, favorites INTEGER, shares INTEGER, comments INTEGER, danmaku INTEGER,
                online_count INTEGER, potential_score REAL, online_precision TEXT,
                PRIMARY KEY (bvid, ts));
            CREATE TABLE up_obs (mid INTEGER, ts INTEGER, kichu_count INTEGER, video_count_30d INTEGER,
                views_30d INTEGER, latest_pub_ts INTEGER, follower_count INTEGER, activity_score REAL,
                activity_rank INTEGER, play_rank INTEGER, avg_views INTEGER, video_count_total INTEGER,
                sign TEXT, following_count INTEGER, latest_videos_json TEXT, kichu_count_30d INTEGER,
                PRIMARY KEY (mid, ts));
        """)
        connection.execute("INSERT INTO videos VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
            "BV1fixture", 7, "fixture video", 119, "鬼畜", 100, 60, 90, "fixture", "hot", None,
        ))
        connection.execute("INSERT INTO ups VALUES (?,?,?,?)", (7, "fixture up", "face", 1))
        connection.execute("INSERT INTO video_obs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
            "BV1fixture", 101, None, 0, 2, 3, 4, 5, 6, 0, 1.5, "exact",
        ))
        connection.execute("INSERT INTO up_obs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            7, 101, 1, 2, 3, 4, 5, 6.5, 7, 8, 9, 10, "hello", 11, '[{"bvid":"BV1fixture"}]', 12,
        ))

    auth = tmp_path / "auth.sqlite"
    with sqlite3.connect(auth) as connection:
        connection.executescript("""
            CREATE TABLE admin_accounts (mid INTEGER PRIMARY KEY, name TEXT, face TEXT,
                added_at INTEGER, added_by TEXT);
            CREATE TABLE bili_sessions (token TEXT PRIMARY KEY, visitor_id TEXT, mid INTEGER,
                name TEXT, face TEXT, cookies TEXT, created_at INTEGER, expires_at INTEGER);
            CREATE TABLE collector_credential_handoffs (id INTEGER PRIMARY KEY, action TEXT,
                payload TEXT, requested_by TEXT, requested_at INTEGER);
        """)
        connection.execute("INSERT INTO admin_accounts VALUES (?,?,?,?,?)", (7, "fixture up", "face", 99, "seed"))
        connection.execute("INSERT INTO bili_sessions VALUES (?,?,?,?,?,?,?,?)", (
            "session-token", "visitor", 7, "fixture up", "face", '{"SESSDATA":"kept-server-side"}', 99, 999,
        ))
        connection.execute("INSERT INTO collector_credential_handoffs VALUES (?,?,?,?,?)", (
            1, "replace", '{"SESSDATA":"handoff"}', "7", 100,
        ))

    dashboard = tmp_path / "dashboard.json"
    dashboard.write_text(json.dumps({
        "dashboard": {"hot_videos": ["BV1fixture"], "favorites": [{
            "id": "video_fixture", "type": "video", "owner": "7", "tags": ["fixture"],
            "notes": "kept", "saved_at": 101, "bvid": "BV1fixture",
        }]},
        "runtime_settings": {
            "danmaku_filters": {"allowed_exact": ["666"], "bad_exact": ["广告"], "bad_substr": ["推广"]},
            "meme_stopwords": {"自定义": ["泛词"]},
            "meme_seed_words": ["哈基米"],
            "tag_filters": {"categories": {"自定义": ["泛词"]}, "ad_keywords": ["品牌"],
                            "activity_keywords": ["企划"], "allowed_two_char": ["叮咚"]},
        },
    }), encoding="utf-8")
    tracked = tmp_path / "tracked.json"
    tracked.write_text(json.dumps({
        "ups": [{"mid": 7, "name": "fixture up", "enabled": True}],
        "config": {"mode": "fixture"}, "updated_at": 102,
        "requests": {"pending": [{"id": "req_fixture", "mid": 8, "visitor_id": "visitor",
            "request_type": "add", "up": {"mid": 8}, "reason": "please", "submitted_at": 103,
            "status": "pending"}], "processed": []},
    }), encoding="utf-8")
    return business, auth, dashboard, tracked


@pytest.fixture(autouse=True)
def empty_import_target(clean_postgres_data):
    """Each import test starts from a clean application dataset."""


def test_importer_reconciles_explicit_sqlite_and_json_snapshots(postgres_url, snapshot_paths, tmp_path):
    """Import keeps NULL/0, relation keys, auth state, and mutable JSON state."""
    from scripts.import_sqlite_snapshot import import_snapshot

    upgrade_database(postgres_url)
    report_path = tmp_path / "reconciliation.json"
    report = import_snapshot(
        business_sqlite=snapshot_paths[0], auth_sqlite=snapshot_paths[1],
        dashboard_json=snapshot_paths[2], tracked_ups_json=snapshot_paths[3],
        database_url=postgres_url, report_path=report_path,
    )

    assert report["valid"] is True
    for entity in report["entities"].values():
        assert entity["source_count"] == entity["target_count"]
        assert entity["keys_match"] is True
    for name in ("sessions", "credential_handoffs", "favorites", "tracked_ups", "tracking_requests"):
        assert report[name]["source_count"] == report[name]["target_count"]
        assert report[name]["keys_match"] is True
    assert report["latest_observation_ts"] == {"source": 101, "target": 101}
    assert report["dashboard_state"]["matches"] is True
    assert report["runtime_settings"] == {
        "source_count": 4, "target_count": 4,
        "keys_match": True, "payloads_match": True, "matches": True,
    }
    assert json.loads(report_path.read_text(encoding="utf-8"))["valid"] is True

    engine = create_engine(postgres_url)
    with engine.connect() as connection:
        row = connection.execute(text("SELECT views, likes FROM app.video_observations")).one()
        assert tuple(row) == (None, 0)
        assert connection.execute(text("SELECT count(*) FROM auth.browser_sessions")).scalar_one() == 1
        assert connection.execute(text(
            "SELECT payload FROM app.dashboard_state WHERE name = 'meme_seed_words'"
        )).scalar_one() == ["哈基米"]


def test_importer_refuses_nonempty_target_without_explicit_override(postgres_url, snapshot_paths, tmp_path):
    from scripts.import_sqlite_snapshot import ImportSafetyError, import_snapshot

    upgrade_database(postgres_url)
    args = dict(
        business_sqlite=snapshot_paths[0], auth_sqlite=snapshot_paths[1],
        dashboard_json=snapshot_paths[2], tracked_ups_json=snapshot_paths[3],
        database_url=postgres_url, report_path=tmp_path / "report.json",
    )
    import_snapshot(**args)

    with pytest.raises(ImportSafetyError, match="nonempty"):
        import_snapshot(**args)


def test_importer_invalid_when_up_key_set_differs(postgres_url, snapshot_paths, tmp_path):
    """Changing one target UP key must invalidate reconciliation even when counts match."""
    with sqlite3.connect(snapshot_paths[0]) as connection:
        connection.execute("INSERT INTO ups VALUES (?,?,?,?)", (8, "second up", "face", 0))
    with _target_trigger(
        postgres_url, "test_rewrite_up_key", "ups",
        "IF NEW.mid = 8 THEN NEW.mid := 9; END IF; RETURN NEW;",
    ):
        report = _import(postgres_url, snapshot_paths, tmp_path / "up-keys.json")

    assert report["entities"]["ups"]["source_count"] == 2
    assert report["entities"]["ups"]["target_count"] == 2
    assert report["entities"]["ups"]["keys_match"] is False
    assert report["valid"] is False


def test_importer_invalid_when_up_observation_count_differs(postgres_url, snapshot_paths, tmp_path):
    """A target dropping UP observations must invalidate reconciliation."""
    with _target_trigger(
        postgres_url, "test_drop_up_observation", "up_observations", "RETURN NULL;",
    ):
        report = _import(postgres_url, snapshot_paths, tmp_path / "up-observations.json")

    assert report["entities"]["up_observations"]["source_count"] == 1
    assert report["entities"]["up_observations"]["target_count"] == 0
    assert report["entities"]["up_observations"]["keys_match"] is False
    assert report["valid"] is False


def test_importer_invalid_when_tracking_request_count_differs(postgres_url, snapshot_paths, tmp_path):
    """A target dropping tracking requests must invalidate reconciliation."""
    with _target_trigger(
        postgres_url, "test_drop_tracking_request", "tracking_requests", "RETURN NULL;",
    ):
        report = _import(postgres_url, snapshot_paths, tmp_path / "tracking-requests.json")

    assert report["tracking_requests"]["source_count"] == 1
    assert report["tracking_requests"]["target_count"] == 0
    assert report["tracking_requests"]["keys_match"] is False
    assert report["valid"] is False


def test_importer_invalid_when_runtime_setting_payload_differs(postgres_url, snapshot_paths, tmp_path):
    """A target-side setting mutation must fail payload reconciliation."""
    with _target_trigger(
        postgres_url, "test_mutate_runtime_setting", "dashboard_state",
        "IF NEW.name = 'tag_filters' THEN NEW.payload := '{}'::jsonb; END IF; RETURN NEW;",
    ):
        report = _import(postgres_url, snapshot_paths, tmp_path / "runtime-settings.json")

    assert report["dashboard_state"]["matches"] is True
    assert report["runtime_settings"]["keys_match"] is True
    assert report["runtime_settings"]["payloads_match"] is False
    assert report["valid"] is False
