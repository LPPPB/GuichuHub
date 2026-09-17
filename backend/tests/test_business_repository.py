"""PostgreSQL business repository contracts."""

import time

import pytest

from storage.migrations import upgrade_database
from storage.repositories.business import BusinessRepository
from storage import db as legacy_db


@pytest.fixture
def business_repository(clean_postgres_data, postgres_url):
    upgrade_database(postgres_url)
    repository = BusinessRepository.from_url(postgres_url)
    try:
        yield repository
    finally:
        legacy_db.configure_business_repository(None)
        repository._sessions.kw["bind"].dispose()


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


def test_calendar_job_queue_uses_postgres_row_locks(business_repository):
    job, created = business_repository.enqueue_calendar_job(
        "recent", [{"mid": 303, "name": "UP303"}], now=100, days=7,
    )

    assert created is True
    claimed = business_repository.claim_calendar_job("worker-a", now=101, lease_seconds=120)
    assert claimed["id"] == job["id"]
    assert claimed["items"] == [{
        "mid": 303, "name": "UP303", "status": "queued", "pages": 0,
        "videos": 0, "attempts": 0, "error_code": "", "error_message": "",
        "started_at": None, "finished_at": None,
    }]


def test_calendar_job_deduplicates_an_existing_live_request(business_repository):
    first, created = business_repository.enqueue_calendar_job(
        "recent", [{"mid": 304, "name": "UP304"}], now=100,
        days=7, dedupe_key="manual:recent:7", dedupe_window_seconds=60,
    )
    second, created_again = business_repository.enqueue_calendar_job(
        "recent", [{"mid": 304, "name": "UP304"}], now=110,
        days=7, dedupe_key="manual:recent:7", dedupe_window_seconds=60,
    )

    assert created is True
    assert created_again is False
    assert second["id"] == first["id"]


def test_calendar_job_progress_and_failure_counters_are_persisted(business_repository):
    job, _ = business_repository.enqueue_calendar_job(
        "recent", [{"mid": 305, "name": "UP305"}, {"mid": 306, "name": "UP306"}],
        now=200, days=7,
    )
    business_repository.update_calendar_job_item(
        job["id"], {"mid": 305, "status": "success", "pages": 2,
                    "videos": 5, "attempts": 1},
        worker_id="worker", now=201, lease_seconds=120,
    )
    business_repository.fail_calendar_job_items(
        job["id"], "cookie_expired", "Cookie unavailable", now=202,
    )

    result = business_repository.calendar_job(job["id"])
    assert result["processed_ups"] == 2
    assert result["succeeded_ups"] == 1
    assert result["failed_ups"] == 1
    assert result["total_videos"] == 5
    assert result["progress_percent"] == 100
    failed_item = next(item for item in result["items"] if item["mid"] == 306)
    assert failed_item["status"] == "failed"
    assert failed_item["error_code"] == "cookie_expired"
    assert failed_item["finished_at"] == 202


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


def test_legacy_up_observation_adapter_upserts_jsonb_batch(business_repository):
    """Appending duplicate UP observations for one batch must fail this compatibility contract."""
    legacy_db.configure_business_repository(business_repository)
    legacy_db.upsert_up_obs(600, [{"mid": 42, "name": "UP", "follower_count": 1}])
    legacy_db.upsert_up_obs(600, [{"mid": 42, "name": "UP", "follower_count": 2}])

    assert business_repository.up_observation(42, 600) == {
        "mid": 42, "payload": {"mid": 42, "name": "UP", "follower_count": 2}
    }


def test_legacy_calendar_adapter_upserts_postgresql_video(business_repository):
    """Appending calendar rows for the same video/author must fail this calendar contract."""
    legacy_db.configure_business_repository(business_repository)
    legacy_db.upsert_calendar_videos([{
        "bvid": "BV5", "mid": 88, "pub_date": 700, "pub_date_str": "09-15", "views": 1, "title": "calendar"
    }])
    legacy_db.upsert_calendar_videos([{
        "bvid": "BV5", "mid": 88, "pub_date": 700, "pub_date_str": "09-15", "views": 2, "title": "calendar"
    }])

    assert business_repository.calendar_video("BV5", 88) == {"views": 2, "pub_date_str": "01-01"}


