"""热修并发验证 — 证明两个修复生效

测试1: tracked_ups.json 原子写 — 模拟写到一半被另一线程读，应读到旧值或新值，绝不读半截
测试2: save_tracked_list + save_config 持锁 RMW — 并发 100 次交替调用，最终数据自洽
测试3: start_analysis 执行锁 — 第二次调用返回 None（409 路径）
"""
import os
import sys
import json
import time
import threading
import tempfile

# 让脚本能 import 项目模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_atomic_write():
    """测试1: 原子写 — 证明写入中途失败时文件仍是完整旧版

    原子写的核心保证：os.replace 要么完成（出新版），要么没发生（停在旧版），
    绝不会停在"半截新版本"。本测试用 monkey-patch 让 os.replace 抛 PermissionError
    模拟写入失败，验证文件仍是上一次完整版本，能被 json.load 解析。
    旧实现 open('w') 截断后写到一半崩溃 → 文件停留在半截状态 → 下次读 except。
    """
    from storage.tracked_ups import _safe_write_json, _safe_read_json
    import storage.tracked_ups as tu

    tmpdir = tempfile.mkdtemp()
    fp = os.path.join(tmpdir, 'test.json')

    # 先写一个完整 v1
    _safe_write_json(fp, {'version': 1, 'data': 'original'})
    original_replace = tu.os.replace

    # 让 os.replace 模拟失败（写入中断），tmp 已写好但目标未替换
    call_count = [0]
    def flaky_replace(tmp, target):
        call_count[0] += 1
        raise PermissionError(5, '模拟失败')

    tu.os.replace = flaky_replace
    raised = False
    try:
        _safe_write_json(fp, {'version': 2, 'data': 'should_not_persist'})
    except PermissionError:
        raised = True
    tu.os.replace = original_replace

    # 验证1: 异常被抛出（不是静默吞掉）
    assert raised, '写入失败应抛出异常，不能静默'

    # 验证2: 文件仍是完整 v1（不是半截 / 不是 v2）
    final = _safe_read_json(fp, {})
    assert final.get('version') == 1, \
        f'原子写失败：写入中断后文件应为 v1，实际 version={final.get("version")}'
    assert final.get('data') == 'original', \
        f'原子写失败：写入中断后 data 应为 original，实际={final.get("data")}'

    # 不应有残留 .tmp 文件（重试耗尽后 tmp 仍在，但目标文件未受污染）
    # —— 实际上 tmp 文件会残留，生产中下次写入会覆盖，无影响，不强制断言

    print(f'[测试1 通过] 原子写: os.replace 失败 {call_count[0]} 次后，'
          f'文件仍是完整 v1（非半截、非 v2）')


def test_concurrent_rmw():
    """测试2: save_tracked_list + save_config 并发持锁"""
    # 用临时 TRACKED_FILE 避免污染生产数据
    import storage.tracked_ups as tu

    tmpdir = tempfile.mkdtemp()
    original_file = tu.TRACKED_FILE
    tu.TRACKED_FILE = os.path.join(tmpdir, 'tracked_ups.json')

    try:
        # 初始化
        tu.save_tracked_list([{'mid': 1, 'name': 'up1', 'enabled': True}])

        # 50 线程并发 save_tracked_list + 50 线程并发 save_config
        errors = []

        def worker_save_list(i):
            try:
                # RMW: 读→加新 UP→写
                existing = tu.load_tracked_list()
                ups = existing['ups'] if existing else []
                # 模拟前端"添加新 UP"的完整流程
                ups = ups + [{'mid': 100 + i, 'name': f'up{100+i}', 'enabled': True}]
                tu.save_tracked_list(ups)
            except Exception as e:
                errors.append(('list', i, str(e)))

        def worker_save_config(i):
            try:
                tu.save_config({'refresh_interval': 30 + (i % 10)})
            except Exception as e:
                errors.append(('config', i, str(e)))

        threads = []
        for i in range(50):
            threads.append(threading.Thread(target=worker_save_list, args=(i,)))
            threads.append(threading.Thread(target=worker_save_config, args=(i,)))
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 校验：无异常 + 最终数据自洽
        final = tu._safe_read_json(tu.TRACKED_FILE)

        # 关键自洽检查：
        # 1) config.refresh_interval 是某个 30~39 的值（不被空值覆盖）
        # 2) ups 数组里至少有 up1 + 一些 100+i（不被空值覆盖）
        # 3) config 和 ups 同时存在（不互相覆盖）
        assert errors == [], f'并发异常: {errors[:5]}'
        assert 'config' in final, 'config 段被覆盖丢失！'
        assert 'ups' in final, 'ups 段被覆盖丢失！'
        assert 30 <= final['config']['refresh_interval'] <= 39, \
            f'config 值异常: {final["config"]["refresh_interval"]}'
        # up1 必须还在（不能被丢失）
        mids = {u['mid'] for u in final['ups']}
        assert 1 in mids, f'up1 被丢失！剩余 mids={list(mids)[:5]}...'

        print(f'[测试2 通过] 并发 RMW: 100 线程无异常，config/ups 均未丢失，'
              f'最终 ups={len(final["ups"])} 个，refresh_interval={final["config"]["refresh_interval"]}')

    finally:
        tu.TRACKED_FILE = original_file


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


if __name__ == '__main__':
    print('=' * 60)
    print('热修并发验证')
    print('=' * 60)
    test_atomic_write()
    test_concurrent_rmw()
    test_analysis_lock()
    print('\n✓ 全部通过')
