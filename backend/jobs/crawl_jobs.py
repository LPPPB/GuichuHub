"""调度层 — 全量抓取 + 轻量观测任务

设计依据（docs/架构演进实施检查清单.md）：
- 抓取互斥锁：定时任务与手动刷新不能并发（会互相覆盖）
- 抓取批次的观测与 dashboard 状态由 PostgreSQL 持久化
- A3 非空保护：某板块抓取被限流返回空时，保留旧数据
"""

import threading
import time

from storage.cache import get_data, persist_data
from storage import db as tsdb
from collectors import run_all_crawlers
from config import (OBSERVE_HOT_LIMIT, RETRY_DELAY_MINUTES, RETRY_MAX_ATTEMPTS,
                    RETRY_BACKOFF_BASE)
from logger import get_logger

logger = get_logger(__name__)

_crawl_lock = threading.Lock()
_crawl_status = {
    'crawling': False,
    'started_at': None,
    'last_finished_at': None,
    'last_error': None,
}


def get_status():
    """返回抓取状态快照（线程安全只读）"""
    return dict(_crawl_status)


def _get_rank_bvids():
    """当前榜单视频 bvid 列表（方案A：榜单视频强制纳入观测）。

    榜单 = 前端直接展示的视频集合（鬼畜榜 kichu_rank + 热门视频 hot_videos），
    来自最近一次全量抓取的 PostgreSQL dashboard state。无论 A4 分级如何，
    这些用户看得见的视频都必须保持高频观测，否则播放量折线图会停更。
    """
    try:
        data = get_data() or {}
        bvids = []
        for key in ('kichu_rank', 'hot_videos'):
            for item in data.get(key, []) or []:
                b = (item or {}).get('bvid')
                if b:
                    bvids.append(b)
        return bvids
    except Exception as e:
        logger.warning(f'[观测] 读取榜单 bvid 失败: {e}')
        return []


def try_acquire_lock():
    """尝试获取抓取锁。返回 True 表示成功（可以开始抓取），False 表示已有任务在跑。"""
    return _crawl_lock.acquire(blocking=False)


def mark_crawling():
    """锁已持有后，标记抓取状态为进行中（设置 started_at 供 _crawl_job_locked 写观测批次用）"""
    _crawl_status.update({
        'crawling': True,
        'started_at': int(time.time()),
        'last_error': None,
    })


def run_crawl_job(trigger='scheduled'):
    """全量抓取任务（scheduler 入口）：获取锁后同步执行，失败自动重试。

    HTTP 手动刷新入口见 refresh_data 路由（在请求线程先 acquire，再交工作线程执行）。
    定时触发失败后延迟 RETRY_DELAY_MINUTES 分钟重试，最多 RETRY_MAX_ATTEMPTS 次。
    """
    _run_with_retry(_crawl_once, trigger, RETRY_MAX_ATTEMPTS)


# 锁等待参数：全量抓取触发时若观测等短任务正在跑，等待其释放而非立即跳过。
# 观测任务通常 1-3 分钟完成，5 分钟超时足以覆盖；超时则抛异常走 _run_with_retry 重试。
_CRAWL_LOCK_WAIT_TIMEOUT = 300   # 秒
_CRAWL_LOCK_WAIT_INTERVAL = 5    # 秒


def _acquire_crawl_lock_with_wait():
    """带超时等待的锁获取，避免与短时观测任务冲突时静默跳过定时抓取。

    全量抓取触发时若观测任务正在跑，等待其释放（每 5 秒重试，最多 5 分钟）。
    返回 True 拿到锁，False 超时未拿到。
    """
    deadline = time.time() + _CRAWL_LOCK_WAIT_TIMEOUT
    while True:
        if _crawl_lock.acquire(blocking=False):
            return True
        if time.time() >= deadline:
            return False
        time.sleep(_CRAWL_LOCK_WAIT_INTERVAL)


