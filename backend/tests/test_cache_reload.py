"""storage.cache uses PostgreSQL state, never JSON file mtimes."""

import pytest

import storage.cache as cache


@pytest.fixture
def fresh_cache(monkeypatch):
    """Reset the in-process cache around a PostgreSQL-style state adapter."""
    data = {'comments_gold': [{'rpid': 1}]}
    version = [1]

    monkeypatch.setattr(cache, 'get_postgres_data_version', lambda: version[0])
    monkeypatch.setattr(cache, 'load_data_snapshot', lambda: (dict(data), version[0]))

    def _update(mutator):
        mutator(data)
        version[0] += 1
        return data

    monkeypatch.setattr(cache, 'update_data', _update)

    cache._data_cache = None
    cache._data_cache_version = None
    yield data, version

    cache._data_cache = None
    cache._data_cache_version = None


def test_cache_hit_when_file_unchanged(fresh_cache):
    """An unchanged PostgreSQL revision loads its snapshot only once."""
    calls = []
    orig_load = cache.load_data_snapshot
    monkey = pytest.MonkeyPatch()
    monkey.setattr(cache, 'load_data_snapshot', lambda: (calls.append(1), orig_load())[1])
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
    """A persisted PostgreSQL snapshot becomes the immediate cache value."""
    calls = []
    orig_load = cache.load_data_snapshot
    monkey = pytest.MonkeyPatch()
    monkey.setattr(cache, 'load_data_snapshot', lambda: (calls.append(1), orig_load())[1])
    try:
        result = cache.persist_data({'hot_videos': [{'title': 'v'}]})
        assert result['hot_videos'] == [{'title': 'v'}]
        assert cache.get_data() is result          # 落盘后立即命中内存缓存
        assert len(calls) == 1                     # 提交后读取一次新 revision 快照
    finally:
        monkey.undo()


def test_repeated_read_returns_cached_postgres_snapshot(fresh_cache):
    cached = cache.get_data()
    assert cache.get_data() is cached


def test_new_postgres_revision_refreshes_process_cache(fresh_cache):
    data, version = fresh_cache
    assert cache.get_data()['comments_gold'][0]['rpid'] == 1

    data['comments_gold'] = [{'rpid': 2}]
    version[0] += 1

    assert cache.get_data()['comments_gold'][0]['rpid'] == 2
