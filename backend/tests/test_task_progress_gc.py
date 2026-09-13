"""_task_progress 内存泄漏修复验证

测试4个场景：
1. 超期已完成任务被 GC
2. 保留期内的已完成任务保留（前端轮询能拿到 done）
3. 正在跑的任务（done=False）永不清理
4. KEEP_MAX_DONE 上限保护（异常堆积时强制裁剪到上限）
5. GC 在 get_progress 查询时也触发（长跑不刷新场景）
"""
import os
import sys
import time
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def reset_state():
    """每个测试前重置模块全局状态"""
    import jobs.up_trends_jobs as jobs
    # 释放可能持有的锁
    if jobs._analysis_lock.locked():
        jobs._analysis_lock.release()
    with jobs._task_lock:
        jobs._task_progress.clear()


def test_gc_expired_done():
    """测试1: 超期已完成任务被 GC"""
    import jobs.up_trends_jobs as jobs
    reset_state()

    now = int(time.time())
    with jobs._task_lock:
        # 1 个超期已完成 + 1 个新近已完成 + 1 个未完成
        jobs._task_progress['old_done'] = {
            'done': True,
            'started_at': now - 1000,
            'finished_at': now - 1000,  # 已超期（>300s）
        }
        jobs._task_progress['fresh_done'] = {
            'done': True,
            'started_at': now - 10,
            'finished_at': now - 10,    # 保留期内
        }
        jobs._task_progress['running'] = {
            'done': False,
            'started_at': now - 5,
        }
        jobs._gc_done_tasks(now)

    assert 'old_done' not in jobs._task_progress, '超期已完成任务未被清理'
    assert 'fresh_done' in jobs._task_progress, '保留期内已完成任务被误删'
    assert 'running' in jobs._task_progress, '未完成任务被误删'

    print(f'[测试1 通过] GC 超期: old_done 已清理，fresh_done + running 保留')


def test_gc_keep_within_window():
    """测试2: 保留期内的已完成任务可被 get_progress 取到（前端轮询能拿 done）"""
    import jobs.up_trends_jobs as jobs
    reset_state()

    now = int(time.time())
    with jobs._task_lock:
        jobs._task_progress['recent'] = {
            'done': True,
            'result': {'analysis': {'summary': {'total_ups': 139}}},
            'started_at': now - 30,
            'finished_at': now - 30,   # 30 秒前完成，保留期内
        }
    # get_progress 内部会触发 GC，然后返回任务
    p = jobs.get_progress('recent')
    assert p is not None, '保留期内已完成任务应能被 get_progress 取到'
    assert p['done'] is True
    assert p['result']['analysis']['summary']['total_ups'] == 139

    print(f'[测试2 通过] 保留期: 30s 前完成的任务仍可查询，前端轮询能拿到 done')


def test_gc_never_clean_running():
    """测试3: 正在跑的任务（done=False）永不清理，即使时间很老"""
    import jobs.up_trends_jobs as jobs
    reset_state()

    now = int(time.time())
    with jobs._task_lock:
        # 一个跑了很久但还没完成的任务（极端：1 小时前启动）
        jobs._task_progress['long_running'] = {
            'done': False,
            'started_at': now - 3600,  # 1 小时前
            'total': 200,
            'current': 50,
        }
        # 加几个超期的已完成任务，触发 GC
        for i in range(3):
            jobs._task_progress[f'expired_{i}'] = {
                'done': True,
                'finished_at': now - 1000,
            }
        jobs._gc_done_tasks(now)

    assert 'long_running' in jobs._task_progress, '正在跑的任务被误删！'
    for i in range(3):
        assert f'expired_{i}' not in jobs._task_progress, f'超期任务 expired_{i} 未被清理'

    print(f'[测试3 通过] 正在跑保护: 1 小时前启动的 running 任务未被清理')


