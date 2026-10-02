"""PostgreSQL-backed calendar job queue and in-process worker orchestration."""
import hashlib
import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone, timedelta

from logger import get_logger
from storage.db import get_business_repository
from storage.tracked_ups import load_tracked_list
from storage.repositories.business import CalendarSubmissionCooldown

logger = get_logger(__name__)
CN_TZ = timezone(timedelta(hours=8))

LEASE_SECONDS = 120
POLL_SECONDS = 2
_worker_guard = threading.Lock()
_worker_thread = None


def _enabled_ups(mids=None):
    tracked = load_tracked_list() or {}
    entries = tracked.get('ups', [])
    by_mid = {}
    for up in entries:
        try:
            by_mid[int(up.get('mid'))] = up
        except (TypeError, ValueError):
            continue
    if mids is None:
        selected = [u for u in by_mid.values() if u.get('enabled', True)]
    else:
        selected = []
        for raw_mid in mids:
            try:
                mid = int(raw_mid)
            except (TypeError, ValueError):
                continue
            up = by_mid.get(mid) or {'mid': mid, 'name': f'UID:{mid}', 'enabled': True}
            selected.append(up)
    # 保持顺序同时去重。
    result = []
    seen = set()
    for up in selected:
        mid = int(up['mid'])
        if mid <= 0 or mid in seen:
            continue
        seen.add(mid)
        result.append({'mid': mid, 'name': up.get('name') or f'UID:{mid}'})
    return result


def _repository():
    repository = get_business_repository()
    if repository is None:
        raise RuntimeError('PostgreSQL business repository is not configured')
    return repository


def get_calendar_job(job_id, include_items=True):
    return _repository().calendar_job(job_id, include_items=include_items)


def get_active_calendar_job():
    return _repository().active_calendar_job()


def enqueue_calendar_job(mode='recent', days=None, year=None, mids=None,
                         requested_by='system', reason='', dedupe_key=None,
                         dedupe_window_seconds=0, parent_job_id=None,
                         dedupe_forever=False, cooldown_seconds=0):
    """只提交持久化任务；消费者仅由 Worker 入口启动。返回 (job, created)。"""
    if mode not in ('recent', 'year'):
        raise ValueError('mode 必须为 recent 或 year')
    if mode == 'recent':
        days = int(days or 7)
        if days <= 0 or days > 90:
            raise ValueError('recent days 必须在 1-90 之间')
        year = None
    else:
        year = int(year or datetime.now(CN_TZ).year)
        current_year = datetime.now(CN_TZ).year
        if year < 2009 or year > current_year + 1:
            raise ValueError('year 超出允许范围')
        days = None

    ups = _enabled_ups(mids)
    now = int(time.time())
    job, created = _repository().enqueue_calendar_job(
        mode, ups, now, days=days, year=year, requested_by=requested_by,
        reason=reason, dedupe_key=dedupe_key,
        dedupe_window_seconds=dedupe_window_seconds,
        parent_job_id=parent_job_id, dedupe_forever=dedupe_forever,
        cooldown_seconds=cooldown_seconds,
    )
    return job, created


def enqueue_manual_calendar_job(mode='recent', days=None, year=None, mids=None,
                                requested_by='system', reason='管理员手动刷新',
                                parent_job_id=None):
    # Repository serializes and normalizes the effective scope (including UP IDs).
    return enqueue_calendar_job(mode=mode, days=days, year=year, mids=mids,
                                requested_by=requested_by, reason=reason,
                                parent_job_id=parent_job_id, cooldown_seconds=60)