def test_legacy_up_observation_adapter_keeps_rankings(business_repository):
    legacy_db.configure_business_repository(business_repository)
    legacy_db.upsert_up_obs(
        901,
        [{"mid": 91, "name": "UP", "total_recent_views": 8}],
        play_ranking=[{"mid": 91}],
        active_ranking=[{"mid": 91}],
    )

    assert business_repository.up_observation(91, 901)["payload"] == {
        "mid": 91,
        "name": "UP",
        "total_recent_views": 8,
        "play_rank": 1,
        "activity_rank": 1,
    }


def test_snapshot_reader_uses_configured_postgresql_repository(business_repository):
    legacy_db.configure_business_repository(business_repository)
    legacy_db.upsert_video_obs_snapshot_batch(902, {
        "timeline": [{"views": 3}], "pool_summary": {"total_views": 3},
    })

    from storage.video_snapshot_reader import get_video_snapshot_fields

    assert get_video_snapshot_fields(902) == {
        "timeline": [{"views": 3}], "pool_summary": {"total_views": 3},
    }


def test_snapshot_history_reader_uses_configured_postgresql_repository(business_repository):
    legacy_db.configure_business_repository(business_repository)
    legacy_db.upsert_video_obs_snapshot(1000, "timeline", [{"views": 1}])
    legacy_db.upsert_video_obs_snapshot(2000, "timeline", [{"views": 2}])

    from storage.video_snapshot_reader import get_timeline_history

    assert get_timeline_history(1000, 2000) == [
        {"created_at": 1000, "analysis": {"timeline": [{"views": 1}]}},
        {"created_at": 2000, "analysis": {"timeline": [{"views": 2}]}},
    ]


def test_up_observation_reader_uses_configured_postgresql_repository(business_repository):
    legacy_db.configure_business_repository(business_repository)
    legacy_db.upsert_up_obs(
        3000,
        [{
            "mid": 301, "name": "排行 UP", "face": "face", "total_recent_views": 9,
            "avg_views": 3, "video_count": 4, "follower_count": 5,
            "kichu_video_count": 6, "latest_pub_date": 7,
        }],
        play_ranking=[{"mid": 301}],
    )

    from storage.up_obs_reader import get_latest_batch_ts, get_play_ranking

    assert get_latest_batch_ts() == 3000
    assert get_play_ranking(3000) == [{
        "mid": 301, "name": "排行 UP", "face": "face", "total_recent_views": 9,
        "avg_views": 3, "video_count": 4, "follower_count": 5,
        "kichu_video_count": 6, "latest_pub_date": 7,
    }]


def test_up_observation_reader_builds_postgresql_creator_summary_and_details(business_repository):
    legacy_db.configure_business_repository(business_repository)
    legacy_db.upsert_up_obs(
        4000,
        [{
            "mid": 401, "name": "详情 UP", "face": "face", "total_recent_views": 10,
            "avg_views": 5, "video_count": 8, "recent_video_count": 2,
            "follower_count": 3, "kichu_video_count": 1, "recent_kichu_count": 1,
            "latest_pub_date": 100, "sign": "签名", "following_count": 4,
            "latest_videos": [{"bvid": "BV401"}],
        }],
        active_ranking=[{"mid": 401}],
    )

    from storage.up_obs_reader import get_creator_ranking, get_summary, get_up_details

    assert get_creator_ranking(4000) == [{
        "mid": 401, "name": "详情 UP", "face": "face", "recent_video_count": 2,
        "total_recent_views": 10, "avg_views": 5, "follower_count": 3,
        "kichu_video_count": 1, "latest_pub_date": 100,
    }]
    assert get_summary(4000, now=101) == {
        "total_ups": 1, "total_videos": 2, "total_views": 10,
        "avg_views_per_video": 5, "kichu_up_count": 1,
        "kichu_video_count": 1, "active_up_count": 1,
    }
    assert get_up_details(4000) == [{
        "mid": 401, "name": "详情 UP", "face": "face", "sign": "签名",
        "follower_count": 3, "following_count": 4,
        "latest_videos": [{"bvid": "BV401"}], "kichu_video_count": 1,
        "total_recent_views": 10, "latest_pub_date": 100, "avg_views": 5,
        "video_count": 8, "recent_video_count": 2,
    }]


