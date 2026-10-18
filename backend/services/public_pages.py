"""Read-only, identity-independent projections for public HTML publication.

Never serialize whole business records. A new public field needs an explicit
projection here; this module does not import collectors or write repositories.
"""
import hashlib
import json
import math
import re
from urllib.parse import urlsplit

TABS = ('dashboard', 'kichu-rank', 'memes', 'videos', 'meme-materials', 'songs', 'materials', 'danmaku', 'up-trends')
MAX_BYTES = 2 * 1024 * 1024
_BVID = re.compile(r'BV[A-Za-z0-9]{10}\Z')


def _text(value, limit=1000):
    return value[:limit] if isinstance(value, str) else None


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def _image(value):
    if not isinstance(value, str) or len(value) > 1000:
        return None
    try:
        url = urlsplit(value)
        host = url.hostname or ''
        return value if (url.scheme == 'https' and not url.username and not url.password and url.port in (None, 443)
                         and any(host == domain or host.endswith('.' + domain) for domain in ('hdslb.com', 'bilibili.com'))) else None
    except ValueError:
        return None


def _video(value):
    if not isinstance(value, dict) or not isinstance(value.get('bvid'), str) or not _BVID.fullmatch(value['bvid']):
        return None
    title = _text(value.get('title'), 500)
    if not title:
        return None
    row = {'bvid': value['bvid'], 'title': title, 'cover': _image(value.get('cover'))}
    for key in ('author', 'tname', 'trend_label', 'potential_reason', 'material_reason', 'up_name'):
        row[key] = _text(value.get(key))
    row['description'] = _text(value.get('description'), 4000)
    for key in ('views', 'likes', 'shares', 'coins', 'favorites', 'danmaku', 'comments', 'potential_score', 'material_score', 'trend_score', 'online_count', 'duration', 'pub_date', 'up_mid'):
        row[key] = _number(value.get(key))
    # Persisted observations are historical by the time cached HTML is served.
    row['online_circuit_skipped'] = row['online_count'] is not None
    return row


def _rows(value, project, limit=200):
    if not isinstance(value, list):
        return []
    result = []
    for item in value[:limit]:
        projected = project(item)
        if projected is not None:
            result.append(projected)
    return result


def _meme(value):
    if not isinstance(value, dict) or not _text(value.get('keyword'), 500):
        return None
    return {'keyword': _text(value['keyword'], 500), 'heat': _number(value.get('heat')),
            'trend_label': _text(value.get('trend_label')),
            'related_videos': _rows(value.get('related_videos'), _video, 20)}


def _material(value):
    if not isinstance(value, dict) or not _text(value.get('name'), 500):
        return None
    return {'name': _text(value['name'], 500), 'description': _text(value.get('description'), 4000),
            'aliases': [s[:500] for s in (value.get('aliases') or [])[:20] if isinstance(s, str)] if isinstance(value.get('aliases'), list) else [],
            'video_count': _number(value.get('video_count')), 'total_views': _number(value.get('total_views')),
            'related_videos': _rows(value.get('related_videos'), _video, 20)}


def _song(value):
    if not isinstance(value, dict) or not _text(value.get('name'), 500):
        return None
    row = _video({**value, 'title': value['name']})
    if row is None:
        return None
    return {**row, 'name': _text(value['name'], 500), 'plays': _number(value.get('plays')),
            'heat': _number(value.get('heat'))}


def _word(value):
    if not isinstance(value, dict) or not _text(value.get('word'), 500):
        return None
    return {'word': _text(value['word'], 500), 'count': _number(value.get('count')),
            'weight': _number(value.get('weight'))}


def _comment(value):
    if not isinstance(value, dict) or not _text(value.get('content'), 4000):
        return None
    return {'content': _text(value['content'], 4000), 'author': _text(value.get('author'), 500),
            'source_video': _text(value.get('source_video'), 500),
            'source_bvid': value.get('source_bvid') if isinstance(value.get('source_bvid'), str) and _BVID.fullmatch(value['source_bvid']) else None,
            'source_cover': _image(value.get('source_cover')), 'author_avatar': _image(value.get('author_avatar')),
            **{key: _number(value.get(key)) for key in ('likes', 'replies', 'author_level')}}