def enqueue_baseline_jobs(mids, requested_by='system', reason='新增或重新启用 UP'):
    """按配置起始年份到当前年份，为指定 UP 建立基线任务。"""
    from config import CALENDAR_START_YEAR

    mids = sorted({int(mid) for mid in mids if int(mid) > 0})
    if not mids:
        return []
    digest = hashlib.sha1(','.join(map(str, mids)).encode('utf-8')).hexdigest()[:10]
    current_year = datetime.now(CN_TZ).year
    jobs = []
    for year in range(min(int(CALENDAR_START_YEAR), current_year), current_year + 1):
        job, _ = enqueue_calendar_job(
            mode='year', year=year, mids=mids, requested_by=requested_by,
            reason=reason, dedupe_key=f'baseline:{year}:{digest}',
        )
        jobs.append(job)
    return jobs


def retry_calendar_job(job_id, requested_by='system'):
    source = get_calendar_job(job_id)
    if not source:
        return None, False
    failed_mids = [
        item['mid'] for item in source.get('items', [])
        if item['status'] in ('failed', 'partial')
    ]
    if not failed_mids:
        return source, False
    return enqueue_manual_calendar_job(
        mode=source['mode'], year=source.get('year'), days=source.get('days'),
        mids=failed_mids, requested_by=requested_by,
        reason=f"重试任务 {job_id}", parent_job_id=job_id,
    )


def _claim_next_job(worker_id):
    now = int(time.time())
    return _repository().claim_calendar_job(worker_id, now, LEASE_SECONDS)


def _update_item(job_id, event, worker_id):
    now = int(time.time())
    _repository().update_calendar_job_item(job_id, event, worker_id, now, LEASE_SECONDS)


def _finish_job(job_id, status, error_summary=''):
    now = int(time.time())
    _repository().finish_calendar_job(job_id, status, now, error_summary)


def _fail_unstarted_items(job_id, code, message):
    now = int(time.time())
    _repository().fail_calendar_job_items(job_id, code, message, now)


def _execute_job(job, worker_id):
    job_id = job['id']
    from collectors.bilibili_auth import get_cookie_str
    from collectors.calendar_backfill import backfill_calendar

    # 采集 Cookie 与访问本接口的管理员身份相互独立；任务执行前明确校验。
    if not get_cookie_str():
        message = '服务器采集账号未登录，无法请求 B 站 WBI 投稿接口'
        _fail_unstarted_items(job_id, 'collector_auth_missing', message)
        _finish_job(job_id, 'failed', message)
        return

    mids = [item['mid'] for item in job.get('items', [])]
    try:
        result = backfill_calendar(
            mids=mids,
            recent_days=job.get('days') if job['mode'] == 'recent' else None,
            year=job.get('year'),
            progress_callback=lambda event: _update_item(job_id, event, worker_id),
        )
        errors = result.get('errors', [])
        summary = '; '.join(
            f"{e.get('mid')}:{e.get('code')}" for e in errors[:10]
        )
        _finish_job(job_id, result.get('status', 'failed'), summary)
    except Exception as exc:
        logger.error('日历任务 %s 执行失败: %s', job_id, exc, exc_info=True)
        permission_error = getattr(getattr(exc, 'orig', None), 'sqlstate', None) == '42501'
        code = 'database_permission_denied' if permission_error else 'job_error'
        message = 'Worker 数据库权限异常，请检查部署配置' if permission_error else '日历任务执行失败，请检查 Worker 日志后重试'
        _fail_unstarted_items(job_id, code, message)
        _finish_job(job_id, 'failed', message)


def _worker_loop():
    worker_id = f'{os.getpid()}-{uuid.uuid4().hex[:8]}'
    logger.info('日历回填 worker 已启动: %s', worker_id)
    while True:
        try:
            job = _claim_next_job(worker_id)
            if job:
                _execute_job(job, worker_id)
                continue
        except Exception as exc:
            logger.error('日历 worker 循环异常: %s', exc, exc_info=True)
        time.sleep(POLL_SECONDS)


def ensure_calendar_worker():
    global _worker_thread
    with _worker_guard:
        if _worker_thread and _worker_thread.is_alive():
            return _worker_thread
        _worker_thread = threading.Thread(
            target=_worker_loop, name='calendar-backfill-worker', daemon=True,
        )
        _worker_thread.start()
        return _worker_thread

