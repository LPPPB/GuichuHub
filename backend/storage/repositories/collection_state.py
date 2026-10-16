"""Publish source-specific snapshots without mixing them with legacy arrays."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from collectors.official_ranking import SOURCE

PROTECTED_KEYS = frozenset({'official_kichu_snapshot','official_kichu_attempt',
                           'potential_v2_snapshot','potential_v2_attempt','potential_pending'})
LEGACY_FIELDS = frozenset({'kichu_rank','hot_videos','hot_memes','hot_songs',
                          'material_candidates','meme_materials','danmaku_words','comments_gold'})
_repository = None


def _order(value):
    return (value.get('started_at',0),value.get('started_at_ns',0),value.get('attempt_id',''))


def _content_time(at):
    return datetime.fromtimestamp(at,timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')


def merge_official(current, result):
    attempt = result.attempt
    if _order(attempt) >= _order(current.get('official_kichu_attempt') or {}):
        current['official_kichu_attempt'] = deepcopy(attempt)
    snapshot = result.snapshot
    if snapshot and snapshot.get('source') == SOURCE and snapshot.get('rid') == 1007 and snapshot.get('type') == 'all':
        if _order(snapshot) >= _order(current.get('official_kichu_snapshot') or {}):
            current['official_kichu_snapshot'] = deepcopy(snapshot)
            current['last_updated'] = _content_time(snapshot['fetched_at'])


def merge_generation(current, data, result):
    changed = False
    for key in LEGACY_FIELDS:
        if data.get(key):
            current[key] = deepcopy(data[key])
            changed = True
    attempt = result.attempt
    if _order(attempt) >= _order(current.get('potential_v2_attempt') or {}):
        current['potential_v2_attempt'] = deepcopy(attempt)
    snapshot = result.snapshot
    prior = current.get('potential_v2_snapshot') or {}
    if snapshot is not None and _order(snapshot['meta']) >= _order(prior.get('meta') or {}):
        current['potential_v2_snapshot'] = deepcopy(snapshot)
        current['potential_pending'] = deepcopy(result.pending[:400])
        changed = True
    if changed:
        current['last_updated'] = _content_time(attempt['finished_at'] if 'finished_at' in attempt else attempt['started_at'])


class CollectionStateRepository:
    def __init__(self, state, business):
        self.state, self.business = state, business

    def publish_official(self, result, *, guard):
        guard.assert_held()
        if result.snapshot:
            for item in result.snapshot['items']:
                self.business.register_video_metadata({**item,'source':SOURCE},new_tier='warm')
        with guard.publication_connection() as connection:
            return self.state.update_dashboard(lambda current: merge_official(current,result),
                result.attempt['finished_at'],connection=connection)

    def publish_generation(self, data, result, *, guard, mode):
        with guard.publication_connection() as connection:
            return self.state.update_dashboard(lambda current: merge_generation(current,data,result),
                result.attempt['finished_at'],connection=connection)


def configure_collection_repository(repository):
    global _repository
    _repository = repository


def get_collection_repository():
    if _repository is None:
        raise RuntimeError('PostgreSQL collection repository is not configured')
    return _repository
