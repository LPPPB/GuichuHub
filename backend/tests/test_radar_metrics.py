"""视频能力雷达的服务端契约。"""

from utils.radar_metrics import build_radar_metrics
from app import _build_dashboard_payload


def _axis_map(metrics):
    return {axis['id']: axis for axis in metrics['axes']}


def test_radar_metrics_exposes_six_bounded_explainable_axes():
    metrics = build_radar_metrics({
        'views': 100_000,
        'likes': 4_000,
        'coins': 1_000,
        'favorites': 400,
        'shares': 300,
        'comments': 150,
        'danmaku': 500,
        'trend_score': 70,
        'online_count': 800,
    })

    assert metrics['baseline_version'] == 'radar-v1'
    axes = _axis_map(metrics)
    assert list(axes) == ['reach', 'engagement', 'discussion', 'spread', 'momentum', 'live']
    assert axes['reach']['raw'] == 100_000
    assert axes['momentum']['score'] == 70
    assert axes['engagement']['score'] == 100
    assert axes['live']['status'] == 'available'
    assert all(0 <= axis['score'] <= 100 for axis in axes.values())


def test_radar_metrics_preserves_unknown_or_historical_live_attention():
    metrics = build_radar_metrics({
        'views': 80_000,
        'trend_score': 40,
        'online_count': None,
        'online_circuit_skipped': True,
    })

    live = _axis_map(metrics)['live']
    assert live['score'] is None
    assert live['raw'] is None
    assert live['status'] == 'historical'


def test_dashboard_payload_adds_radar_without_mutating_cached_video_data():
    video = {'bvid': 'BV1', 'views': 100_000, 'trend_score': 55, 'online_count': 200}
    payload = _build_dashboard_payload({'hot_videos': [video]}, is_live=False)

    assert payload['hot_videos'][0]['radar']['algorithm_version'] == 'radar-v2'
    assert 'radar' not in video


def test_dashboard_payload_treats_missing_video_lists_as_empty():
    payload = _build_dashboard_payload({'hot_videos': None}, is_live=False)

    assert payload['hot_videos'] == []
