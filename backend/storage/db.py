"""PostgreSQL-backed compatibility adapters for business persistence.

Public functions remain stable for collectors, jobs, analytics, and routes.
SQLAlchemy sessions and SQL stay inside focused repositories; runtime code
cannot open raw database connections or perform schema migration.
"""

from __future__ import annotations

import math
import statistics
import time
from datetime import datetime, timedelta, timezone

from config import KICHU_TIDS_WITH_PARENT
from utils.scorer import calc_engagement_quality

CN_TZ = timezone(timedelta(hours=8))
_business_repository = None

_VIDEO_SNAPSHOT_FIELDS = frozenset({
    'timeline', 'hot_videos', 'all_videos', 'content_types', 'keyword_cloud', 'pool_summary',
})


def configure_business_repository(repository):
    global _business_repository
    _business_repository = repository


def get_business_repository():
    return _business_repository


def _repository():
    if _business_repository is None:
        raise RuntimeError("PostgreSQL business repository is not configured")
    return _business_repository


def get_conn():
    """Raw connections are intentionally unavailable to business callers."""
    _repository()
    raise RuntimeError("raw database connections are not exposed by the PostgreSQL adapter")


def begin_crawl_run(trigger):
    return _repository().begin_crawl_run(trigger, int(time.time()))


def finish_crawl_run(run_id, status, stats=None):
    _repository().finish_crawl_run(run_id, status, stats or {}, int(time.time()))


def record_video(video, ts, source):
    payload = dict(video)
    payload.setdefault('first_seen', ts)
    payload.setdefault('source', source)
    _repository().record_video(payload, ts=ts, source=source)


def record_obs(bvid, ts, metrics):
    _repository().record_observation(bvid, ts, metrics)


def record_words(words, ts, scope='danmaku'):
    _repository().record_words(words, ts, scope)


def mark_candidates_hot(bvids):
    if bvids:
        _repository().mark_candidates_hot(list(bvids))


def refresh_observe_tiers(now=None):
    return _repository().refresh_observe_tiers(now or int(time.time()))


def get_observation_targets(now=None, hot_limit=500):
    return _repository().observation_targets(now or int(time.time()), hot_limit)


def get_video_obs_trend(bvid, hours=48):
    return _repository().video_observation_trend(
        bvid, start_ts=int(time.time()) - hours * 3600,
    )


def get_bursting_videos(window_hours=2, threshold=2.0, limit=20):
    return _repository().bursting_videos(
        window_hours, threshold, limit, int(time.time()),
        sorted(KICHU_TIDS_WITH_PARENT),
    )


def upsert_up_obs(ts, up_list, play_ranking=None, active_ranking=None):
    if not up_list:
        return 0
    return _repository().upsert_up_observations(
        ts, up_list, play_ranking, active_ranking,
    )


def register_up(mid, name='', face=''):
    if mid is None:
        return False
    _repository().register_up(int(mid), name or '', face or '')
    return True


def get_up_names(mids):
    return _repository().up_names([int(mid) for mid in mids])


def upsert_video_obs_snapshot(ts, field, payload):
    if field not in _VIDEO_SNAPSHOT_FIELDS:
        raise ValueError(f'非法 field: {field}，允许: {sorted(_VIDEO_SNAPSHOT_FIELDS)}')
    return _repository().upsert_snapshot_document(ts, field, payload)


def upsert_video_obs_snapshot_batch(ts, fields_dict):
    for field in fields_dict:
        if field not in _VIDEO_SNAPSHOT_FIELDS:
            raise ValueError(f'非法 field: {field}，允许: {sorted(_VIDEO_SNAPSHOT_FIELDS)}')
    return _repository().upsert_snapshot_batch(ts, fields_dict)


def upsert_calendar_videos(videos, tracked_mids=None):
    fetched = len(videos or [])
    normalized = {}
    authors = set()
    for raw in videos or []:
        bvid = str(raw.get('bvid') or '').strip()
        try:
            mid = int(raw.get('mid'))
            pub_date = int(raw.get('pub_date'))
            views = int(raw.get('views') or 0)
        except (TypeError, ValueError):
            continue
        if not bvid or mid <= 0 or pub_date <= 0:
            continue
        row = {
            'bvid': bvid,
            'mid': mid,
            'pub_date': pub_date,
            'pub_date_str': datetime.fromtimestamp(pub_date, tz=CN_TZ).strftime('%m-%d'),
            'views': max(0, views),
            'title': (raw.get('title') or '')[:200],
        }
        authors.add((bvid, mid))
        current = normalized.get(bvid)
        if current is None or row['views'] >= current['views']:
            normalized[bvid] = row
    if not normalized:
        return {
            'fetched': fetched, 'valid': 0, 'inserted': 0,
            'updated': 0, 'unchanged': 0, 'invalid': fetched,
        }
    return _repository().upsert_calendar_videos(
        list(normalized.values()), authors, fetched, int(time.time()),
    )


