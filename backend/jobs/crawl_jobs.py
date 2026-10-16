"""调度层 — 全量抓取 + 轻量观测任务

设计依据（docs/架构演进实施检查清单.md）：
- 抓取互斥锁：定时任务与手动刷新不能并发（会互相覆盖）
- 抓取批次的观测与 dashboard 状态由 PostgreSQL 持久化
- A3 非空保护：某板块抓取被限流返回空时，保留旧数据
"""

import os
import time
from uuid import uuid4

from storage.cache import get_data, persist_data
from storage import db as tsdb
from collectors import run_all_crawlers
from config import (OBSERVE_HOT_LIMIT, RETRY_DELAY_MINUTES, RETRY_MAX_ATTEMPTS,
                    RETRY_BACKOFF_BASE)
from logger import get_logger

logger = get_logger(__name__)

from jobs.collection_lock import get_collection_lock, CollectionLockLost
from storage.repositories.collection_state import get_collection_repository
from config import load_collection_policy
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
    from services.collection_views import select_collection_views
    data=select_collection_views(get_data() or {},live=None,
        mode=load_collection_policy(os.environ).mode,now=int(time.time()))
    return list(dict.fromkeys(v['bvid'] for key in ('kichu_rank','hot_videos')
                             for v in data[key] if v.get('bvid')))


