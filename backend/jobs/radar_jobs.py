"""Worker-only, immutable weekly references; no network collection."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import time

from storage.repositories.radar import get_radar_repository
from utils.radar_v2 import build_baseline, MIN_REFERENCE


def week_start(now):
    local = datetime.fromtimestamp(now, ZoneInfo('Asia/Shanghai'))
    monday = (local-timedelta(days=local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(monday.timestamp())


def run_radar_baseline_job(now=None):
    now = int(time.time()) if now is None else now
    repository = get_radar_repository()
    if repository is None:
        return {'status': 'unconfigured'}
    if repository.load_active_baseline(now):
        return {'status': 'unchanged'}
    _, previous = repository.revision()
    start = week_start(now)
    cutoff = start if previous else now
    baseline = build_baseline(repository.reference_contexts(cutoff), cutoff, start+7*86400)
    if not any(g['status'] == 'available' for groups in baseline['distributions'].values() for g in groups):
        return {'status': 'insufficient', 'sample_count': baseline['sample_count']}
    # Legacy observations have no verifiable source. Warm up the first reference
    # before freezing it for the week, rather than freezing an empty growth axis.
    if not previous and not any(g['count'] >= MIN_REFERENCE for g in baseline['distributions']['speed']):
        return {'status': 'warming_up', 'sample_count': baseline['sample_count']}
    baseline['version'] = f"radar-v2-{'weekly' if previous else 'bootstrap'}-{cutoff}"
    published = repository.publish_baseline(baseline, now)
    return {'status': 'published' if published else 'unchanged', 'version': baseline['version'],
            'sample_count': baseline['sample_count']}
