"""Refresh display counts atomically without changing ranking snapshots or scores."""
from utils.radar_v2 import COUNTS, number


def with_observed_statistics(video, latest, now):
    result = dict(video)
    if not latest or latest.get('metrics_source') != 'bilibili_stat':
        return result
    observed_at = number(latest.get('observed_at'))
    if not observed_at or observed_at > now or any(number(latest.get(k)) is None for k in COUNTS):
        return result
    snapshot_at = number(video.get('observed_at')) or 0
    if snapshot_at <= now and snapshot_at > observed_at:
        return result
    result.update({k: latest[k] for k in COUNTS})
    result.update(observed_at=latest['observed_at'], metrics_source=latest['metrics_source'])
    return result
