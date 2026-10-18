"""Card counts must come from a single current observation, not ranking discovery."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from services.radar_service import RadarService
from tests.test_radar_v2 import context, NOW


COUNTS = ('views', 'likes', 'coins', 'favorites', 'shares', 'comments', 'danmaku')


def repository(observation):
    return SimpleNamespace(
        load_active_baseline=lambda now: None,
        video_contexts=lambda ids, now: {observation['bvid']: observation},
        revision=lambda: (1, None),
    )


def snapshot(**extra):
    return dict(bvid='BV0', title='original', views=89427, likes=11400,
                coins=465, favorites=2376, shares=418, comments=176, danmaku=127,
                metrics_source='bilibili_stat', observed_at=NOW-3600,
                potential_score=77.3, trend_score=60, **extra)


def current():
    c = context()
    c['latest'].update(views=245764, likes=28966, coins=994, favorites=5714,
                       shares=947, comments=356, danmaku=160)
    return c


@pytest.mark.parametrize('endpoint,field', [
    ('/api/dashboard', 'kichu_rank'), ('/api/dashboard', 'hot_videos'),
    ('/api/dashboard', 'material_candidates'), ('/api/kichu-rank', None),
    ('/api/videos', None), ('/api/material-candidates', None),
])
def test_card_counts_match_latest_curve_point_without_rewriting_ranking(monkeypatch, endpoint, field):
    import app as api
    c = current()
    data = {name: [snapshot(), {'bvid': 'BVunknown', 'views': 10}]
            for name in ('kichu_rank', 'hot_videos', 'material_candidates')}
    data['hot_videos'][0]['potential_score'] = 80
    before = deepcopy(data)
    monkeypatch.setattr('storage.repositories.radar.get_radar_repository', lambda: repository(c))
    monkeypatch.setattr('storage.cache.get_live_cache', lambda: None)
    monkeypatch.setattr('storage.cache.get_data_version', lambda: 1)
    monkeypatch.setattr(api, 'get_data', lambda: data)
    monkeypatch.setattr(api.time, 'time', lambda: NOW)
    monkeypatch.setattr('storage.db.get_video_obs_trend', lambda bvid, hours: [c['latest']])
    api._invalidate_dashboard_payload()
    try:
        with api.app.test_client() as client:
            response = client.get(endpoint)
            point = client.get('/api/videos/BV0/obs-trend').json['data']['points'][-1]
        payload = response.json['data']
        rows = payload[field] if field else payload
        assert [v['bvid'] for v in rows] == ['BV0', 'BVunknown']
        assert {k: rows[0][k] for k in COUNTS} == {k: point[k] for k in COUNTS}
        assert rows[0]['observed_at'] == NOW
        assert rows[0]['potential_score'] == (80 if field == 'hot_videos' or endpoint == '/api/videos' else 77.3)
        assert rows[1]['views'] == 10
        assert data == before
    finally:
        api._invalidate_dashboard_payload()


@pytest.mark.parametrize('field,value', [
    ('views', None), ('likes', -1), ('coins', float('nan')), ('favorites', True),
    ('shares', float('inf')), ('observed_at', NOW+1), ('metrics_source', 'estimated'),
])
def test_invalid_observation_never_partially_overwrites_card(field, value):
    c = current()
    c['latest'][field] = value
    source = snapshot()
    row = RadarService(repository(c)).decorate([source], NOW)[0]
    assert {k: row[k] for k in (*COUNTS, 'observed_at')} == {
        k: source[k] for k in (*COUNTS, 'observed_at')}


def test_newer_manual_statistics_are_not_replaced_by_older_database_point():
    c = current()
    source = snapshot()
    source.update(views=300000, observed_at=NOW)
    c['latest']['observed_at'] = NOW-1
    row = RadarService(repository(c)).decorate([source], NOW)[0]
    assert {k: row[k] for k in (*COUNTS, 'observed_at')} == {
        k: source[k] for k in (*COUNTS, 'observed_at')}


def test_true_zero_counts_replace_older_nonzero_counts():
    c = current()
    c['latest'].update({k: 0 for k in COUNTS})
    source = snapshot()
    row = RadarService(repository(c)).decorate([source], NOW)[0]
    assert [row[k] for k in COUNTS] == [0]*7
    assert row['observed_at'] == NOW
    assert source['views'] == 89427


@pytest.mark.parametrize('status,count,want', [
    ('available', 0, 'available'), ('stale', 24, 'historical'), ('unavailable', None, 'unavailable'),
])
def test_legacy_radar_live_axis_uses_same_observation_as_online_badge(status, count, want):
    from app import _with_radar_metrics
    row = snapshot(online_count=999)
    row['online_observation'] = {'status': status, 'count': count}
    result = _with_radar_metrics([row])[0]
    axis = next(a for a in result['radar']['axes'] if a['id'] == 'live')
    assert axis['status'] == want
    assert axis['raw'] == (0 if status == 'available' else None)
    assert row['online_count'] == 999