def _crawl_once(trigger):
    """单次全量抓取（不含重试逻辑，由 run_crawl_job 包装）。

    失败时异常向上抛出，由 _run_with_retry 决定是否重试。
    _crawl_job_locked 内部 finally 会释放锁并重置 crawling 状态。

    锁冲突时短时等待（最多5分钟）而非立即跳过，避免观测任务偶发占用导致
    定时窗口被静默错过；等待超时则抛异常，由 _run_with_retry 在更长时间后重试。
    """
    # 登录态预检：未登录时 412 限流风险高，记日志但不阻断（降级为游客模式继续抓）
    try:
        from collectors.bilibili_auth import is_logged_in
        if not is_logged_in():
            logger.warning('[抓取] B站登录已过期或未登录，将以游客模式抓取（412 风险升高）')
    except Exception as e:
        logger.warning(f'[抓取] 登录态检测失败: {e}，继续以游客模式抓取')

    if not _acquire_crawl_lock_with_wait():
        msg = f'抓取锁等待超时（{_CRAWL_LOCK_WAIT_TIMEOUT}秒），已有任务长时间占用（触发源: {trigger}）'
        logger.warning(f'[抓取] {msg}')
        raise RuntimeError(msg)  # 抛异常让 _run_with_retry 延迟重试，不再静默跳过
    _crawl_status.update({
        'crawling': True,
        'started_at': int(time.time()),
        'last_error': None,
    })
    # _crawl_job_locked 内部 finally 释放锁；异常向上抛给 _run_with_retry
    _crawl_job_locked(trigger)
    return True


def _crawl_job_locked(trigger):
    """锁已持有时的抓取主流程（由 run_crawl_job / refresh_data 的工作线程调用）。

    观测和 dashboard 状态均通过 PostgreSQL repository 持久化。
    finally 释放锁——threading.Lock 允许跨线程 release（HTTP路径下锁在请求线程获取）。
    """
    print(f'[抓取] 开始（触发源: {trigger}）...')
    run_id = tsdb.begin_crawl_run(trigger)
    try:
        new_data = run_all_crawlers()
        all_videos = new_data.pop('_all_videos', [])

        # ── ① 写 PostgreSQL 时序层（B7: ts 用批次开始时刻，同批幂等）──
        # startup（应用启动预热）只刷新看板缓存，不写观测数据：record_video 是
        # "登记 + 写一次观测"的原子操作，startup 落库会与半小时轻量观测交错，
        # 产生"成对"数据点（开发期反复重启后端尤其明显）。观测由 scheduled
        # 全量抓取（03:00/15:00）与轻量观测任务（每30分钟）负责。
        if trigger == 'startup':
            tsdb.finish_crawl_run(run_id, 'success', {
                'mode': 'startup_no_obs',
                'videos_crawled': len(all_videos),
            })
            print(f'[时序库] startup 模式：跳过观测写入（{len(all_videos)} 视频仅刷新缓存）')
        else:
            ts = _crawl_status['started_at']
            try:
                for v in all_videos:
                    source = v.pop('_source', None) or 'unknown'
                    tsdb.record_video(v, ts, source)
                tsdb.record_words(new_data.get('danmaku_words', []), ts)
                # 候选池视频保持 hot 高频观测（A4）
                hot_bvids = [
                    v['bvid']
                    for v in new_data.get('hot_videos', []) + new_data.get('material_candidates', [])
                    if v.get('bvid')
                ]
                tsdb.mark_candidates_hot(hot_bvids)
                retired = tsdb.refresh_observe_tiers()
                tsdb.finish_crawl_run(run_id, 'success', {
                    'videos_recorded': len(all_videos),
                    'hot_marked': len(hot_bvids),
                    'retired_to_cold': retired,
                })
                print(f'[时序库] 登记 {len(all_videos)} 视频，{len(hot_bvids)} 候选标记hot，{retired} 视频退役cold')
            except Exception as e:
                tsdb.finish_crawl_run(run_id, 'failed', {'error': str(e)})
                raise

        # ── ② 观测写入成功后才更新 PostgreSQL dashboard state ──
        persist_data(new_data)
        _crawl_status['last_finished_at'] = int(time.time())
        print('[抓取] 完成')
    except Exception as e:
        _crawl_status['last_error'] = str(e)
        print(f'[抓取] 失败: {e}')
        # 无论成败都收尾 crawl_run，避免进程被杀/异常中断后残留 running 记录
        try:
            tsdb.finish_crawl_run(run_id, 'failed', {'error': str(e)[:200]})
        except Exception:
            pass
        raise  # 重新抛出，让上层 _run_with_retry 处理重试（HTTP 路径在自己的 try 中吞掉）
    finally:
        _crawl_status['crawling'] = False
        _crawl_lock.release()