def try_acquire_lock(trigger='manual'):
    return get_collection_lock().try_acquire(trigger=trigger)


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
    返回原始 session guard，超时返回 None。
    """
    deadline = time.time() + _CRAWL_LOCK_WAIT_TIMEOUT
    while True:
        guard=try_acquire_lock('full')
        if guard is not None:
            return guard
        if time.time() >= deadline:
            return None
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

    guard=_acquire_crawl_lock_with_wait()
    if guard is None:
        msg = f'抓取锁等待超时（{_CRAWL_LOCK_WAIT_TIMEOUT}秒），已有任务长时间占用（触发源: {trigger}）'
        logger.warning(f'[抓取] {msg}')
        raise RuntimeError(msg)  # 抛异常让 _run_with_retry 延迟重试，不再静默跳过
    _crawl_status.update({
        'crawling': True,
        'started_at': int(time.time()),
        'last_error': None,
    })
    # _crawl_job_locked 内部 finally 释放锁；异常向上抛给 _run_with_retry
    _crawl_job_locked(trigger,guard=guard)
    return True


def _radar_observations_changed():
    from storage.repositories.radar import get_radar_repository
    from jobs.radar_jobs import run_radar_baseline_job
    repository = get_radar_repository()
    if repository is not None:
        repository.touch_observations(int(time.time()))
        try:
            run_radar_baseline_job()
        except Exception as error:
            logger.warning('雷达基线构建失败，保留明确不可用状态: %s', type(error).__name__)


def _collect_round():
    policy=load_collection_policy(os.environ)
    if policy.mode=='legacy':
        return run_all_crawlers()
    from collectors.bilibili import make_collection_context
    data=get_data() or {}
    prior=data.get('potential_v2_attempt') or {}
    context=make_collection_context(policy,int(time.time()),seed_cursor=prior.get('seed_cursor',0))
    return run_all_crawlers(context=context,official_snapshot=data.get('official_kichu_snapshot'),
                            pending=data.get('potential_pending'),mode=policy.mode)


def _crawl_job_locked(trigger,*,guard):
    records_written=0
    run_id=None
    mode=None
    attempt_identity=dict(attempt_id=uuid4().hex,started_at=int(time.time()),started_at_ns=time.time_ns())
    try:
        guard.assert_held()
        mode=load_collection_policy(os.environ).mode
        run_id=tsdb.begin_crawl_run(trigger)
        new_data=_collect_round()
        all_videos=new_data.pop('_all_videos',[])
        result=new_data.pop('_potential_result',None)
        if result is not None:
            result.attempt.update(attempt_identity)
            if result.snapshot is not None:
                result.snapshot['meta'].update(attempt_identity)
        summary=new_data.pop('_collection_summary',{})
        ts=_crawl_status.get('started_at') or int(time.time())
        business=tsdb.get_business_repository()
        from services.collection_contracts import STAT_KEYS,nonnegative_int
        for video in all_videos:
            guard.assert_held()
            row=dict(video)
            source=row.pop('_source',None) or 'unknown'
            preserve=row.pop('_preserve_tier',False)
            row.setdefault('first_seen',ts)
            # Reused official samples are metadata only. Never invent a fresh point.
            real=(row.get('metrics_source')=='bilibili_stat'
                  and all(nonnegative_int(row.get(k)) is not None for k in STAT_KEYS.values())
                  and ts<=row.get('observed_at',0)<=int(time.time()))
            if trigger=='startup' or (result is not None and not real):
                business.register_video_metadata({**row,'source':source},new_tier=row.get('observe_tier','warm'))
            elif preserve:
                business.record_video(row,ts=ts,source=source,preserve_tier=True)
                records_written+=1
            else:
                tsdb.record_video(row,ts,source)
                records_written+=1
        if trigger!='startup':
            guard.assert_held()
            tsdb.record_words(new_data.get('danmaku_words',[]),ts)
            tsdb.refresh_observe_tiers()
        guard.assert_held()
        if result is not None:
            get_collection_repository().publish_generation(new_data,result,guard=guard,
                mode=load_collection_policy(os.environ).mode)
        else:
            persist_data({k:v for k,v in new_data.items() if not k.startswith('_')})
        tsdb.finish_crawl_run(run_id,'success',dict(summary,mode='startup_no_obs' if trigger=='startup' else summary.get('mode','legacy'),
                                                  videos_registered=len(all_videos),videos_recorded=records_written))
        _crawl_status['last_finished_at']=int(time.time())
    except Exception as error:
        _crawl_status['last_error']=str(error)
        if mode in ('shadow','official'):
            from services.collection_contracts import PotentialResult
            failed=dict(attempt_identity,finished_at=int(time.time()),outcome='error',error_code='pipeline_exception')
            try:
                guard.assert_held()
                get_collection_repository().publish_generation({},PotentialResult(None,[],failed),guard=guard,mode=mode)
            except Exception as publication_error:
                logger.warning('Failed-attempt publication unavailable: %s',type(publication_error).__name__)
        if run_id is not None:
            try: tsdb.finish_crawl_run(run_id,'failed',{'error':type(error).__name__})
            except Exception: pass
        raise
    finally:
        if records_written:
            try: _radar_observations_changed()
            except Exception as error: logger.warning('Radar revision failed: %s',type(error).__name__)
        _crawl_status['crawling']=False
        guard.release()


def _crawl_job_live(trigger='manual',*,guard):
    from storage.cache import set_live_cache,invalidate_live_cache
    try:
        new_data=_collect_round()
        merged={k:v for k,v in new_data.items() if not k.startswith('_')
                and (v or k in ('potential_v2_snapshot','potential_v2_attempt'))}
        guard.assert_held()
        set_live_cache(merged)
        _crawl_status['last_finished_at']=int(time.time())
    except Exception as error:
        _crawl_status['last_error']=str(error)
        invalidate_live_cache()
        raise
    finally:
        _crawl_status['crawling']=False
        guard.release()


def run_observe_job():
    """每小时轻量观测：只对 tier 命中的视频补 obs（view+online），不动 dashboard state。

    与全量抓取的差异：不发现新视频、不抓弹幕/评论，只记录已知视频的指标变化。
    观测对象由 A4 分级策略给出（hot每小时/warm每天/cold停测），成本有恒定上界。
    """
    from collectors.bilibili import fetch_video_detail, fetch_online_count, _online_breaker_open, _online_pacing
    guard=try_acquire_lock('observe')
    if guard is None:
        print('[观测] 全量抓取进行中，跳过本轮')
        return
    try:
        targets = tsdb.get_observation_targets(hot_limit=OBSERVE_HOT_LIMIT)
        # 方案A：榜单视频（鬼畜榜/热门视频）强制纳入观测，无论 A4 分级如何。
        # 榜单 bvid 在前、去重保序，避免用户可见视频的折线图因分级降级而停更。
        ranked = _get_rank_bvids()
        from jobs.official_ranking_jobs import select_observation_targets
        targets = select_observation_targets(ranked,targets,limit=load_collection_policy(os.environ).observe_limit)
        # Shared hot-tier coverage can contain fewer than 200 eligible ghost
        # videos. A stable reference quota prevents a permanently empty baseline.
        # Reference-only targets need complete stats, not extra online requests.
        from storage.repositories.radar import get_radar_repository
        repository = get_radar_repository()
        reference_only = set()
        if repository is not None:
            try:
                references = repository.reference_observation_targets(int(time.time()))
                reference_only = set(references)-set(targets)
                targets = list(dict.fromkeys(targets+references))
            except Exception as error:
                logger.warning('雷达参考观测目标读取失败，保留常规观测: %s', type(error).__name__)
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
                if cid and bvid not in reference_only and not _online_breaker_open():
                    online, online_precision, online_display = fetch_online_count(bvid, cid)
                    _online_pacing()
                else:
                    online_display = None
                guard.assert_held()
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
            except CollectionLockLost:
                raise
            except Exception as e:
                print(f'  [观测] {bvid} 失败: {e}')
        if observed:
            _radar_observations_changed()
        retired = tsdb.refresh_observe_tiers()
        tsdb.finish_crawl_run(run_id, 'success', {
            'targets': len(targets), 'reference_only':len(reference_only), 'ordinary_targets':len(targets)-len(reference_only), 'observed': observed, 'retired_to_cold': retired,
        })
        print(f'[观测] 完成: {observed}/{len(targets)} 条，{retired} 视频退役cold')
    except Exception as e:
        print(f'[观测] 失败: {e}')
    finally:
        guard.release()


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
