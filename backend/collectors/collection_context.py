"""Round-local budgets and memoization. No cache survives a crawl retry."""
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import requests

_ACTIVE = ContextVar('collection_round', default=None)
_KIND = ContextVar('collection_request_kind', default='derived')


@dataclass
class SourceResult:
    value: object = None
    outcome: str = 'success'
    error_code: str | None = None
    observed_at: int | None = None


class RoundContext:
    def __init__(self, policy, *, loaders, now, clock=None):
        self.policy, self.loaders, self.now = policy, loaders, now
        self.clock = clock or (lambda:now)
        self._cache = {}
        self._counts = {name: Counter() for name in ('logical','http_attempts','cache_hits','skipped')}
        self.events = []

    @contextmanager
    def activate(self):
        token = _ACTIVE.set(self)
        try:
            yield self
        finally:
            _ACTIVE.reset(token)

    def record_http_attempt(self, kind):
        self._counts['http_attempts'][kind] += 1

    def summary(self):
        return {key: dict(value) for key, value in self._counts.items()}

    def fetch_once(self, kind, key, loader):
        cache_key = (kind,key)
        if cache_key in self._cache:
            self._counts['cache_hits'][kind] += 1
            return self._cache[cache_key]
        limits = {'discovery':self.policy.discovery_limit,'detail':self.policy.detail_limit,
                  'tags':self.policy.tag_limit,'online':self.policy.online_limit}
        if self._counts['logical'][kind] >= limits.get(kind,float('inf')):
            self._counts['skipped'][kind] += 1
            result = SourceResult(outcome='budget',error_code='budget')
        else:
            self._counts['logical'][kind] += 1
            token = _KIND.set(kind)
            try:
                with self.activate():
                    value = loader()
                    result = value if isinstance(value,SourceResult) else SourceResult(value)
                    if result.outcome == 'success' and result.observed_at is None:
                        result.observed_at = int(self.clock())
            except requests.RequestException:
                result = SourceResult(outcome='error',error_code='network')
            finally:
                _KIND.reset(token)
        self._cache[cache_key] = result
        self.events.append({'kind':kind,'outcome':result.outcome,'key':key})
        return result

    def call(self, name, *args, kind='discovery'):
        def load():
            loader = self.loaders.get(name)
            return loader(*args) if callable(loader) else SourceResult(outcome='error',error_code='missing_loader')
        return self.fetch_once(kind,(name,*args),load)


def record_http_attempt():
    context = _ACTIVE.get()
    if context is not None:
        context.record_http_attempt(_KIND.get())