def _crawl_job_live(trigger='manual'):
    """实时抓取主流程：抓取数据只更新内存缓存，不落库。

    与 _crawl_job_locked 的差异：
      - 不调 tsdb.record_video / record_words / mark_candidates_hot
      - 不调 persist_data（不更新持久 dashboard state）
      - 只调 set_live_cache 更新实时内存缓存
      - 共用 _crawl_lock，与定时抓取互斥

    用途：用户点"刷新"按钮时触发，数据仅供即时展示，TTL 过期后回退到定时数据。
    定时抓取仍走 _crawl_job_locked 落库，作为后续数据分析的事实源。

    参数:
      trigger: 触发源（'manual' / 'live'）
    """
    from storage.cache import set_live_cache, invalidate_live_cache

    print(f'[实时抓取] 开始（触发源: {trigger}）...')
    _crawl_status['started_at'] = int(time.time())
    try:
        new_data = run_all_crawlers()

        # A3 非空保护：某板块为空时不覆盖（复用 persist_data 的合并逻辑）
        # 但只更新实时缓存，不落盘
        merged = {}
        for key, value in new_data.items():
            if value:
                merged[key] = value
            else:
                print(f'  [警告] {key} 实时抓取为空，跳过该板块')

        # 写入实时缓存（不调 persist_data，不落库）
        set_live_cache(merged)
        _crawl_status['last_finished_at'] = int(time.time())
        print('[实时抓取] 完成（仅更新实时缓存，未落库）')

    except Exception as e:
        _crawl_status['last_error'] = str(e)
        invalidate_live_cache()  # 失败时清空实时缓存，回退到定时数据
        print(f'[实时抓取] 失败: {e}')
        raise
    finally:
        _crawl_status['crawling'] = False
        _crawl_lock.release()


def run_observe_job():
    """每小时轻量观测：只对 tier 命中的视频补 obs（view+online），不动 dashboard state。

    与全量抓取的差异：不发现新视频、不抓弹幕/评论，只记录已知视频的指标变化。
    观测对象由 A4 分级策略给出（hot每小时/warm每天/cold停测），成本有恒定上界。
    """
    from collectors.bilibili import fetch_video_detail, fetch_online_count, _online_breaker_open, _online_pacing
    if not _crawl_lock.acquire(blocking=False):
        print('[观测] 全量抓取进行中，跳过本轮')
        return
    try:
        targets = tsdb.get_observation_targets(hot_limit=OBSERVE_HOT_LIMIT)
        # 方案A：榜单视频（鬼畜榜/热门视频）强制纳入观测，无论 A4 分级如何。
        # 榜单 bvid 在前、去重保序，避免用户可见视频的折线图因分级降级而停更。
        ranked = _get_rank_bvids()
        if ranked:
            targets = list(dict.fromkeys(ranked + targets))
        if not targets:
            print('[观测] 无观测目标')
            return
        print(f'[观测] 开始，目标 {len(targets)} 个视频（hot_limit={OBSERVE_HOT_LIMIT}，含榜单 {len(ranked)} 个）...')
        ts = int(time.time())
        run_id = tsdb.begin_crawl_run('observe')
        observed = 0
        for bvid in targets:
            try:
                detail = fetch_video_detail(bvid)
                _online_pacing()
                if not detail:
                    continue
                stat = detail.get('stat', {})
                observed_at = int(time.time())
                cid = detail.get('cid')
                online = None
                online_precision = None
                if cid and not _online_breaker_open():
                    online, online_precision, online_display = fetch_online_count(bvid, cid)
                    _online_pacing()
                else:
                    online_display = None
                tsdb.record_obs(bvid, ts, {
                    'views': stat.get('view'),
                    'likes': stat.get('like'),
                    'coins': stat.get('coin'),
                    'favorites': stat.get('favorite'),
                    'shares': stat.get('share'),
                    'comments': stat.get('reply'),
                    'danmaku': stat.get('danmaku'),
                    'online_count': online,
                    'online_precision': online_precision,
                    'online_display': online_display,
                    'online_observed_at': int(time.time()) if online is not None else None,
                    'observed_at': observed_at,
                    'metrics_source': 'bilibili_stat' if all(stat.get(k) is not None for k in
                        ('view', 'like', 'coin', 'favorite', 'share', 'reply', 'danmaku')) else 'legacy_unknown',
                })
                observed += 1
            except Exception as e:
                print(f'  [观测] {bvid} 失败: {e}')
        retired = tsdb.refresh_observe_tiers()
        tsdb.finish_crawl_run(run_id, 'success', {
            'targets': len(targets), 'observed': observed, 'retired_to_cold': retired,
        })
        print(f'[观测] 完成: {observed}/{len(targets)} 条，{retired} 视频退役cold')
    except Exception as e:
        print(f'[观测] 失败: {e}')
    finally:
        _crawl_lock.release()


