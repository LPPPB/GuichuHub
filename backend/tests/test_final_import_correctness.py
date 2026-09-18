"""Regression fixtures for complete, repeatable legacy conversion."""

import json
import sqlite3

import pytest
from sqlalchemy import create_engine, event, select, text

from tests.test_sqlite_snapshot_import import snapshot_paths, empty_import_target, _import, _target_trigger
from storage.repositories.business import BusinessRepository
from storage.repositories.state import StateRepository


def test_observations_persist_every_metric_on_insert_and_conflict(postgres_url):
    repository = BusinessRepository.from_url(postgres_url)
    repository.record_video({"bvid": "metrics", "first_seen": 1})
    values = {"views": None, "likes": 0, "coins": 3, "favorites": 4, "shares": 5,
              "comments": 6, "danmaku": 7, "online_count": 0, "online_precision": "exact", "potential_score": 1.5}
    for metrics in (values, {key: None if value == 0 else 0 if isinstance(value, (int, float)) else value
                            for key, value in values.items()}):
        repository.record_observation("metrics", 1, metrics)
        with repository._sessions() as session:
            row = session.execute(text("SELECT * FROM app.video_observations WHERE bvid='metrics'")).mappings().one()
        assert {key: row[key] for key in metrics} == metrics


def test_favorite_legacy_timestamp_and_new_favorite_keep_display_contract(postgres_url, snapshot_paths, tmp_path):
    dashboard = json.loads(snapshot_paths[2].read_text(encoding="utf-8"))
    dashboard["dashboard"]["favorites"][0]["saved_at"] = "2026-09-15 08:30:00"
    snapshot_paths[2].write_text(json.dumps(dashboard), encoding="utf-8")
    assert _import(postgres_url, snapshot_paths, tmp_path / "report.json")["valid"]
    repository = StateRepository.from_url(postgres_url)
    assert repository.get_favorites("7")[0]["saved_at"] == "2026-09-15 08:30:00"
    assert repository.add_favorite("video", {}, "7", 0)["saved_at"] == "1970-01-01 08:00:00"


def test_up_legacy_keys_and_rejection_reason_reach_public_readers(postgres_url, snapshot_paths, tmp_path):
    from storage import db, up_obs_reader
    document = json.loads(snapshot_paths[3].read_text(encoding="utf-8"))
    request = document["requests"]["pending"].pop()
    request.update(status="rejected", reject_reason="reviewed fixture", reviewed_at=104)
    document["requests"]["processed"].append(request)
    snapshot_paths[3].write_text(json.dumps(document), encoding="utf-8")
    assert _import(postgres_url, snapshot_paths, tmp_path / "report.json")["valid"]
    repository = BusinessRepository.from_url(postgres_url)
    db.configure_business_repository(repository)
    try:
        assert up_obs_reader.get_up_details(101) == [{
            "mid": 7, "name": "fixture up", "face": "face", "sign": "hello", "follower_count": 5,
            "following_count": 11, "latest_videos": [{"bvid": "BV1fixture"}], "kichu_video_count": 1,
            "total_recent_views": 3, "latest_pub_date": 4, "avg_views": 9, "video_count": 10, "recent_video_count": 2,
        }]
        assert up_obs_reader.get_summary(101, now=105)["kichu_video_count"] == 12
    finally:
        db.configure_business_repository(None)
    assert StateRepository.from_url(postgres_url).tracking_requests_for("visitor")[0]["reject_reason"] == "reviewed fixture"


def test_crawl_sequence_advances_after_explicit_import(postgres_url, snapshot_paths, tmp_path):
    with sqlite3.connect(snapshot_paths[0]) as connection:
        connection.executescript("CREATE TABLE crawl_runs(id INTEGER PRIMARY KEY, started_at INTEGER, status TEXT, stats_json TEXT); INSERT INTO crawl_runs VALUES(1,100,'success','{}');")
    assert _import(postgres_url, snapshot_paths, tmp_path / "report.json")["valid"]
    repository = BusinessRepository.from_url(postgres_url)
    assert repository.begin_crawl_run("fixture", 200) > 1


def test_snapshot_import_bounds_more_than_65535_bind_parameters(postgres_url, snapshot_paths, tmp_path):
    with sqlite3.connect(snapshot_paths[0]) as connection:
        connection.executemany("INSERT INTO video_obs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", [
            ("BV1fixture", 1000 + index, None, 0, 2, 3, 4, 5, 6, 0, 1.5, "exact") for index in range(6000)
        ])
    assert _import(postgres_url, snapshot_paths, tmp_path / "report.json")["entities"]["video_observations"]["target_count"] == 6001


def test_same_source_reviewed_retry_is_idempotent(postgres_url, snapshot_paths, tmp_path):
    from scripts.import_sqlite_snapshot import import_snapshot
    assert _import(postgres_url, snapshot_paths, tmp_path / "first.json")["valid"]
    report = import_snapshot(business_sqlite=snapshot_paths[0], auth_sqlite=snapshot_paths[1],
        dashboard_json=snapshot_paths[2], tracked_ups_json=snapshot_paths[3], database_url=postgres_url,
        report_path=tmp_path / "retry.json", allow_nonempty=True)
    assert report["valid"]
    with create_engine(postgres_url).connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM app.data_import_records")).scalar_one() == 1