def test_gc_max_done_cap():
    """测试4: KEEP_MAX_DONE 上限保护 — 异常堆积时强制裁剪到上限"""
    import jobs.up_trends_jobs as jobs
    reset_state()

    now = int(time.time())
    with jobs._task_lock:
        # 灌 10 条已完成任务（都在保留期内，但超过 KEEP_MAX_DONE=5）
        for i in range(10):
            jobs._task_progress[f'done_{i}'] = {
                'done': True,
                'finished_at': now - i * 10,  # 0/10/20...90s 前
                'started_at': now - i * 10 - 5,
            }
        jobs._gc_done_tasks(now)

    done_remaining = [k for k in jobs._task_progress.keys() if k.startswith('done_')]
    assert len(done_remaining) == jobs.KEEP_MAX_DONE, \
        f'已完成任务应裁剪到 {jobs.KEEP_MAX_DONE} 条，实际 {len(done_remaining)} 条'
    # 应保留 finished_at 最新的 5 条（即 done_0..done_4）
    expected = {f'done_{i}' for i in range(5)}
    assert set(done_remaining) == expected, \
        f'应保留最新 5 条，实际保留 {sorted(done_remaining)}'

    print(f'[测试4 通过] 上限保护: 10 条已完成 → 裁剪到 {jobs.KEEP_MAX_DONE} 条，保留最新')


def test_gc_on_get_progress():
    """测试5: get_progress 查询时也触发 GC（用户长期不刷新场景）"""
    import jobs.up_trends_jobs as jobs
    reset_state()

    now = int(time.time())
    with jobs._task_lock:
        # 灌一个超期已完成任务
        jobs._task_progress['very_old'] = {
            'done': True,
            'finished_at': now - 10000,
        }
        # 灌一个保留期内的已完成任务
        jobs._task_progress['recent'] = {
            'done': True,
            'finished_at': now - 10,
        }
    # 不调用 start_analysis，仅查询 — GC 应在 get_progress 内触发
    jobs.get_progress('recent')

    with jobs._task_lock:
        assert 'very_old' not in jobs._task_progress, '查询时未触发 GC，超期任务残留'
        assert 'recent' in jobs._task_progress, '查询时 GC 误删保留期任务'

    print(f'[测试5 通过] 查询触发 GC: 长期不刷新场景下超期任务也会被清理')


def test_no_leak_under_repeated_starts():
    """测试6: 模拟长跑服务下连续启动 20 个任务（执行锁串行），验证不会无限增长

    场景：用户每次分析完几分钟后再次手动刷新，连续 20 次。
    旧实现：_task_progress 会累积 20 条 done 任务。
    新实现：GC 在 start_analysis 入口触发，每次启动前清理超期任务。
    为快速验证，临时把 KEEP_SECONDS 调小。
    """
    import jobs.up_trends_jobs as jobs
    reset_state()

    # 临时调小保留期，让超期清理在测试里立即可触发
    original_keep = jobs.KEEP_SECONDS
    jobs.KEEP_SECONDS = 0  # 立即超期

    try:
        # 手动模拟"启动→完成"的循环（不真跑分析，直接构造 done 状态）
        for i in range(20):
            with jobs._task_lock:
                tid = f'task_{i}'
                jobs._task_progress[tid] = {
                    'done': True,
                    'finished_at': int(time.time()) - 1,  # 1 秒前完成（已超期）
                    'started_at': int(time.time()) - 2,
                    'result': {'big': 'x' * 10000},  # 模拟大 result
                }
            # 模拟下一次 start_analysis 入口的 GC
            with jobs._task_lock:
                jobs._gc_done_tasks()

        # 20 轮后，由于 KEEP_SECONDS=0，每次 GC 都会清掉上一轮的 done 任务
        # 加上 KEEP_MAX_DONE=5 上限保护，最终 done 任务 ≤ 5
        done_count = sum(1 for p in jobs._task_progress.values() if p.get('done'))
        assert done_count <= jobs.KEEP_MAX_DONE, \
            f'连续 20 次启动后 done 任务 {done_count} 条，应 ≤ {jobs.KEEP_MAX_DONE}'

        print(f'[测试6 通过] 长跑防泄漏: 连续 20 次任务后 done 任务 = {done_count} 条 '
              f'(≤ {jobs.KEEP_MAX_DONE})')
    finally:
        jobs.KEEP_SECONDS = original_keep


if __name__ == '__main__':
    print('=' * 60)
    print('_task_progress 内存泄漏修复验证')
    print('=' * 60)
    test_gc_expired_done()
    test_gc_keep_within_window()
    test_gc_never_clean_running()
    test_gc_max_done_cap()
    test_gc_on_get_progress()
    test_no_leak_under_repeated_starts()
    print('\n✓ 全部通过')
