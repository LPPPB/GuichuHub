"""PostgreSQL business repository contracts."""

import subprocess
import time

import pytest
from sqlalchemy import create_engine, text

from storage.migrations import upgrade_database
from storage.repositories.business import BusinessRepository
from storage import db as legacy_db


@pytest.fixture(scope="module")
def business_repository():
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
        yield BusinessRepository.from_url(url)
    finally:
        subprocess.run(["docker", "stop", container_id], check=False)


def test_observation_upsert_preserves_null_and_zero(business_repository):
    """Replacing NULL with zero, or making upsert append rows, must fail this contract."""
    business_repository.record_video({"bvid": "BV1", "first_seen": 100, "title": "test"})
    business_repository.record_observation("BV1", 100, {"views": None, "likes": 0})
    business_repository.record_observation("BV1", 100, {"views": None, "likes": 0})

    assert business_repository.video_trend("BV1", start_ts=0) == [
        {"ts": 100, "views": None, "likes": 0}
    ]


def test_two_workers_claim_distinct_calendar_items(business_repository):
    """Removing SKIP LOCKED or transactional status updates must fail this claim contract."""
    business_repository.enqueue_calendar_items("job-1", [101, 202])

    first = business_repository.claim_calendar_item("worker-a")
    second = business_repository.claim_calendar_item("worker-b")

    assert {first["mid"], second["mid"]} == {101, 202}
    assert {first["worker_id"], second["worker_id"]} == {"worker-a", "worker-b"}


def test_legacy_record_obs_adapter_persists_to_postgresql(business_repository):
    """Leaving the public adapter on SQLite must fail this compatibility contract."""
    legacy_db.configure_business_repository(business_repository)
    legacy_db.record_video({"bvid": "BV2", "first_seen": 200, "title": "adapter"}, 200, "test")
    legacy_db.record_obs("BV2", 200, {"views": 7, "likes": 0})

    assert business_repository.video_trend("BV2", start_ts=0) == [
        {"ts": 200, "views": 7, "likes": 0}
    ]


def test_legacy_words_and_crawl_run_adapters_persist_to_postgresql(business_repository):
    """Keeping these public write APIs on SQLite must fail this batch-persistence contract."""
    legacy_db.configure_business_repository(business_repository)
    run_id = legacy_db.begin_crawl_run("scheduled")
    legacy_db.record_words([{"word": "梗", "count": 3}], 300)
    legacy_db.finish_crawl_run(run_id, "success", {"videos": 1})

    assert business_repository.word_rows(300) == [{"word": "梗", "count": 3, "scope": "danmaku"}]
    assert business_repository.crawl_run(run_id) == {"status": "success", "stats": {"videos": 1}}


def test_legacy_video_snapshot_adapter_upserts_jsonb_document(business_repository):
    """Appending a second document for one timestamp/field must fail this snapshot contract."""
    legacy_db.configure_business_repository(business_repository)
    legacy_db.upsert_video_obs_snapshot(400, "hot_videos", [{"bvid": "BV3", "views": 1}])
    legacy_db.upsert_video_obs_snapshot(400, "hot_videos", [{"bvid": "BV3", "views": 2}])

    assert business_repository.snapshot_document(400, "hot_videos") == {
        "payload": [{"bvid": "BV3", "views": 2}], "item_count": 1
    }


def test_legacy_snapshot_batch_rejects_invalid_field_without_partial_write(business_repository):
    """Removing pre-validation must fail because the valid first document would be persisted."""
    legacy_db.configure_business_repository(business_repository)
    legacy_db.upsert_video_obs_snapshot_batch(499, {"hot_videos": [{"bvid": "BV4"}]})
    assert business_repository.snapshot_document(499, "hot_videos") == {
        "payload": [{"bvid": "BV4"}], "item_count": 1
    }

    with pytest.raises(ValueError, match="非法 field"):
        legacy_db.upsert_video_obs_snapshot_batch(500, {
            "hot_videos": [{"bvid": "BV4"}], "not_a_field": []
        })

    with pytest.raises(Exception):
        business_repository.snapshot_document(500, "hot_videos")
