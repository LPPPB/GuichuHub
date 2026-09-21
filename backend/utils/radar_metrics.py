"""视频能力雷达的稳定展示口径。

雷达图不使用当前页面的 Min-Max，避免排序、分页或单条爆款改变同一视频的形状。
v1 采用面向鬼畜候选池的固定阈值；将来替换为持久化分位数基线时，只需新增版本，
前端仍消费同一 payload 契约。
"""

import math

from utils.scorer import calc_engagement_quality, calc_online_index


BASELINE_VERSION = 'radar-v1'
REACH_REFERENCE = 1_000_000
DISCUSSION_REFERENCE = 0.04
SPREAD_REFERENCE = 0.025


def _number(value):
    try:
        return max(0.0, float(value or 0))
    except (TypeError, ValueError):
        return 0.0


def _bounded(value):
    return round(min(100.0, max(0.0, value)), 1)


def _log_score(value, reference):
    """将长尾量映射到 0~100，reference 对应满分并封顶。"""
    if reference <= 0:
        return 0.0
    return _bounded(math.log1p(_number(value)) / math.log1p(reference) * 100)


def _rate(video, weights):
    views = max(1.0, _number(video.get('views')))
    weighted = sum(_number(video.get(field)) * weight for field, weight in weights.items())
    return weighted / views


def _axis(axis_id, label, score, raw, status='available'):
    return {
        'id': axis_id,
        'label': label,
        'score': score,
        'raw': raw,
        'status': status,
    }


def build_radar_metrics(video):
    """构造单条视频的六维雷达 payload。

    所有可用维度为 0~100；同接在采集熔断或缺失时保持 None，不能伪装成低分。
    """
    views = int(_number(video.get('views')))
    engagement_rate = _rate(video, {
        'likes': 1.0, 'coins': 2.0, 'favorites': 1.5, 'shares': 5.0,
        'comments': 2.0, 'danmaku': 2.5,
    })
    discussion_rate = _rate(video, {'comments': 2.0, 'danmaku': 2.5})
    spread_rate = _rate(video, {'shares': 5.0, 'favorites': 1.5})
    trend_score = _bounded(_number(video.get('trend_score')))

    if video.get('online_circuit_skipped'):
        live_score, live_raw, live_status = None, None, 'historical'
    elif video.get('online_count') is None:
        live_score, live_raw, live_status = None, None, 'unavailable'
    else:
        live_raw = int(_number(video.get('online_count')))
        live_score, live_status = calc_online_index(video), 'available'

    return {
        'baseline_version': BASELINE_VERSION,
        'axes': [
            _axis('reach', '播放规模', _log_score(views, REACH_REFERENCE), views),
            _axis('engagement', '互动质量', calc_engagement_quality(video), round(engagement_rate, 6)),
            _axis('discussion', '讨论热度', _log_score(discussion_rate, DISCUSSION_REFERENCE), round(discussion_rate, 6)),
            _axis('spread', '传播能力', _log_score(spread_rate, SPREAD_REFERENCE), round(spread_rate, 6)),
            _axis('momentum', '增长动能', trend_score, trend_score),
            _axis('live', '实时关注', live_score, live_raw, live_status),
        ],
    }
