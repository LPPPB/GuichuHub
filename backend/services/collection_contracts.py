"""Versioned collection values; no HTTP or database work at import time."""
from dataclasses import dataclass, field
from typing import Literal

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
