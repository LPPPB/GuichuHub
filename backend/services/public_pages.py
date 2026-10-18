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
    for key in ('author', 'tname', 'trend_label', 'potential_reason', 'pub_date'):
        row[key] = _text(value.get(key))
    row['description'] = _text(value.get('description'), 4000)
    for key in ('views', 'likes', 'shares', 'coins', 'favorites', 'danmaku', 'comments', 'potential_score', 'trend_score', 'online_count', 'duration'):
        row[key] = _number(value.get(key))
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


def _unavailable():
    return {'status': 'unavailable', 'content_version': None, 'source_updated_at': None, 'data': {}}


def _section(data, source_updated_at=None):
    encoded = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    return {'status': 'ready', 'content_version': hashlib.sha256(encoded).hexdigest(),
            'source_updated_at': source_updated_at, 'data': data}


def build_public_sections(dashboard: dict, up_analysis: dict | None) -> dict:
    sections = {tab: _unavailable() for tab in TABS}
    dashboard = dashboard if isinstance(dashboard, dict) else {}
    for tab, field, project in (('kichu-rank', 'kichu_rank', _video), ('videos', 'hot_videos', _video), ('memes', 'hot_memes', _meme)):
        rows = _rows(dashboard.get(field), project)
        if rows:
            sections[tab] = _section({field: rows})
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
