"""调度层 — UP主动态分析异步任务

管理后台分析任务的进度追踪和状态查询。

V3 架构：
  分析完成后写 PostgreSQL：up_obs（UP 维度）+ video_obs_snapshot（视频维度）。
  读路径完全走数据库，无文件依赖。
"""

import threading
import time
import uuid

from logger import get_logger
from storage.db import upsert_up_obs, upsert_video_obs_snapshot_batch

logger = get_logger(__name__)

_task_progress = {}
_task_lock = threading.Lock()

# 分析执行锁：同时只允许一个 UP 主动态分析任务运行。
# 历史：V1 无执行互斥，双击"刷新动态"会启动两条并发分析线程，导致数据竞争。
# 本锁非阻塞 acquire，已在跑则返回 None（路由层返回 409，前端接管在跑任务）。
_analysis_lock = threading.Lock()

# ─── _task_progress 内存泄漏修复 ───
# 原状态：_task_progress 字典只增不减，task_id 单调增长；done=True 的任务仍
# 保留（含 result 字段，单条可达几百 KB），长跑服务下缓慢内存泄漏。
# 修复：done=True 的任务在保留期内仍可查询（前端轮询拿 done），超期后被动 GC。
#   - KEEP_SECONDS = 300s（5 分钟）：前端轮询间隔 800ms，分析完到前端拿到结果
#     通常 < 2 秒，5 分钟足够兜底网络抖动/页面切后台
#   - KEEP_MAX_DONE = 5：上限保护，防止异常情况下大量已完成任务堆积
#   - GC 时机：start_analysis 入口 + get_progress 查询时被动触发，无需额外线程
KEEP_SECONDS = 300
KEEP_MAX_DONE = 5


def _gc_done_tasks(now=None):
    """清理已完成且超期的任务（必须在 _task_lock 内调用）。

    清理规则：
      1. done=True 且 finished_at 距今 > KEEP_SECONDS → 删除
      2. 删完仍超过 KEEP_MAX_DONE 条已完成任务 → 按_finished_at 升序删最旧的
      3. done=False 的正在跑任务永不清理
    """
    if not _task_progress:
        return
    now = now or int(time.time())

    # 规则1：超期清理
    expired = [
        tid for tid, p in _task_progress.items()
        if p.get('done') and p.get('finished_at', 0) < now - KEEP_SECONDS
    ]
    for tid in expired:
        _task_progress.pop(tid, None)

    # 规则2：上限保护（防异常堆积）
    done_items = [
        (tid, p.get('finished_at', 0))
        for tid, p in _task_progress.items()
        if p.get('done')
    ]
    if len(done_items) > KEEP_MAX_DONE:
        # 按 finished_at 升序，删除最旧的
        done_items.sort(key=lambda x: x[1])
        for tid, _ in done_items[:-KEEP_MAX_DONE]:
            _task_progress.pop(tid, None)


def start_analysis(enabled_ups):
    """启动 UP主分析后台任务，返回 task_id；若已有任务在跑则返回 None。"""
    # 非阻塞抢锁：抢不到说明已有分析在跑，路由层应返回 409
    if not _analysis_lock.acquire(blocking=False):
        return None

    task_id = uuid.uuid4().hex[:8]
    with _task_lock:
        # 入口被动 GC：每次启动新任务前清理上一轮已完成超期任务
        _gc_done_tasks()
        _task_progress[task_id] = {
            'total': len(enabled_ups),
            'current': 0,
            'current_up': '准备中...',
            'eta_seconds': len(enabled_ups) * 2,
            'done': False,
            'started_at': int(time.time()),
        }

    thread = threading.Thread(
        target=_run_analysis_async, args=(task_id, enabled_ups), daemon=True
    )
    thread.start()
    return task_id


def get_running_task_id():
    """返回当前正在跑的 task_id（用于 409 路径让前端接管轮询），无则 None。

    选取规则：最近一个 done=False 的任务。_task_progress 是 dict 无序，
    故按 started_at 倒序找最先命中的未完成任务。
    """
    with _task_lock:
        # 查询时顺手 GC（用户长期不刷新场景下也要清理）
        _gc_done_tasks()
        candidates = [
            (tid, p) for tid, p in _task_progress.items()
            if not p.get('done')
        ]
    if not candidates:
        return None
    # 按 started_at 倒序，取最新的
    candidates.sort(key=lambda x: x[1].get('started_at', 0), reverse=True)
    return candidates[0][0]


def get_progress(task_id):
    """查询分析任务进度"""
    with _task_lock:
        # 查询时顺手 GC（长跑服务下防止字典无限增长）
        _gc_done_tasks()
        return _task_progress.get(task_id)


