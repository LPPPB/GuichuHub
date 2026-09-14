"""storage.cache 内存缓存失效测试。

背景：神评论跳转定位失败的根因——外部脚本直接改写 JSON 后，
运行中的后端 _data_cache 永不感知，一直返回旧数据（rpid 缺失）。
修复方案：get_data() 检查数据文件 mtime，变化则自动重载。
"""

import json
import os

import pytest

import storage.cache as cache


@pytest.fixture
def fresh_cache(monkeypatch, tmp_path):
    """每测试独立的临时数据文件 + 重置 cache 模块全局状态"""
    db_file = tmp_path / 'test_db.json'

    def _write(data):
        db_file.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')

    _write({'comments_gold': [{'rpid': 1}]})

    monkeypatch.setattr(cache, 'get_db_path', lambda: str(db_file))
    monkeypatch.setattr(cache, 'load_data', lambda: json.loads(db_file.read_text(encoding='utf-8')))
    def _update(mutator):
        data = json.loads(db_file.read_text(encoding='utf-8'))
        mutator(data)
        _write(data)
        return data

    monkeypatch.setattr(cache, 'update_data', _update)

    cache._data_cache = None
    cache._cache_mtime = None
    yield db_file, _write

    cache._data_cache = None
    cache._cache_mtime = None


def _bump_mtime(path, offset=10):
    """显式前移 mtime，避免文件系统时间精度导致的等值"""
    st = os.stat(str(path))
    os.utime(str(path), (st.st_atime, st.st_mtime + offset))


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


def test_reload_when_file_modified_externally(fresh_cache):
    """外部改写 JSON（mtime 变化）：get_data 自动重载，返回新数据"""
    db_file, _write = fresh_cache
    old = cache.get_data()
    assert old['comments_gold'][0]['rpid'] == 1

    # 外部脚本直接改写数据文件（rpid 补齐场景）
    _write({'comments_gold': [{'rpid': 315121232352}]})
    _bump_mtime(db_file)

    new = cache.get_data()
    assert new['comments_gold'][0]['rpid'] == 315121232352


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


def test_missing_file_returns_cached(fresh_cache):
    """文件被删除（getmtime 异常）：返回缓存数据而非崩溃"""
    db_file, _ = fresh_cache
    cached = cache.get_data()
    db_file.unlink()
    assert cache.get_data() is cached