def get_calendar_data(mids=None, year=None):
    if year is None:
        year = datetime.now(CN_TZ).year
    year_start = int(datetime(year, 1, 1, tzinfo=CN_TZ).timestamp())
    year_end = int(datetime(year + 1, 1, 1, tzinfo=CN_TZ).timestamp()) - 1
    return _repository().calendar_data(year_start, year_end, mids)


def get_calendar_freshness(mids=None, year=None):
    if mids == []:
        return None
    year_start = year_end = None
    if year is not None:
        year_start = int(datetime(int(year), 1, 1, tzinfo=CN_TZ).timestamp())
        year_end = int(datetime(int(year) + 1, 1, 1, tzinfo=CN_TZ).timestamp())
    return _repository().calendar_freshness(mids, year_start, year_end)


def get_calendar_recent_series(mids=None, days=60):
    return _repository().calendar_recent_series(mids, days)


def get_calendar_day_videos(date_str, mids=None, limit=50):
    limit = max(1, min(int(limit or 50), 100))
    return _repository().calendar_day_videos(date_str, mids, limit)


def reconcile_calendar_author(mid, year, seen_bvids, missing_threshold=2):
    year_start = int(datetime(year, 1, 1, tzinfo=CN_TZ).timestamp())
    year_end = int(datetime(year + 1, 1, 1, tzinfo=CN_TZ).timestamp())
    seen = {str(value) for value in (seen_bvids or []) if value}
    return _repository().reconcile_calendar_author(
        mid, year_start, year_end, seen, missing_threshold,
    )


def get_interaction_quality(limit=20, min_views=1000, max_views=1000000):
    repository = _repository()
    latest_ts = repository.latest_video_observation_ts()
    if latest_ts is None:
        return []
    rows = repository.interaction_quality_rows(
        latest_ts, sorted(KICHU_TIDS_WITH_PARENT), min_views, max_views,
    )
    if not rows:
        return []

    def pct(number, views):
        return round(number / views * 100, 3) if views and number else 0.0

    items = []
    for row in rows:
        views = row['views'] or 0
        if views <= 0:
            continue
        item = {
            'bvid': row['bvid'], 'title': row['title'] or '', 'mid': row['mid'],
            'author': row['author'] or '', 'tname': row['tname'] or '',
            'pub_date': row['pub_date'] or 0, 'views': views,
            'likes': row['likes'] or 0, 'coins': row['coins'] or 0,
            'favorites': row['favorites'] or 0, 'shares': row['shares'] or 0,
            'comments': row['comments'] or 0, 'danmaku': row['danmaku'] or 0,
            'online_count': row['online_count'],
            'coin_ratio': pct(row['coins'], views),
            'fav_ratio': pct(row['favorites'], views),
            'like_ratio': pct(row['likes'], views),
            'share_ratio': pct(row['shares'], views),
            'danmaku_ratio': pct(row['danmaku'], views),
            'online_ratio': pct(row['online_count'], views),
            'engagement_score': calc_engagement_quality({
                'views': views, 'likes': row['likes'] or 0,
                'coins': row['coins'] or 0, 'favorites': row['favorites'] or 0,
                'shares': row['shares'] or 0, 'comments': row['comments'] or 0,
                'danmaku': row['danmaku'] or 0,
            }),
        }
        items.append(item)
    if not items:
        return []
    views_median = statistics.median(item['views'] for item in items)
    coin_median = statistics.median(item['coin_ratio'] for item in items)
    for item in items:
        item['is_treasure'] = bool(
            item['views'] < views_median and item['coin_ratio'] > coin_median,
        )
    return sorted(items, key=lambda item: item['engagement_score'], reverse=True)[:limit]


def get_publish_habits(mids=None, days=180):
    return _repository().publish_habits(mids, days, int(time.time()))


def get_follower_growth(days=7, limit=10):
    return _repository().follower_growth(days, limit)


