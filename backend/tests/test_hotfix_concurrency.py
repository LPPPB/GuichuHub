"""Concurrency contracts for PostgreSQL tracked state and analysis jobs."""

import threading
import pytest


def test_tracked_roster_write_rolls_back_as_one_transaction(postgres_runtime):
    repository = postgres_runtime.state
    repository.save_tracked_list([{'mid': 1, 'name': 'original'}], 1)

    with pytest.raises(TypeError, match="not JSON serializable"):
        repository.save_tracked_list([
            {'mid': 2, 'name': 'would-be-partial'},
            {'mid': 3, 'name': object()},
        ], 2)

    assert [up['mid'] for up in repository.load_tracked_list()['ups']] == [1]


def test_concurrent_rmw(postgres_runtime):
    """Roster and config writes serialize without erasing each other's state."""
    import storage.tracked_ups as tu

    tu.save_tracked_list([{'mid': 1, 'name': 'up1', 'enabled': True}])

    errors = []

    def worker_save_list(i):
        try:
            existing = tu.load_tracked_list()
            ups = existing['ups'] if existing else []
            tu.save_tracked_list(
                ups + [{'mid': 100 + i, 'name': f'up{100+i}', 'enabled': True}],
            )
        except Exception as exc:
            errors.append(('list', i, str(exc)))

    def worker_save_config(i):
        try:
            tu.save_config({'refresh_interval': 30 + (i % 10)})
        except Exception as exc:
            errors.append(('config', i, str(exc)))

    threads = []
    for i in range(20):
        threads.append(threading.Thread(target=worker_save_list, args=(i,)))
        threads.append(threading.Thread(target=worker_save_config, args=(i,)))
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    final = tu.load_tracked_list()
    assert errors == []
    assert 30 <= final['config']['refresh_interval'] <= 39
    assert 1 in {up['mid'] for up in final['ups']}


def test_analysis_lock():
    """测试3: start_analysis 执行锁"""
    import jobs.up_trends_jobs as jobs

    # 先重置执行锁（防止其他测试残留）
    if jobs._analysis_lock.locked():
        jobs._analysis_lock.release()

    # 第一次手动 acquire 模拟"已有分析在跑"
    acquired = jobs._analysis_lock.acquire(blocking=False)
    assert acquired, '执行锁第一次 acquire 应该成功'

    try:
        # 此时 start_analysis 应该返回 None
        result = jobs.start_analysis([])
        assert result is None, f'执行锁未生效，第二次返回了 task_id={result}'

        print(f'[测试3 通过] 执行锁: 已有任务在跑时，start_analysis 返回 None（路由 → 409）')
    finally:
        jobs._analysis_lock.release()
