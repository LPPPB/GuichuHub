from copy import deepcopy
import pytest
from utils.radar_v2 import build_baseline, build_video_radar, build_online_observation, percentile_position

NOW = 1800000000


def context(i=0):
    latest = dict(views=10000+i*100, likes=400+i, coins=20+i,
                  favorites=100+i*2, shares=5+i, comments=20+i, danmaku=50+i,
                  metrics_source='bilibili_stat', observed_at=NOW)
    prev = {**latest, 'observed_at': NOW-21600, 'views': latest['views']-600-i*6}
    return dict(bvid=f'BV{i}', pub_date=NOW-3*86400, latest=latest, history=[prev, latest], online=None)


@pytest.fixture
def baseline():
    return build_baseline([context(i) for i in range(240)], NOW, NOW+86400)


def axes(radar):
    return {a['id']: a for a in radar['axes']}


def test_midrank_and_true_zero():
    assert percentile_position(2, [1, 2, 2, 4]) == 50
    assert percentile_position(0, [0, 0, 1, 2]) == 0


def test_growth_uses_actual_six_hour_delta(baseline):
    result = axes(build_video_radar(context(), baseline, NOW))
    assert result['growth']['raw'] == 100
    assert result['growth']['window_hours'] == 6
    assert list(result) == ['reach', 'approval', 'retention', 'discussion', 'sharing', 'growth']


@pytest.mark.parametrize('hours,want', [(4, 'unavailable'), (5, 'available'), (7, 'available'), (8, 'unavailable')])
def test_growth_window_is_bounded_and_uses_real_interval(baseline, hours, want):
    c = context()
    c['history'][0]['observed_at'] = NOW-hours*3600
    a = axes(build_video_radar(c, baseline, NOW))['growth']
    assert a['status'] == want
    if want == 'available':
        assert a['raw'] == round(600/hours, 1)


def test_negative_growth_is_not_zero_and_no_growth_is_zero(baseline):
    c = context()
    c['history'][0]['views'] = 10001
    assert axes(build_video_radar(c, baseline, NOW))['growth']['status'] == 'invalid'
    c['history'][0]['views'] = 10000
    a = axes(build_video_radar(c, baseline, NOW))['growth']
    assert (a['raw'], a['score']) == (0, 0)


def test_single_behavior_changes_only_its_axis(baseline):
    original = context(100)
    before = axes(build_video_radar(original, baseline, NOW))
    for field, axis in [('favorites', 'retention'), ('shares', 'sharing'), ('comments', 'discussion')]:
        changed = deepcopy(original)
        changed['latest'][field] *= 4
        after = axes(build_video_radar(changed, baseline, NOW))
        assert after[axis]['score'] != before[axis]['score']
        assert all(after[k]['score'] == before[k]['score'] for k in before if k != axis)
    original.update(trend_score=100, potential_score=100)
    assert axes(build_video_radar(original, baseline, NOW)) == before


def test_missing_source_missing_counts_stale_and_future_are_explicit(baseline):
    for field, value in [('metrics_source', 'estimated'), ('likes', None), ('views', float('nan')),
                         ('observed_at', NOW+1)]:
        c = context()
        c['latest'][field] = value
        assert all(a['score'] is None for a in build_video_radar(c, baseline, NOW)['axes'])
    c = context()
    assert axes(build_video_radar(c, baseline, NOW+5401))['growth']['status'] == 'stale'
    assert axes(build_video_radar(c, baseline, NOW+86401))['reach']['status'] == 'stale'


def test_baseline_deduplicates_and_rejects_tiny_or_degenerate_samples():
    tiny = build_baseline([context()]*250, NOW, NOW+86400)
    assert tiny['sample_count'] == 1
    assert all(a['score'] is None for a in build_video_radar(context(), tiny, NOW)['axes'])
    rows = [{**context(), 'bvid': f'BV{i}'} for i in range(240)]
    constant = build_baseline(rows, NOW, NOW+86400)
    assert axes(build_video_radar(context(), constant, NOW))['reach']['reason'] == '基准无区分度'


def test_zero_denominator_and_low_sample_are_not_high_interaction(baseline):
    c = context()
    c['latest']['views'] = 0
    a = axes(build_video_radar(c, baseline, NOW))
    assert a['reach']['score'] == 0
    assert a['approval']['score'] is None
    c['latest']['views'] = 1499
    assert axes(build_video_radar(c, baseline, NOW))['sharing']['status'] == 'low_sample'


def test_online_zero_precision_and_expiry_are_separate():
    c = context()
    c['online'] = dict(online_count=0, online_display='0', online_precision='exact', online_observed_at=NOW)
    assert build_online_observation(c, NOW)['count'] == 0
    c['online'].update(online_count=1000, online_display='1000+', online_precision='rounded')
    assert build_online_observation(c, NOW)['display'] == '1000+'
    assert build_online_observation(c, NOW+5401)['status'] == 'stale'


def test_expired_or_missing_baseline_never_uses_page_minmax(baseline):
    assert all(a['score'] is None for a in build_video_radar(context(), None, NOW)['axes'])
    baseline['valid_until'] = NOW
    assert axes(build_video_radar(context(), baseline, NOW))['reach']['reason'] == '基线已到期'


def test_million_views_do_not_automatically_hit_ceiling():
    rows = [context(i) for i in range(240)]
    for i, c in enumerate(rows):
        c['latest']['views'] = 1000000+i*10000
    b = build_baseline(rows, NOW, NOW+86400)
    assert axes(build_video_radar(rows[100], b, NOW))['reach']['score'] == 41.9


def test_numeric_strings_are_normalized_without_changing_input(baseline):
    c = context()
    c['latest'] = {k: str(v) if k != 'metrics_source' else v for k, v in c['latest'].items()}
    assert axes(build_video_radar(c, baseline, NOW))['growth']['raw'] == 100
    assert c['latest']['observed_at'] == str(NOW)
