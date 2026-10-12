from sqlalchemy import event, select

from storage.models import video_observations
from storage.repositories.radar import RadarRepository

NOW = 1800000000


def video(bvid='BVradar', **extra):
    return dict(bvid=bvid, first_seen=NOW-86400, pub_date=NOW-86400, tid=216,
                views=10000, likes=500, coins=50, favorites=100, shares=10,
                comments=20, danmaku=30, metrics_source='bilibili_stat',
                observed_at=NOW, **extra)


def test_latest_complete_real_row_and_last_valid_online_are_independent(postgres_runtime):
    business = postgres_runtime.business
    v = video()
    v.update(online_count_raw=1000, online_display='1000+', online_precision='rounded',
             online_observed_at=NOW-3600, observed_at=NOW-3600)
    business.record_video(v, ts=NOW-3600)
    newer = video()
    business.record_video(newer, ts=NOW)
    business.record_observation('BVradar', NOW+1, {'views': 90000})
    context = RadarRepository(postgres_runtime.sessions).video_contexts(['BVradar'], NOW+2)['BVradar']
    assert context['latest']['views'] == 10000
    assert context['latest']['observed_at'] == NOW
    assert context['online']['online_display'] == '1000+'
    assert context['online']['online_observed_at'] == NOW-3600


def test_legacy_and_future_rows_are_not_reference_samples(postgres_runtime):
    business = postgres_runtime.business
    legacy = video('BVlegacy')
    legacy.pop('metrics_source')
    business.record_video(legacy, ts=NOW-1)
    good = video()
    business.record_video(good, ts=NOW-1)
    later = video()
    later['views'] = 99999
    later['observed_at'] = NOW+1
    business.record_video(later, ts=NOW+1)
    rows = RadarRepository(postgres_runtime.sessions).reference_contexts(NOW)
    assert [r['bvid'] for r in rows] == ['BVradar']
    assert rows[0]['latest']['views'] == 10000
    with postgres_runtime.sessions() as session:
        row = session.execute(select(video_observations).where(
            video_observations.c.bvid == 'BVlegacy')).mappings().one()
    assert row['metrics_source'] == 'legacy_unknown'


def test_zero_online_remains_valid_and_query_count_does_not_grow_per_card(postgres_runtime):
    for i in range(20):
        row = video(f'BV{i}')
        row.update(online_count_raw=0, online_observed_at=NOW, online_display='0', online_precision='exact')
        postgres_runtime.business.record_video(row, ts=NOW)
    engine = postgres_runtime.sessions.kw['bind']
    queries = []
    def record(*args):
        queries.append(args[2])
    event.listen(engine, 'before_cursor_execute', record)
    try:
        contexts = RadarRepository(postgres_runtime.sessions).video_contexts([f'BV{i}' for i in range(20)], NOW)
    finally:
        event.remove(engine, 'before_cursor_execute', record)
    assert len(queries) <= 3
    assert len(contexts) == 20
    assert contexts['BV0']['online']['online_count'] == 0


def test_seven_hour_growth_anchor_with_89_minute_old_endpoint_is_returned(postgres_runtime):
    last = video()
    last['observed_at'] = NOW-89*60
    postgres_runtime.business.record_video(last, ts=last['observed_at'])
    prev = {**last, 'views': 9000, 'observed_at': NOW-509*60}
    postgres_runtime.business.record_video(prev, ts=prev['observed_at'])
    c = RadarRepository(postgres_runtime.sessions).video_contexts(['BVradar'], NOW)['BVradar']
    assert any(p['observed_at'] == NOW-509*60 for p in c['history'])
