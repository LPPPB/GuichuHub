"""Process-local read-through caches backed by PostgreSQL dashboard state."""

import threading
from storage.database import (
    get_data_version as get_postgres_data_version,
    load_data_snapshot,
    update_data,
)

_data_cache = None
_data_cache_version = None
_data_lock = threading.RLock()


def get_data():
    """Read cached dashboard data, refreshing when another process commits a version."""
    global _data_cache, _data_cache_version
    with _data_lock:
        current_version = get_postgres_data_version()
        if _data_cache is not None and current_version == _data_cache_version:
            return _data_cache
        _data_cache, _data_cache_version = load_data_snapshot()
        return _data_cache


def get_data_version():
    """Return the cross-process PostgreSQL dashboard version."""
    return get_postgres_data_version()


def persist_data(new_data):
    """Merge new dashboard data while protecting non-empty sections."""
    global _data_cache, _data_cache_version
    from storage.repositories.collection_state import PROTECTED_KEYS
    if PROTECTED_KEYS.intersection(new_data):
        raise ValueError('Use source-specific snapshot publication')
    with _data_lock:
        def merge(current):
            for key, value in new_data.items():
                if value:
                    current[key] = value
                else:
                    print(f'  [警告] {key} 抓取为空，保留旧数据（可能限流）')

        update_data(merge)
        _data_cache, _data_cache_version = load_data_snapshot()
        current = _data_cache
        return current


# ─── 实时缓存层（手动抓取数据，不落库）─────────────────────────
# 设计依据：实时抓取数据只做即时展示，TTL 过期后回退到定时数据
#   - TTL = 10 分钟：足够用户查看，过期后自动回退避免显示过时"实时"数据
#   - 独立于 _data_cache：定时数据缓存不受实时缓存影响
#   - 20 分钟兜底清理：TTL 过期后变量仍占内存，用 threading.Timer 定时清空
#     彻底释放；反复刷新时取消旧 timer 重新计时，始终以最后一次刷新为起点
import time as _time

_LIVE_TTL_SECONDS = 600           # 10 分钟：逻辑过期（get_live_cache 返回 None）
_LIVE_CLEANUP_DELAY_SECONDS = 1200  # 20 分钟：物理清理（清空变量释放内存）
_live_cache = None                # {'data': {...}, 'cached_at': ts}
_live_cleanup_timer = None        # threading.Timer 实例（20 分钟后清空 _live_cache）


def set_live_cache(data):
    """写入实时缓存（手动抓取完成后调用）。

    同时调度 20 分钟后的兜底清理任务：TTL=10 分钟已让数据逻辑过期，
    但 _live_cache 变量仍占内存；20 分钟后主动清空，防止反复刷新内存堆积。
    反复刷新时取消旧 timer 重新计时，始终以最后一次刷新为起点。

    参数:
      data: 抓取到的看板数据（与 persist_data 入参同结构）
    """
    global _live_cache, _live_cleanup_timer
    with _data_lock:
        _live_cache = {
            'data': data,
            'cached_at': int(_time.time()),
        }
        # 取消旧的清理任务（反复刷新时以最新一次为起点重新计时）
        if _live_cleanup_timer is not None:
            _live_cleanup_timer.cancel()
        # 启动新的 20 分钟清理任务（daemon=True 进程退出不阻塞）
        _live_cleanup_timer = threading.Timer(
            _LIVE_CLEANUP_DELAY_SECONDS, invalidate_live_cache
        )
        _live_cleanup_timer.daemon = True
        _live_cleanup_timer.start()


def get_live_cache():
    """读取实时缓存，过期返回 None。

    返回: dict 或 None
      - 未过期: {'data': {...}, 'cached_at': ts, 'is_live': True}
      - 过期/不存在: None
    """
    with _data_lock:
        if not _live_cache:
            return None
        age = int(_time.time()) - _live_cache['cached_at']
        if age > _LIVE_TTL_SECONDS:
            return None  # 过期
        return {
            'data': _live_cache['data'],
            'cached_at': _live_cache['cached_at'],
            'is_live': True,
        }


def invalidate_live_cache():
    """清除实时缓存（手动抓取失败/20 分钟兜底清理时调用）

    同时取消待执行的清理 timer，避免 timer 重复触发无意义的清理。
    """
    global _live_cache, _live_cleanup_timer
    with _data_lock:
        _live_cache = None
        if _live_cleanup_timer is not None:
            _live_cleanup_timer.cancel()
            _live_cleanup_timer = None
