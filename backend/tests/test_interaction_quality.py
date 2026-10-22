"""Interaction quality ranking behavior without an external database."""

from storage import db


NOW = 1_800_000_000
DAY = 86400


def video(bvid, published, *, coins=100, favorites=100, views=1000,
          likes=0, shares=0, comments=0, danmaku=0):
    return {
        'bvid': bvid, 'title': bvid, 'mid': 1, 'author': 'UP', 'tname': '鬼畜',
        'pub_date': published, 'views': views, 'likes': likes, 'coins': coins,
        'favorites': favorites, 'shares': shares, 'comments': comments,
        'danmaku': danmaku,
        'online_count': None,
    }


class ObservationRows:
    def __init__(self, rows):
        self.rows = rows

    def latest_video_observation_ts(self):
        return NOW

    def interaction_quality_rows(self, ts, tids, min_views, max_views):
        return self.rows


class RadarRows:
    def __init__(self, rows, baseline, latest_overrides=None):
        self.rows = {row['bvid']: row for row in rows}
        self.baseline = baseline
        self.latest_overrides = latest_overrides or {}

    def load_active_baseline(self, now):
        return self.baseline

    def video_contexts(self, bvids, now):
        return {
            bvid: {
                'bvid': bvid, 'pub_date': self.rows[bvid]['pub_date'],
                'latest': {**self.rows[bvid], 'metrics_source': 'bilibili_stat',
                           'observed_at': now, **self.latest_overrides.get(bvid, {})},
                'history': [], 'online': None,
            }
            for bvid in bvids
        }


def reference_baseline():
    group = {'values': list(range(1, 201)), 'count': 200,
             'status': 'available', 'cohorts': list(range(6))}
    return {
        'algorithm_version': 'radar-v2', 'version': 'test-reference',
        'valid_until': NOW + DAY,
        'distributions': {
            name: [group] for name in (
                'views', 'likes_rate', 'coins_rate', 'favorites_rate',
                'shares_rate', 'comments_rate', 'danmaku_rate',
            )
        },
    }


def ranked(rows, radar_repository=None):
    db.configure_business_repository(ObservationRows(rows))
    try:
        return db.get_interaction_quality(now=NOW, radar_repository=radar_repository)
    finally:
        db.configure_business_repository(None)


def test_interaction_quality_retires_videos_older_than_fourteen_days():
    rows = [
        video('expired', NOW - 14 * DAY - 1),
        video('boundary', NOW - 14 * DAY),
        video('recent', NOW - DAY),
        video('unknown', 0),
        video('future', NOW + 1),
    ]

    assert {item['bvid'] for item in ranked(rows)} == {'boundary', 'recent'}


def test_interaction_quality_uses_radar_v2_behavior_percentiles():
    rows = [
        video('stronger', NOW - DAY, views=10000, likes=1000, coins=1000,
              favorites=1000, shares=1000, comments=1000, danmaku=1000),
        video('weaker', NOW - DAY, views=10000, likes=500, coins=500,
              favorites=500, shares=500, comments=500, danmaku=500),
    ]

    result = ranked(rows, RadarRows(rows, reference_baseline()))

    assert [item['bvid'] for item in result] == ['stronger', 'weaker']
    assert [item['engagement_score'] for item in result] == [49.8, 24.8]
    assert all(item['score_method'] == 'radar-v2-interaction' for item in result)


def test_interaction_quality_marks_missing_reference_as_unscored():
    rows = [video('pending', NOW - DAY, views=10000)]

    result = ranked(rows, RadarRows(rows, None))

    assert result[0]['engagement_score'] is None
    assert result[0]['score_reason'] == '参考样本不足'


def test_interaction_quality_excludes_video_when_trusted_views_cross_cap():
    rows = [video('already-hot', NOW - DAY, views=999999)]

    result = ranked(rows, RadarRows(
        rows, reference_baseline(), {'already-hot': {'views': 1000001}},
    ))

    assert result == []