@pytest.fixture
def complete_snapshot(snapshot_paths):
    with sqlite3.connect(snapshot_paths[0]) as connection:
        connection.executescript('''
CREATE TABLE video_tags(bvid TEXT, tag TEXT, ts INTEGER);
INSERT INTO video_tags VALUES('BV1fixture','tag',101);
CREATE TABLE word_obs(word TEXT, ts INTEGER, scope TEXT, count INTEGER);
INSERT INTO word_obs VALUES('word',101,'danmaku',3);
CREATE TABLE crawl_runs(id INTEGER, started_at INTEGER, status TEXT, stats_json TEXT);
INSERT INTO crawl_runs VALUES(10,101,'success','{"videos":1}');
CREATE TABLE up_staff_map(bvid TEXT, mid INTEGER, position INTEGER);
INSERT INTO up_staff_map VALUES('BV1fixture',7,1);
CREATE TABLE video_obs_snapshot(ts INTEGER, field TEXT, payload_json TEXT, item_count INTEGER);
INSERT INTO video_obs_snapshot VALUES(101,'hot_videos','[{"bvid":"BV1fixture"}]',1);
CREATE TABLE up_card_cache(mid INTEGER, payload_json TEXT, fetched_at INTEGER);
INSERT INTO up_card_cache VALUES(7,'{"name":"fixture"}',101);
CREATE TABLE calendar_videos(bvid TEXT, mid INTEGER, pub_date INTEGER, pub_date_str TEXT, views INTEGER, title TEXT);
INSERT INTO calendar_videos VALUES('BV1fixture',7,100,'01-01',3,'fixture');
CREATE TABLE calendar_video_authors(bvid TEXT, mid INTEGER);
INSERT INTO calendar_video_authors VALUES('BV1fixture',7);
CREATE TABLE calendar_backfill_jobs(id TEXT, mode TEXT, status TEXT, created_at INTEGER, updated_at INTEGER);
INSERT INTO calendar_backfill_jobs VALUES('job','year','completed',100,101);
CREATE TABLE calendar_backfill_job_items(job_id TEXT, mid INTEGER, status TEXT);
INSERT INTO calendar_backfill_job_items VALUES('job',7,'success');
''')
    return snapshot_paths


@pytest.mark.parametrize("table", ["video_tags", "word_observations", "crawl_runs", "up_staff_memberships",
    "video_snapshot_documents", "up_card_cache", "calendar_videos", "calendar_video_authors",
    "calendar_backfill_job_items", "tracked_up_settings"])
def test_reconciliation_detects_loss_in_every_imported_entity(postgres_url, complete_snapshot, tmp_path, table):
    with _target_trigger(postgres_url, "fixture_drop", table, "RETURN NULL;"):
        report = _import(postgres_url, complete_snapshot, tmp_path / "report.json")
    assert not report["valid"], f"lost {table} was silently accepted"
    assert report["entities"][table]["target_count"] == 0


def test_reconciliation_checks_calendar_job_payload(postgres_url, complete_snapshot, tmp_path):
    with _target_trigger(postgres_url, "fixture_change", "calendar_backfill_jobs", "NEW.payload := '{}'::jsonb; RETURN NEW;"):
        report = _import(postgres_url, complete_snapshot, tmp_path / "report.json")
    assert not report["valid"]


def test_reconciliation_accounts_for_synthesized_parents(postgres_url, snapshot_paths, tmp_path):
    with sqlite3.connect(snapshot_paths[0]) as connection:
        connection.execute("DELETE FROM videos")
        connection.execute("DELETE FROM ups")
    report = _import(postgres_url, snapshot_paths, tmp_path / "report.json")
    assert report["valid"]
    assert report["entities"]["videos"]["synthesized_count"] == 1
    assert report["entities"]["ups"]["synthesized_count"] == 1


@pytest.mark.parametrize("table,column,value", [("up_obs", "latest_videos_json", "{broken"),
    ("bili_sessions", "cookies", "{broken"), ("up_obs", "latest_videos_json", "{}"), ("bili_sessions", "cookies", "[]")])
def test_malformed_embedded_json_cannot_report_valid(postgres_url, snapshot_paths, tmp_path, table, column, value):
    from scripts.import_sqlite_snapshot import ImportSafetyError
    source = snapshot_paths[1] if table == "bili_sessions" else snapshot_paths[0]
    with sqlite3.connect(source) as connection:
        connection.execute(f"UPDATE {table} SET {column}=?", (value,))
    report_path = tmp_path / "report.json"
    with pytest.raises(ImportSafetyError, match="embedded JSON"):
        _import(postgres_url, snapshot_paths, report_path)
    assert json.loads(report_path.read_text())["valid"] is False