def _run_analysis_async(task_id, enabled_ups):
    """在后台线程中执行分析，实时更新进度。

    执行锁在 finally 里释放，确保任何异常路径都不会泄漏（否则会永久卡死后续分析）。
    """
    try:
        total = len(enabled_ups)
        started_at = time.time()

        def progress_cb(idx, up_name):
            now = time.time()
            elapsed = now - started_at
            rate = (idx + 1) / elapsed if elapsed > 0 else 0.05
            eta = (total - idx - 1) / rate if rate > 0 else 0
            with _task_lock:
                _task_progress[task_id] = {
                    'total': total,
                    'current': idx + 1,
                    'current_up': up_name,
                    'eta_seconds': int(eta),
                    'done': False,
                    'started_at': int(started_at),
                }

        from collectors.bilibili_user import analyze_tracked_ups_with_progress
        result = analyze_tracked_ups_with_progress(enabled_ups, progress_cb)

        if result.get('error'):
            with _task_lock:
                _task_progress[task_id] = {
                    'done': True,
                    'error': result.get('message', '分析失败'),
                    'finished_at': int(time.time()),
                    'started_at': int(started_at),
                }
            return

        analysis = result.get('analysis', {})
        up_trends_data = result.get('up_trends', [])

        # ── V2 双写：up_obs（UP 维度）→ video_obs_snapshot（视频维度）──
        # 顺序设计依据：两表事务独立，各自原子
        #   - up_obs 写成功 + video_obs_snapshot 写失败：UP 维度有数据，视频维度缺（重试幂等）
        #   - up_obs 写失败 + video_obs_snapshot 写成功：用户重试即可
        #   - 任何 DB 部分写入后崩溃：各自事务独立回滚，不留半截
        # 整批 ts = 当前时刻（与分析开始时刻对齐，便于跨表 JOIN）
        batch_ts = int(time.time())

        # 1. up_obs 写入（UP 维度，整批事务原子）
        try:
            written = upsert_up_obs(
                ts=batch_ts,
                up_list=up_trends_data,
                play_ranking=analysis.get('play_ranking'),
                active_ranking=analysis.get('creator_ranking'),
            )
            logger.info(f'up_obs 写入成功: {written} 行 (ts={batch_ts})')
            result['up_obs_ts'] = batch_ts      # 透传给前端/对账用
            result['up_obs_rows'] = written
        except Exception as e:
            # up_obs 写失败：记日志，继续 video_obs_snapshot 写入（不阻塞主流程）
            # 读路径走 up_obs，失败会导致本轮分析数据缺失，用户重试即可
            logger.error(f'up_obs 写入失败（video_obs_snapshot 仍会写入）: {e}', exc_info=True)
            result['up_obs_error'] = str(e)

        # 2. video_obs_snapshot 写入（视频/文本维度，单事务原子）
        # 阶段 4 新增：承接 timeline / hot_videos / content_types / keyword_cloud
        # 2026-08-03 追加 pool_summary：近7天去重视频池的总播放/视频数/平均播放（联合投稿只计一次）
        try:
            _summary = analysis.get('summary', {})
            video_fields = {
                'timeline': analysis.get('timeline', []),
                'hot_videos': analysis.get('hot_videos', []),
                'all_videos': analysis.get('all_videos', []),
                'content_types': analysis.get('content_types', []),
                'keyword_cloud': analysis.get('keyword_cloud', []),
                # 视频池求和（analyze_tracked_ups_with_progress 内 sum(views for v in filtered_videos)）：
                # 总播放量唯一真源，读层用它覆盖 up_obs 的 UP 聚合口径
                'pool_summary': {
                    'total_views': _summary.get('total_views', 0),
                    'total_videos': _summary.get('total_videos', 0),
                    'avg_views_per_video': _summary.get('avg_views_per_video', 0),
                },
            }
            video_written = upsert_video_obs_snapshot_batch(batch_ts, video_fields)
            logger.info(f'video_obs_snapshot 写入成功: {video_written} 字段 (ts={batch_ts})')
            result['video_obs_snapshot_ts'] = batch_ts
            result['video_obs_snapshot_fields'] = video_written
        except Exception as e:
            # video_obs_snapshot 写失败：记日志（不阻塞主流程）
            # 读路径走该表，失败会导致视频维度数据缺失，用户重试即可
            logger.error(f'video_obs_snapshot 写入失败: {e}', exc_info=True)
            result['video_obs_snapshot_error'] = str(e)

        # 3. 分析完成只负责投递轻量增量任务；持久化 worker 串行执行并保留进度。
        # 与独立定时任务使用相同 dedupe_key，避免短时间重复扫描。
        try:
            from jobs.calendar_jobs import enqueue_calendar_job
            calendar_job, created = enqueue_calendar_job(
                mode='recent', days=7, requested_by='system:analysis',
                reason='UP 主动态分析完成', dedupe_key='recent:7:all',
                dedupe_window_seconds=30 * 60,
            )
            logger.info('日历增量任务%s: %s', '已创建' if created else '已复用', calendar_job['id'])
            result['calendar_job_id'] = calendar_job['id']
        except Exception as e:
            logger.error(f'日历增量任务创建失败: {e}', exc_info=True)
            result['calendar_job_error'] = str(e)

        with _task_lock:
            _task_progress[task_id] = {
                'done': True,
                'total': total,
                'current': total,
                'eta_seconds': 0,
                'result': result,
                'up_obs_ts': batch_ts,
                'video_obs_snapshot_ts': batch_ts,
                'started_at': int(started_at),
                'finished_at': int(time.time()),
            }
    except Exception as e:
        with _task_lock:
            _task_progress[task_id] = {
                'done': True,
                'error': str(e),
                'started_at': int(started_at) if 'started_at' in locals() else int(time.time()),
                'finished_at': int(time.time()),
            }
    finally:
        # 任何路径（成功/失败/异常）都释放执行锁，否则后续分析永久卡死
        _analysis_lock.release()