# ─── 调度层包装函数（供 scheduler.py 调用）─────────────────────────

def run_analysis_job(trigger='scheduled'):
    """UP 主动态分析的调度入口（定时任务调用）。

    从 PostgreSQL 读取 enabled UP 列表，调用 start_analysis 异步执行。
    start_analysis 内部有 _analysis_lock 互斥，与手动触发"刷新动态"按钮共用。
    """
    try:
        # 复用 tracked_ups.py 的 repository-backed 读取逻辑。
        from storage.tracked_ups import load_tracked_list
        tracked = load_tracked_list()
        if not tracked or not tracked.get('ups'):
            logger.warning('[UP分析] 名单为空，跳过本次分析')
            return False

        enabled_ups = [up for up in tracked['ups'] if up.get('enabled', True)]
        if not enabled_ups:
            logger.warning('[UP分析] 无启用的UP主，跳过本次分析')
            return False

        logger.info(f'[UP分析] 启动（trigger={trigger}, {len(enabled_ups)} UPs）')
        from jobs.up_trends_jobs import start_analysis
        task_id = start_analysis(enabled_ups, requested_by=f'system:{trigger}')

        if task_id is None:
            logger.info('[UP分析] 已有分析任务在跑，跳过')
            return False

        logger.info(f'[UP分析] 任务已启动 task_id={task_id}')
        return True
    except Exception as e:
        logger.error(f'[UP分析] 启动失败: {e}', exc_info=True)
        return False


def _run_with_retry(job_func, trigger, max_attempts):
    """通用失败重试包装。

    job_func 执行失败后，延迟 RETRY_DELAY_MINUTES 分钟重试，最多 max_attempts 次。
    重试期间 sleep 不占用 GIL（time.sleep 释放 GIL）。
    """
    import time as _time

    for attempt in range(1, max_attempts + 2):  # 1 次初始 + max_attempts 次重试
        try:
            job_func(trigger)
            if attempt > 1:
                logger.info(f'[重试] 第 {attempt-1} 次重试成功')
            return  # 成功则退出
        except Exception as e:
            if attempt <= max_attempts:
                logger.warning(f'[重试] 第 {attempt}/{max_attempts} 次失败: {e}，'
                             f'{RETRY_DELAY_MINUTES} 分钟后重试')
                _time.sleep(RETRY_DELAY_MINUTES * 60)
            else:
                logger.error(f'[重试] 已达上限 {max_attempts} 次，放弃: {e}', exc_info=True)


def fetch_with_backoff(fetch_func, *args, **kwargs):
    """412 限流指数退避包装（供 collectors 层调用）。

    捕获 HTTP 412 时按 RETRY_BACKOFF_BASE × 2^n 指数退避，最多 3 次。
    超过重试上限则返回 None，由调用方跳过该请求。

    用法：
        data = fetch_with_backoff(fetch_video_detail, bvid)
        if data is None:
            continue  # 跳过此视频
    """
    import time as _time

    for n in range(3):
        try:
            return fetch_func(*args, **kwargs)
        except Exception as e:
            # 检查是否为 412 限流（requests.HTTPError 或带 412 字样的异常）
            is_412 = ('412' in str(e) or 'Precondition' in str(e)
                      or (hasattr(e, 'response') and e.response is not None
                          and getattr(e.response, 'status_code', None) == 412))
            if not is_412:
                raise  # 非 412 异常直接抛出

            delay = RETRY_BACKOFF_BASE * (2 ** n)
            logger.warning(f'[412限流] 第 {n+1}/3 次退避 {delay:.1f}s: {e}')
            _time.sleep(delay)

    logger.warning(f'[412限流] 已达 3 次上限，跳过此请求')
    return None
