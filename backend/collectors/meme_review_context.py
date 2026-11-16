"""Freeze search settings and record explicit source health for a full crawl."""
from contextvars import ContextVar
from functools import wraps
import time

_round = ContextVar('meme_review_round', default=None)


def frozen_seeds():
    context = _round.get()
    return list(context['seeds']) if context is not None else None


def frozen_aliases():
    from utils.meme_aliases import load_meme_aliases, normalize_meme_key, normalize_meme_name
    context = _round.get()
    if not context or not context.get('dictionary_version'):
        return load_meme_aliases()
    class Index:
        def __init__(self):
            self.mapping = {normalize_meme_key(term): (r['id'], r['name'])
                            for r in context['dictionary'] for term in [r['name'], *r['aliases']]}
        def resolve(self, term):
            return self.mapping.get(normalize_meme_key(term), ('auto:'+normalize_meme_key(term), normalize_meme_name(term)))
        def terms(self):
            return [term for r in context['dictionary'] for term in [r['name'], *r['aliases']]]
    return Index()


def source_health(modern=None, *, board='meme_materials'):
    if modern:
        events = [e for e in modern.events if e['kind'] in ('discovery', 'tags', 'detail')]
        if board == 'hot_memes':
            events = [e for e in events if not (len(e['key']) > 3 and e['key'][0] == 'search_page' and e['key'][3] == 'click')]
        # The bounded algorithm intentionally stops at its request quotas.
        # Budget exhaustion is distinct from an attempted source that failed.
        return any(e['outcome'] == 'success' for e in events) and all(e['outcome'] in ('success','budget') for e in events)
    context = _round.get()
    return bool(context and context['sources']) and all(s['success'] for s in context['sources'])


def record_source(url, result):
    context = _round.get()
    paths = ('/popular', '/ranking', '/newlist', '/search/', '/view', '/tag/')
    if context is None or not any(path in url for path in paths):
        return
    valid = isinstance(result, dict) and result.get('code') == 0 and isinstance(result.get('data'), (dict, list))
    if valid:
        data = result['data']
        if '/popular' in url or '/ranking/v2' in url:
            valid = isinstance(data, dict) and isinstance(data.get('list'), list)
        elif '/newlist' in url:
            valid = isinstance(data, dict) and isinstance(data.get('archives'), list)
        elif '/search/' in url:
            valid = isinstance(data, dict) and isinstance(data.get('result'), list)
        elif '/ranking/region' in url or '/tag/' in url:
            valid = isinstance(data, list)
        elif '/view' in url:
            valid = isinstance(data, dict) and isinstance(data.get('stat'), dict) and bool(data.get('bvid'))
    context['sources'].append({'endpoint': url.split('?')[0], 'success': valid})


def capture_meme_round(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        from collectors.bilibili import load_meme_seed_words
        from storage.runtime_settings import runtime_setting_version
        from services.meme_publication import get_meme_review_service
        try:
            service = get_meme_review_service()
        except RuntimeError:
            service = None
        snapshot = service.seed_snapshot() if service else dict(words=load_meme_seed_words(), version=runtime_setting_version('meme_seed_words'))
        dictionary = service.dictionary_snapshot() if service else {}
        seeds = snapshot['words']
        context = dict(seeds=seeds, seed_version=snapshot['version'],
                       sources=[], started_at=int(time.time()))
        context.update(dictionary)
        token = _round.set(context)
        try:
            result = fn(*args, **kwargs)
            evidence = result.pop('_meme_review_evidence', {})
            modern = kwargs.get('context')
            complete = source_health(modern)
            health = result.pop('_meme_review_health', {})
            result['_meme_review'] = dict(context=context, boards={board: dict(
                complete=health.get(board, complete), evidence_complete=board in evidence,
                cards=result.get(board, []), evidence=evidence.get(board, []),
                seeds=seeds, songs=result.get('hot_songs', []),
                source_status='complete' if health.get(board, complete) else 'incomplete_or_unknown')
                for board in ('hot_memes', 'meme_materials')})
            return result
        finally:
            _round.reset(token)
    return wrapped
