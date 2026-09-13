"""发布日历可靠回填、作者关联、自然日序列与持久化任务测试。"""
import os
import tempfile
from datetime import datetime, timezone, timedelta

import pytest

import collectors.calendar_backfill as backfill
import jobs.calendar_jobs as calendar_jobs
import storage.db as db

CN_TZ = timezone(timedelta(hours=8))


@pytest.fixture
def calendar_db(monkeypatch):
    tmpdir = tempfile.mkdtemp()
    monkeypatch.setattr(db, 'DB_PATH', os.path.join(tmpdir, 'test.db'))
    monkeypatch.setattr(db, 'DATA_DIR', tmpdir)
    db._thread_local.conn = None
    db.get_conn()
    yield
    db._thread_local.conn = None


def _calendar_video(bvid='BV1', mid=1, days_ago=1, views=100):
    pub = datetime.now(CN_TZ) - timedelta(days=days_ago)
    return {
        'bvid': bvid, 'mid': mid, 'pub_date': int(pub.timestamp()),
        'pub_date_str': pub.strftime('%m-%d'), 'views': views, 'title': bvid,
    }


def test_fetch_request_failure_is_not_empty(monkeypatch):
    monkeypatch.setattr(backfill, 'safe_get_with_wbi', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(backfill, 'get_cookie_str', lambda: 'SESSDATA=x')
    with pytest.raises(backfill.CalendarFetchError) as exc:
        backfill.fetch_up_videos_by_year(1, year=datetime.now(CN_TZ).year)
    assert exc.value.code == 'request_failed'


def test_backfill_failure_not_counted_as_success(monkeypatch, calendar_db):
    monkeypatch.setattr(backfill, 'load_tracked_list', lambda: {
        'ups': [{'mid': 1, 'name': 'A', 'enabled': True}],
    })
    monkeypatch.setattr(backfill.time, 'sleep', lambda *_: None)
    monkeypatch.setattr(
        backfill, 'fetch_up_videos_by_year',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            backfill.CalendarFetchError('cookie_expired', 'Cookie 已过期')
        ),
    )
    result = backfill.backfill_calendar(recent_days=7)
    assert result['status'] == 'failed'
    assert result['success_ups'] == 0
    assert result['failed_ups'] == 1


def test_partial_fetch_is_saved_but_reported_partial(monkeypatch, calendar_db):
    partial = [_calendar_video()]
    monkeypatch.setattr(backfill, 'load_tracked_list', lambda: {
        'ups': [{'mid': 1, 'name': 'A', 'enabled': True}],
    })
    monkeypatch.setattr(backfill.time, 'sleep', lambda *_: None)
    monkeypatch.setattr(
        backfill, 'fetch_up_videos_by_year',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            backfill.CalendarFetchError('request_failed', '第二页失败', partial, pages=1)
        ),
    )
    result = backfill.backfill_calendar(recent_days=7)
    assert result['status'] == 'partial'
    assert result['partial_ups'] == 1 and result['total_videos'] == 1
    assert db.get_conn().execute('SELECT COUNT(*) c FROM calendar_videos').fetchone()['c'] == 1


def test_author_relation_survives_representative_mid_change(calendar_db):
    stats = db.upsert_calendar_videos([
        _calendar_video('BV-JOINT', 1, views=100),
        _calendar_video('BV-JOINT', 2, views=200),
    ])
    year = datetime.now(CN_TZ).year
    data = db.get_calendar_data(mids=[1], year=year)
    assert stats['valid'] == 1
    assert sum(v['count'] for v in data.values()) == 1
    assert sum(v['views'] for v in data.values()) == 200


def test_full_scan_soft_reconciliation_requires_two_misses(calendar_db):
    video = _calendar_video('BV-GONE', 1)
    db.upsert_calendar_videos([video])
    year = datetime.fromtimestamp(video['pub_date'], CN_TZ).year
    assert db.get_calendar_data(mids=[1], year=year)
    db.reconcile_calendar_author(1, year, [])
    assert db.get_calendar_data(mids=[1], year=year), '一次未出现不能隐藏'
    db.reconcile_calendar_author(1, year, [])
    assert db.get_calendar_data(mids=[1], year=year) == {}
    db.upsert_calendar_videos([video])
    assert db.get_calendar_data(mids=[1], year=year), '再次抓到后应恢复'


def test_recent_series_contains_every_natural_day(calendar_db):
    db.upsert_calendar_videos([_calendar_video('BV-TODAY', 1, days_ago=0)])
    series = db.get_calendar_recent_series(mids=[1], days=60)
    assert len(series) == 60
    assert all(len(row['date']) == 10 for row in series)
    assert series[-1]['count'] == 1
    dates = [datetime.strptime(row['date'], '%Y-%m-%d').date() for row in series]
    assert all((b - a).days == 1 for a, b in zip(dates, dates[1:]))


def test_calendar_freshness_is_scoped_to_selected_year(calendar_db):
    videos = []
    for year, bvid in ((2025, 'BV-2025'), (2026, 'BV-2026')):
        pub = datetime(year, 1, 2, tzinfo=CN_TZ)
        videos.append({
            'bvid': bvid, 'mid': 1, 'pub_date': int(pub.timestamp()),
            'pub_date_str': pub.strftime('%m-%d'), 'views': 1, 'title': bvid,
        })
    db.upsert_calendar_videos(videos)
    conn = db.get_conn()
    conn.execute("UPDATE calendar_videos SET fetched_at=111 WHERE bvid='BV-2025'")
    conn.execute("UPDATE calendar_videos SET fetched_at=222 WHERE bvid='BV-2026'")
    conn.commit()
    assert db.get_calendar_freshness([1], 2025) == 111
    assert db.get_calendar_freshness([1], 2026) == 222


def test_job_queue_is_persistent_and_deduplicated(monkeypatch, calendar_db):
    monkeypatch.setattr(calendar_jobs, 'load_tracked_list', lambda: {
        'ups': [{'mid': 1, 'name': 'A', 'enabled': True}],
    })
    monkeypatch.setattr(calendar_jobs, 'ensure_calendar_worker', lambda: None)
    first, created = calendar_jobs.enqueue_calendar_job(
        mode='recent', days=7, dedupe_key='test:recent', reason='test',
    )
    second, created_again = calendar_jobs.enqueue_calendar_job(
        mode='recent', days=7, dedupe_key='test:recent', reason='test',
    )
    assert created is True and created_again is False
    assert first['id'] == second['id'] and first['status'] == 'queued'
    claimed = calendar_jobs._claim_next_job('pytest-worker')
    assert claimed['id'] == first['id'] and claimed['status'] == 'running'
