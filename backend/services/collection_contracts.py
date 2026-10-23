"""Versioned collection values; no HTTP or database work at import time."""
from dataclasses import dataclass, field
from typing import Literal
from html import unescape
import re

STAT_KEYS = dict(view='views', like='likes', coin='coins', favorite='favorites',
                 share='shares', reply='comments', danmaku='danmaku')


def nonnegative_int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    return value if isinstance(value, int) and value >= 0 else None


def normalize_category(raw: dict) -> dict | None:
    keys = ('tidv2', 'tnamev2', 'pid_v2', 'pid_name_v2')
    if not any(key in raw for key in keys):
        return None
    return dict(tid=nonnegative_int(raw.get('tidv2')), tname=raw.get('tnamev2'),
                pid=nonnegative_int(raw.get('pid_v2')), pid_name=raw.get('pid_name_v2'))


def classify_kichu(video: dict) -> Literal['eligible', 'ineligible', 'unknown']:
    category = video.get('category_v2')
    if category is not None:
        if not isinstance(category, dict):
            return 'unknown'
        parent = nonnegative_int(category.get('pid'))
        if parent:
            return 'eligible' if parent == 1007 else 'ineligible'
        return 'eligible' if nonnegative_int(category.get('tid')) == 2063 else 'unknown'
    from config import KICHU_TIDS
    tid = nonnegative_int(video.get('tid'))
    return ('eligible' if tid in KICHU_TIDS else 'ineligible') if tid else 'unknown'


@dataclass(frozen=True)
class StatSample:
    metrics: dict[str, int]
    endpoint: str
    observed_at: int


def core_stat_sample(raw: dict, *, endpoint: str, observed_at: int) -> StatSample | None:
    stat = raw.get('stat')
    if not isinstance(stat, dict):
        return None
    metrics = {target: nonnegative_int(stat.get(key)) for key, target in STAT_KEYS.items()}
    if any(value is None for value in metrics.values()):
        return None
    return StatSample(metrics, endpoint, observed_at)


def video_from_api(raw: dict, *, endpoint: str, observed_at: int) -> dict:
    """Normalize metadata without manufacturing missing interaction counts."""
    owner = raw.get('owner') if isinstance(raw.get('owner'), dict) else {}
    def clean(value):
        return unescape(re.sub(r'<[^>]*>', '', str(value or '')))
    def url(value):
        value = str(value or '')
        return 'https:' + value if value.startswith('//') else value
    duration = raw.get('duration', 0)
    if isinstance(duration, str) and ':' in duration:
        try:
            parts = [int(p) for p in duration.split(':')]
            duration = sum(p * 60**i for i, p in enumerate(reversed(parts)))
        except ValueError:
            duration = 0
    video = dict(bvid=raw.get('bvid'), aid=nonnegative_int(raw.get('aid')),
                 cid=nonnegative_int(raw.get('cid')), title=clean(raw.get('title')),
                 description=clean(raw.get('desc') or raw.get('description'))[:300],
                 cover=url(raw.get('pic') or raw.get('cover')),
                 author=clean(owner.get('name') or raw.get('author')),
                 author_avatar=url(owner.get('face') or raw.get('upic')),
                 mid=nonnegative_int(owner.get('mid') or raw.get('mid')),
                 tid=nonnegative_int(raw.get('tid') or raw.get('typeid')),
                 tname=clean(raw.get('tname') or raw.get('typename')),
                 category_v2=normalize_category(raw),
                 pub_date=nonnegative_int(raw.get('pubdate') or raw.get('senddate')) or 0,
                 duration=nonnegative_int(duration) or 0, tags=[], first_seen=observed_at,
                 metrics_source='legacy_unknown', observed_at=None,
                 url=f"https://www.bilibili.com/video/{raw.get('bvid', '')}")
    video.update({value: None for value in STAT_KEYS.values()})
    sample = None if endpoint == 'newest' else core_stat_sample(raw, endpoint=endpoint, observed_at=observed_at)
    if sample:
        video.update(sample.metrics, metrics_source='bilibili_stat',
                     metrics_endpoint=endpoint, observed_at=observed_at)
    elif endpoint == 'search':
        video['views'] = nonnegative_int(raw.get('play'))
    tag = raw.get('tag')
    if isinstance(tag, str):
        video['tags'] = [t.strip() for t in tag.split(',') if t.strip()]
    return video


@dataclass(frozen=True)
class CollectionPolicy:
    mode: str = 'shadow'
    candidate_limit: int = 400
    pending_limit: int = 400
    detail_limit: int = 160
    tag_limit: int = 64
    online_limit: int = 160
    discovery_limit: int = 60
    popular_pages: int = 15
    kichu_search_pages: int = 16
    music_search_pages: int = 7
    funny_search_pages: int = 7
    seed_search_pages: int = 8
    refresh_seconds: int = 1800
    stale_seconds: int = 3600
    historical_seconds: int = 86400
    observe_limit: int = 200
    views_min: int = 1500
    views_max: int = 1000000
    engagement_min: int = 10
    age_days: int = 21

    def __post_init__(self):
        if self.mode not in {'legacy', 'shadow', 'official'}:
            raise ValueError('Invalid COLLECTION_RULES_MODE')
        if any(isinstance(v, bool) or not isinstance(v, int) or v < 0
               for k, v in vars(self).items() if k != 'mode'):
            raise ValueError('Collection limits must be nonnegative integers')
        if min(self.candidate_limit, self.pending_limit, self.refresh_seconds, self.age_days) == 0:
            raise ValueError('Collection sizes and windows must be positive')
        if self.views_min > self.views_max or self.stale_seconds < self.refresh_seconds:
            raise ValueError('Invalid collection threshold range')
        if self.mode != 'legacy' and self.observe_limit < 50:
            raise ValueError('OBSERVE_HOT_LIMIT must cover 50 visible candidates')
        caps = dict(candidate_limit=400,pending_limit=400,detail_limit=160,tag_limit=64,
                    online_limit=160,discovery_limit=60,popular_pages=15,kichu_search_pages=16,
                    music_search_pages=7,funny_search_pages=7,seed_search_pages=8)
        if any(getattr(self,key)>cap for key,cap in caps.items()):
            raise ValueError('Collection budget exceeds the supported cap')


@dataclass
class OfficialFetchResult:
    snapshot: dict | None
    attempt: dict


@dataclass
class DiscoveryResult:
    lanes: dict
    derived: dict
    pending: list = field(default_factory=list)
    attempt: dict = field(default_factory=dict)


@dataclass
class PotentialResult:
    snapshot: dict | None
    pending: list
    attempt: dict
    evaluated: list = field(default_factory=list)
