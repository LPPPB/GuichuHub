from copy import deepcopy
from services.radar_service import RadarService
from storage.repositories.radar import RadarRepository
from utils.radar_v2 import build_baseline
from tests.test_radar_v2 import context, NOW


def prepare(runtime):
    c = context(100)
    row = dict(**c['latest'], bvid=c['bvid'], first_seen=NOW-86400, pub_date=c['pub_date'], tid=216,
               online_count_raw=0, online_observed_at=NOW, online_precision='exact', online_display='0')
    runtime.business.record_video(row, ts=NOW)
    runtime.business.record_observation(c['bvid'], NOW-21600, c['history'][0])
    repo = RadarRepository(runtime.sessions)
    repo.publish_baseline(build_baseline([context(i) for i in range(240)], NOW, NOW+86400), NOW)
    return repo, row


def test_decorate_does_not_mutate_cached_video_or_scores(postgres_runtime):
    repo, row = prepare(postgres_runtime)
    video = dict(bvid=row['bvid'], title='same', views=999, potential_score=88, trend_score=77)
    before = deepcopy(video)
    result = RadarService(repo).decorate([video], NOW)
    assert video == before
    assert result[0]['views'] == 999
    assert result[0]['potential_score'] == 88
    assert result[0]['radar']['axes'][0]['raw'] == 20000
    assert result[0]['online_observation']['count'] == 0


def test_observation_revision_refreshes_dashboard_within_same_time_bucket(client, postgres_runtime, monkeypatch):
    import app as app_module
    repo, row = prepare(postgres_runtime)
    data = {'kichu_rank': [dict(bvid=row['bvid'], views=999, potential_score=88)]}
    monkeypatch.setattr(app_module, 'get_data', lambda: data)
    monkeypatch.setattr('storage.cache.get_live_cache', lambda: None)
    clock = [NOW]
    monkeypatch.setattr(app_module.time, 'time', lambda: clock[0])
    app_module._invalidate_dashboard_payload()
    first = client.get('/api/dashboard').json['data']['kichu_rank'][0]
    newer = {**row, 'views': 22222, 'observed_at': NOW+1, 'online_count_raw': 1,
             'online_observed_at': NOW+1, 'online_display': '1'}
    postgres_runtime.business.record_video(newer, ts=NOW+1)
    repo.touch_observations(NOW+1)
    clock[0] += 1
    second = client.get('/api/dashboard').json['data']['kichu_rank'][0]
    assert first['radar']['axes'][0]['raw'] == 20000
    assert second['radar']['axes'][0]['raw'] == 22222
    assert second['online_observation']['count'] == 1
    assert second['potential_score'] == 88
    assert 'radar' not in data['kichu_rank'][0]
    clock[0] = NOW+5460
    expired = client.get('/api/dashboard').json['data']['kichu_rank'][0]
    assert expired['online_observation']['status'] == 'stale'
    assert expired['radar']['axes'][-1]['status'] == 'stale'
    assert client.get('/api/kichu-rank').json['data'][0]['radar']['algorithm_version'] == 'radar-v2'