def test_up_card_cache_uses_configured_postgresql_repository(business_repository):
    legacy_db.configure_business_repository(business_repository)
    from storage.up_card_store import read_up_card_cache, write_up_card_cache

    write_up_card_cache(501, {"last_7d_views": 12, "keywords": ["梗"]})

    assert business_repository.up_card_cache(501) == {"last_7d_views": 12, "keywords": ["梗"]}
    assert read_up_card_cache(501) == {"last_7d_views": 12, "keywords": ["梗"]}


def test_legacy_record_video_persists_observation_and_tags_atomically(business_repository):
    legacy_db.configure_business_repository(business_repository)
    legacy_db.record_video({
        "bvid": "BV-combined-record", "title": "combined", "first_seen": 250,
        "views": None, "likes": 0, "coins": 2, "favorites": 3, "shares": 4,
        "comments": 5, "danmaku": 6, "online_count": None,
        "online_precision": "k_plus", "potential_score": 7.5,
        "tags": ["鬼畜", "热梗"],
    }, 250, "test")

    assert business_repository.video_observation_trend("BV-combined-record", 0) == [{
        "ts": 250, "views": None, "likes": 0, "coins": 2, "favorites": 3,
        "shares": 4, "comments": 5, "danmaku": 6, "online_count": None,
        "online_precision": "k_plus", "potential_score": 7.5,
    }]
    from storage.models import video_tags
    with business_repository._sessions() as session:
        tags = session.execute(video_tags.select().where(
            video_tags.c.bvid == "BV-combined-record",
        )).mappings().all()
    assert {row["tag"] for row in tags} == {"鬼畜", "热梗"}


def test_legacy_video_trend_adapter_reads_postgresql(business_repository):
    legacy_db.configure_business_repository(business_repository)
    now = int(time.time())
    legacy_db.record_video({
        "bvid": "BV-trend-adapter", "first_seen": now - 10, "title": "trend",
        "views": 0, "likes": None, "coins": 2, "favorites": 3, "shares": 4,
        "comments": 5, "danmaku": 6, "online_count": 7,
        "online_precision": "exact", "potential_score": 8.5,
    }, now - 10, "test")

    assert legacy_db.get_video_obs_trend("BV-trend-adapter", hours=1) == [{
        "ts": now - 10, "views": 0, "likes": None, "coins": 2, "favorites": 3,
        "shares": 4, "comments": 5, "danmaku": 6, "online_count": 7,
        "online_precision": "exact", "potential_score": 8.5,
    }]


def test_observe_tier_refresh_and_target_selection_use_postgresql(business_repository):
    now = 2_000_000_000
    legacy_db.configure_business_repository(business_repository)
    videos = [
        {"bvid": "BV-hot", "first_seen": now - 10, "pub_date": now - 86400},
        {"bvid": "BV-warm-stale", "first_seen": now - 20, "pub_date": now - 30 * 86400},
        {"bvid": "BV-old-cold", "first_seen": now - 30, "pub_date": now - 100 * 86400},
        {"bvid": "BV-old-growing", "first_seen": now - 40, "pub_date": now - 100 * 86400},
        {"bvid": "BV-promoted", "first_seen": now - 50, "pub_date": now - 100 * 86400},
    ]
    for row in videos:
        business_repository.record_video(row)
    business_repository.record_observation("BV-old-cold", now - 3600, {"views": 1000})
    business_repository.record_observation("BV-old-cold", now, {"views": 1200})
    business_repository.record_observation("BV-old-growing", now - 3600, {"views": 1000})
    business_repository.record_observation("BV-old-growing", now, {"views": 2000})
    business_repository.record_observation("BV-warm-stale", now - 21 * 3600, {"views": 50})

    cold_count = legacy_db.refresh_observe_tiers(now)
    legacy_db.mark_candidates_hot(["BV-promoted"])

    assert cold_count == 1
    assert legacy_db.get_observation_targets(now, hot_limit=10) == [
        "BV-hot", "BV-promoted", "BV-warm-stale",
    ]