def _up(value):
    if not isinstance(value, dict) or not _text(value.get('name'), 500):
        return None
    row = {'name': _text(value['name'], 500), 'face': _image(value.get('face')), 'sign': _text(value.get('sign')),
           'latest_videos': _rows(value.get('latest_videos'), _video, 20)}
    for key in ('mid', 'total_recent_views', 'avg_views', 'video_count', 'recent_video_count', 'follower_count',
                'following_count', 'kichu_video_count', 'latest_pub_date'):
        row[key] = _number(value.get(key))
    return row


def _up_analysis(value):
    if not isinstance(value, dict) or not isinstance(value.get('analysis'), dict):
        return None
    created = _number(value.get('created_at'))
    if not created or created <= 0:
        return None
    analysis = value['analysis']
    source_summary = analysis.get('summary') if isinstance(analysis.get('summary'), dict) else {}
    summary = {key: _number(source_summary.get(key)) for key in ('total_ups', 'total_views', 'total_videos',
               'avg_views_per_video', 'kichu_up_count', 'kichu_video_count', 'active_up_count', 'pool_total_views',
               'pool_total_videos', 'pool_avg_views_per_video')}
    return {'created_at': created, 'tracked_up_count': _number(value.get('tracked_up_count')),
            'up_details': _rows(value.get('up_details'), _up),
            'analysis': {'summary': summary, 'hot_videos': _rows(analysis.get('hot_videos'), _video),
                         'play_ranking': _rows(analysis.get('play_ranking'), _up),
                         'creator_ranking': _rows(analysis.get('creator_ranking'), _up),
                         'keyword_cloud': _rows(analysis.get('keyword_cloud'), _up_keyword),
                         'content_types': _rows(analysis.get('content_types'), _content_type),
                         'timeline': _rows(analysis.get('timeline'), _timeline, 60)}}


def _timeline(value):
    if not isinstance(value, dict) or not isinstance(value.get('date'), str) or not re.fullmatch(r'(?:\d{4}-)?\d{2}-\d{2}', value['date']):
        return None
    return {'date': value['date'], 'count': _number(value.get('count')), 'views': _number(value.get('views'))}


def _content_type(value):
    if not isinstance(value, dict) or not _text(value.get('type'), 500):
        return None
    return {'type': _text(value['type'], 500), 'count': _number(value.get('count'))}


def _up_keyword(value):
    if not isinstance(value, dict) or not _text(value.get('text'), 500):
        return None
    return {'text': _text(value['text'], 500), 'value': _number(value.get('value'))}


def _unavailable():
    return {'status': 'unavailable', 'content_version': None, 'source_updated_at': None, 'data': {}}


def _section(data, source_updated_at=None):
    encoded = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    return {'status': 'ready', 'content_version': hashlib.sha256(encoded).hexdigest(),
            'source_updated_at': source_updated_at, 'data': data}


def build_public_sections(dashboard: dict, up_analysis: dict | None) -> dict:
    sections = {tab: _unavailable() for tab in TABS}
    dashboard = dashboard if isinstance(dashboard, dict) else {}
    for tab, field, project in (('kichu-rank', 'kichu_rank', _video), ('videos', 'hot_videos', _video), ('memes', 'hot_memes', _meme),
                                ('meme-materials', 'meme_materials', _material), ('songs', 'hot_songs', _song),
                                ('materials', 'material_candidates', _video)):
        rows = _rows(dashboard.get(field), project)
        if rows:
            sections[tab] = _section({field: rows})
    words = _rows(dashboard.get('danmaku_words'), _word)
    comments = _rows(dashboard.get('comments_gold'), _comment)
    if words or comments:
        sections['danmaku'] = _section({'danmaku_words': words, 'comments_gold': comments})
    public_up = _up_analysis(up_analysis)
    if public_up:
        sections['up-trends'] = _section({'up_analysis': public_up}, public_up['created_at'])
    result = {'schema_version': 1, 'sections': sections}
    if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode('utf-8')) > MAX_BYTES:
        raise ValueError('Public page export exceeds byte limit')
    return result


def load_public_pages() -> dict:
    from storage.cache import get_data
    from storage.up_trends_reader import load_analysis
    try:
        dashboard = get_data()
    except Exception:
        dashboard = None
    try:
        up_analysis = load_analysis()
    except Exception:
        up_analysis = None
    return build_public_sections(dashboard, up_analysis)