def get_tag_heat(limit=30, min_count=2):
    repository = _repository()
    if repository.latest_video_observation_ts() is None:
        return []
    rows = repository.tag_heat_rows(sorted(KICHU_TIDS_WITH_PARENT), min_count)
    from collectors.bilibili import is_useless_tag
    items = []
    for row in rows:
        if is_useless_tag(row['tag']):
            continue
        items.append({
            'tag': row['tag'], 'count': row['cnt'],
            'avg_views': int(row['avg_views'] or 0),
            'avg_likes': int(row['avg_likes'] or 0),
            'avg_coins': int(row['avg_coins'] or 0),
            'avg_favs': int(row['avg_favs'] or 0),
        })
    if not items:
        return []
    median_views = statistics.median(item['avg_views'] for item in items)
    for item in items:
        item['is_hot'] = item['avg_views'] > median_views
    return sorted(
        items, key=lambda item: (item['count'], item['avg_views']), reverse=True,
    )[:limit]


def get_rising_words(recent_batches=2, base_batches=6, min_recent=3, limit=30,
                     return_meta=False):
    from analytics.filters import filter_danmaku_words

    recent_batches = max(1, min(int(recent_batches), 12))
    base_batches = max(1, min(int(base_batches), 30))
    repository = _repository()
    batch_rows = repository.rising_word_batch_totals(recent_batches + base_batches)
    meta = {
        'method': 'batch_rate_per_10k',
        'recent_batch_count': min(len(batch_rows), recent_batches),
        'base_batch_count': max(0, len(batch_rows) - recent_batches),
        'requested_recent_batches': recent_batches,
        'requested_base_batches': base_batches,
        'latest_ts': batch_rows[0]['ts'] if batch_rows else None,
        'is_stale': True, 'data_age_hours': None,
        'sufficient': len(batch_rows) >= recent_batches + 1,
    }
    if not batch_rows:
        return ([], meta) if return_meta else []

    latest_ts = batch_rows[0]['ts']
    age_hours = max(0.0, (time.time() - latest_ts) / 3600)
    meta['data_age_hours'] = round(age_hours, 1)
    meta['is_stale'] = age_hours > 18
    recent_rows = batch_rows[:recent_batches]
    base_rows = batch_rows[recent_batches:]
    if not base_rows:
        return ([], meta) if return_meta else []

    recent_ts = [row['ts'] for row in recent_rows]
    base_ts = [row['ts'] for row in base_rows]
    totals = {row['ts']: max(int(row['total_count'] or 0), 1) for row in batch_rows}
    by_word = {}
    for row in repository.rising_word_observations(recent_ts + base_ts):
        by_word.setdefault(row['word'], {})[row['ts']] = int(row['count'] or 0)

    items = []
    for word, observations in by_word.items():
        recent_counts = [observations.get(ts, 0) for ts in recent_ts]
        base_counts = [observations.get(ts, 0) for ts in base_ts]
        recent_avg = sum(recent_counts) / len(recent_ts)
        base_avg = sum(base_counts) / len(base_ts)
        recent_presence = sum(value > 0 for value in recent_counts)
        base_presence = sum(value > 0 for value in base_counts)
        if recent_avg < min_recent:
            continue
        recent_rate = sum(
            observations.get(ts, 0) / totals[ts] * 10000 for ts in recent_ts
        ) / len(recent_ts)
        base_rate = sum(
            observations.get(ts, 0) / totals[ts] * 10000 for ts in base_ts
        ) / len(base_ts)
        is_new = base_presence == 0
        if is_new and recent_presence < min(2, len(recent_ts)):
            continue
        growth_ratio = (recent_rate + 0.5) / (base_rate + 0.5)
        if not is_new and growth_ratio <= 1.15:
            continue
        coverage = recent_presence / len(recent_ts)
        trend_score = (
            math.log2(max(growth_ratio, 1.0))
            * math.log1p(recent_avg)
            * (0.6 + 0.4 * coverage)
        )
        items.append({
            'word': word, 'recent_count': round(recent_avg),
            'base_count': round(base_avg), 'recent_rate': round(recent_rate, 2),
            'base_rate': round(base_rate, 2), 'recent_presence': recent_presence,
            'base_presence': base_presence, 'growth_ratio': round(growth_ratio, 2),
            'trend_score': round(trend_score, 3), 'is_new': is_new,
        })

    kept = {
        row['word'] for row in filter_danmaku_words([
            {'word': item['word'], 'count': item['recent_count']} for item in items
        ])
    }
    result = sorted(
        (item for item in items if item['word'] in kept),
        key=lambda item: (item['trend_score'], item['recent_rate']),
        reverse=True,
    )[:limit]
    return (result, meta) if return_meta else result