def test_bursting_video_ranking_reads_postgresql_observations(business_repository, monkeypatch):
    from config import KICHU_TIDS_WITH_PARENT

    now = 2_000_000_000
    monkeypatch.setattr(legacy_db.time, "time", lambda: now)
    legacy_db.configure_business_repository(business_repository)
    tid = sorted(KICHU_TIDS_WITH_PARENT)[0]
    for ts, views in ((now - 4 * 3600, 100), (now - 2 * 3600, 200), (now, 500)):
        business_repository.record_video({
            "bvid": "BV-burst", "first_seen": now - 100, "title": "爆发",
            "tid": tid, "tname": "鬼畜", "pub_date": now - 3600, "mid": 123,
            "views": views,
        }, ts=ts, source="test")

    result = legacy_db.get_bursting_videos(window_hours=2, threshold=2, limit=20)

    assert len(result) == 1
    assert result[0]["bvid"] == "BV-burst"
    assert result[0]["speed"] == 150
    assert result[0]["prev_speed"] == 50
    assert result[0]["speed_ratio"] == 3
    assert result[0]["is_bursting"] is True
    assert result[0]["spark"] == [100, 200, 500]


def test_register_up_adapter_writes_postgresql(business_repository):
    from storage.models import ups

    legacy_db.configure_business_repository(business_repository)
    assert legacy_db.register_up(456, "作者", "face-url") is True
    assert legacy_db.get_up_names([456]) == {456: "作者"}
    with business_repository._sessions() as session:
        row = session.execute(ups.select().where(ups.c.mid == 456)).mappings().one()
    assert row["face"] == "face-url"
    assert row["tracked"] is True


def test_interaction_quality_statistics_read_postgresql(business_repository):
    from config import KICHU_TIDS_WITH_PARENT

    legacy_db.configure_business_repository(business_repository)
    tid = sorted(KICHU_TIDS_WITH_PARENT)[0]
    ts = 2_000_000_100
    legacy_db.register_up(501, "UP 501", "face")
    business_repository.record_video({
        "bvid": "BV-quality", "mid": 501, "first_seen": ts, "title": "宝藏视频",
        "tid": tid, "tname": "鬼畜", "pub_date": ts - 1000,
        "views": 1000, "likes": 100, "coins": 20, "favorites": 30,
        "shares": 10, "comments": 5, "danmaku": 50, "online_count": 100,
    }, ts=ts, source="test")

    result = legacy_db.get_interaction_quality(limit=20)

    assert len(result) == 1
    assert result[0]["bvid"] == "BV-quality"
    assert result[0]["author"] == "UP 501"
    assert result[0]["coin_ratio"] == 2.0
    assert result[0]["is_treasure"] is False


def test_follower_growth_uses_postgresql_jsonb_observations(business_repository):
    legacy_db.configure_business_repository(business_repository)
    business_repository.upsert_up_observations(
        2_000_000_000, [{"mid": 502, "name": "UP 502", "face": "face", "follower_count": 100}],
    )
    business_repository.upsert_up_observations(
        2_000_000_100, [{"mid": 502, "name": "UP 502", "face": "face", "follower_count": 150}],
    )

    result = legacy_db.get_follower_growth(days=7, limit=10)

    assert result == [{
        "mid": 502, "name": "UP 502", "face": "face", "follower_before": 100,
        "follower_now": 150, "growth": 50, "growth_rate": 50.0,
        "start_ts": 2_000_000_000, "end_ts": 2_000_000_100,
    }]


def test_tag_heat_aggregates_latest_postgresql_observations(business_repository):
    from config import KICHU_TIDS_WITH_PARENT

    legacy_db.configure_business_repository(business_repository)
    tid = sorted(KICHU_TIDS_WITH_PARENT)[0]
    ts = 2_000_000_200
    for index, views in enumerate((1000, 3000), start=1):
        business_repository.record_video({
            "bvid": f"BV-tag-{index}", "mid": 600 + index, "first_seen": ts,
            "title": "视频", "tid": tid, "pub_date": ts - 1000, "tags": ["鬼畜音MAD"],
            "views": views, "likes": 20, "coins": 5, "favorites": 8,
        }, ts=ts, source="test")

    result = legacy_db.get_tag_heat(limit=30, min_count=2)

    assert len(result) == 1
    assert result[0]["tag"] == "鬼畜音MAD"
    assert result[0]["count"] == 2
    assert result[0]["avg_views"] == 2000
