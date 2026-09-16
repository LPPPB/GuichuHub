"""storage.cache uses PostgreSQL state, never JSON file mtimes."""

import pytest

import storage.cache as cache


@pytest.fixture
def fresh_cache(monkeypatch):
    """Reset the in-process cache around a PostgreSQL-style state adapter."""
    data = {'comments_gold': [{'rpid': 1}]}

    monkeypatch.setattr(cache, 'load_data', lambda: dict(data))
    def _update(mutator):
        mutator(data)
        return data

    monkeypatch.setattr(cache, 'update_data', _update)

    cache._data_cache = None
    yield data

    cache._data_cache = None


def test_cache_hit_when_file_unchanged(fresh_cache):
    """文件未变化：get_data 只 load 一次（保持原有缓存性能）"""
    calls = []
    orig_load = cache.load_data
    monkey = pytest.MonkeyPatch()
    monkey.setattr(cache, 'load_data', lambda: (calls.append(1), orig_load())[1])
    try:
        cache.get_data()
        cache.get_data()
        cache.get_data()
        assert len(calls) == 1
    finally:
        monkey.undo()


def test_cache_module_has_no_json_file_mtime_dependency(fresh_cache):
    assert not hasattr(cache, '_current_mtime')
    assert cache.get_data()['comments_gold'][0]['rpid'] == 1


def test_persist_updates_cache_without_spurious_reload(fresh_cache):
    """persist_data 落盘后缓存即时生效，且下次 get_data 不触发重读"""
    calls = []
    orig_load = cache.load_data
    monkey = pytest.MonkeyPatch()
    monkey.setattr(cache, 'load_data', lambda: (calls.append(1), orig_load())[1])
    try:
        result = cache.persist_data({'hot_videos': [{'title': 'v'}]})
        assert result['hot_videos'] == [{'title': 'v'}]
        assert cache.get_data() is result          # 落盘后立即命中内存缓存
        assert len(calls) == 0                     # 持久化在锁内直接读磁盘快照，无缓存重读
    finally:
        monkey.undo()


def test_repeated_read_returns_cached_postgres_snapshot(fresh_cache):
    cached = cache.get_data()
    assert cache.get_data() is cached
