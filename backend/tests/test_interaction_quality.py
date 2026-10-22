"""Interaction quality ranking behavior without an external database."""

from storage import db


NOW = 1_800_000_000
DAY = 86400


def video(bvid, published, *, coins=100, favorites=100, views=1000):
    return {
        'bvid': bvid, 'title': bvid, 'mid': 1, 'author': 'UP', 'tname': '鬼畜',
        'pub_date': published, 'views': views, 'likes': 0, 'coins': coins,
        'favorites': favorites, 'shares': 0, 'comments': 0, 'danmaku': 0,
        'online_count': None,
    }


class ObservationRows:
    def __init__(self, rows):
        self.rows = rows

    def latest_video_observation_ts(self):
        return NOW

    def interaction_quality_rows(self, ts, tids, min_views, max_views):
        return self.rows


def ranked(rows):
    db.configure_business_repository(ObservationRows(rows))
    try:
        return db.get_interaction_quality(now=NOW)
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


def test_interaction_quality_scores_high_rates_without_a_full_score_tie():
    rows = [
        video('stronger', NOW - DAY, coins=100, favorites=100),
        video('weaker', NOW - DAY, coins=50, favorites=25),
    ]

    result = ranked(rows)

    assert [item['bvid'] for item in result] == ['stronger', 'weaker']
    assert [item['engagement_score'] for item in result] == [71.43, 50.0]
