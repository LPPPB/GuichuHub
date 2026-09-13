"""发布日历持久化任务队列。

SQLite 负责排队、进度和租约；进程内线程只负责消费。多个 Web 进程可以同时
启动 worker，但 BEGIN IMMEDIATE + 全局运行租约保证同一时刻只有一个回填任务。
"""
import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone, timedelta

from logger import get_logger
from storage.db import get_conn, _write_lock
from storage.tracked_ups import load_tracked_list

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


def _row_dict(row):
    if not row:
        return None
    data = dict(row)
    for key in ('total_ups', 'processed_ups', 'succeeded_ups', 'empty_ups',
                'failed_ups', 'partial_ups', 'total_videos'):
        data[key] = int(data.get(key) or 0)
    total = data['total_ups']
    data['progress_percent'] = round(data['processed_ups'] * 100 / total) if total else 100
    return data


def get_calendar_job(job_id, include_items=True):
    conn = get_conn()
    row = conn.execute('SELECT * FROM calendar_backfill_jobs WHERE id=?', (job_id,)).fetchone()
    data = _row_dict(row)
    if not data:
        return None
    if include_items:
        items = conn.execute('''
            SELECT mid, name, status, pages, videos, attempts,
                   error_code, error_message, started_at, finished_at
            FROM calendar_backfill_job_items
            WHERE job_id=? ORDER BY rowid
        ''', (job_id,)).fetchall()
        data['items'] = [dict(item) for item in items]
    return data


def get_active_calendar_job():
    row = get_conn().execute('''
        SELECT * FROM calendar_backfill_jobs
        WHERE status IN ('running', 'queued')
        ORDER BY CASE status WHEN 'running' THEN 0 ELSE 1 END, created_at
        LIMIT 1
    ''').fetchone()
    return _row_dict(row)


def enqueue_calendar_job(mode='recent', days=None, year=None, mids=None,
                         requested_by='system', reason='', dedupe_key=None,
                         dedupe_window_seconds=0):
    """创建回填任务并唤醒 worker；返回 (job, created)。"""
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
    job_id = uuid.uuid4().hex[:16]
    with _write_lock:
        conn = get_conn()
        if dedupe_key:
            existing = conn.execute('''
                SELECT id FROM calendar_backfill_jobs
                WHERE dedupe_key=? AND (
                    status IN ('queued', 'running') OR created_at>=?
                ) ORDER BY created_at DESC LIMIT 1
            ''', (dedupe_key, now - max(0, int(dedupe_window_seconds)))).fetchone()
            if existing:
                return get_calendar_job(existing['id']), False
        status = 'queued' if ups else 'succeeded'
        finished_at = None if ups else now
        try:
            conn.execute('''
                INSERT INTO calendar_backfill_jobs
                (id, mode, year, days, status, reason, requested_by, dedupe_key,
                 total_ups, created_at, finished_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ''', (job_id, mode, year, days, status, reason, requested_by,
                  dedupe_key, len(ups), now, finished_at, now))
            conn.executemany('''
                INSERT INTO calendar_backfill_job_items (job_id, mid, name)
                VALUES (?,?,?)
            ''', [(job_id, up['mid'], up['name']) for up in ups])
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
            existing = conn.execute('''
                SELECT id FROM calendar_backfill_jobs
                WHERE dedupe_key=? AND status IN ('queued', 'running')
                ORDER BY created_at DESC LIMIT 1
            ''', (dedupe_key,)).fetchone()
            if not existing:
                raise
            return get_calendar_job(existing['id']), False
    ensure_calendar_worker()
    return get_calendar_job(job_id), True


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
    return enqueue_calendar_job(
        mode=source['mode'], year=source.get('year'), days=source.get('days'),
        mids=failed_mids, requested_by=requested_by,
        reason=f"重试任务 {job_id}", dedupe_key=f"retry:{job_id}",
    )


def _claim_next_job(worker_id):
    now = int(time.time())
    with _write_lock:
        conn = get_conn()
        conn.commit()
        conn.execute('BEGIN IMMEDIATE')
        try:
            stale = conn.execute('''
                SELECT id FROM calendar_backfill_jobs
                WHERE status='running' AND COALESCE(lease_until, 0) < ?
            ''', (now,)).fetchall()
            for row in stale:
                conn.execute('''
                    UPDATE calendar_backfill_jobs
                    SET status='queued', worker_id=NULL, lease_until=NULL, updated_at=?
                    WHERE id=?
                ''', (now, row['id']))
                conn.execute('''
                    UPDATE calendar_backfill_job_items SET status='queued'
                    WHERE job_id=? AND status='running'
                ''', (row['id'],))

            active = conn.execute('''
                SELECT 1 FROM calendar_backfill_jobs
                WHERE status='running' AND lease_until>=? LIMIT 1
            ''', (now,)).fetchone()
            if active:
                conn.commit()
                return None
            row = conn.execute('''
                SELECT id FROM calendar_backfill_jobs
                WHERE status='queued' ORDER BY created_at LIMIT 1
            ''').fetchone()
            if not row:
                conn.commit()
                return None
            conn.execute('''
                UPDATE calendar_backfill_jobs
                SET status='running', started_at=COALESCE(started_at, ?),
                    updated_at=?, lease_until=?, worker_id=?
                WHERE id=? AND status='queued'
            ''', (now, now, now + LEASE_SECONDS, worker_id, row['id']))
            conn.commit()
            return get_calendar_job(row['id'])
        except Exception:
            conn.rollback()
            raise


def _update_item(job_id, event, worker_id):
    now = int(time.time())
    status = event.get('status', 'running')
    with _write_lock:
        conn = get_conn()
        conn.execute('''
            UPDATE calendar_backfill_job_items
            SET status=?, pages=?, videos=?, attempts=?, error_code=?, error_message=?,
                started_at=COALESCE(started_at, ?),
                finished_at=CASE WHEN ?='running' THEN finished_at ELSE ? END
            WHERE job_id=? AND mid=?
        ''', (
            status, int(event.get('pages') or 0), int(event.get('videos') or 0),
            int(event.get('attempts') or 0), event.get('error_code') or '',
            (event.get('error_message') or '')[:500], now, status, now,
            job_id, int(event['mid']),
        ))
        counts = conn.execute('''
            SELECT
                SUM(CASE WHEN status!='queued' AND status!='running' THEN 1 ELSE 0 END) processed,
                SUM(CASE WHEN status IN ('success','empty') THEN 1 ELSE 0 END) succeeded,
                SUM(CASE WHEN status='empty' THEN 1 ELSE 0 END) empty_count,
                SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) failed,
                SUM(CASE WHEN status='partial' THEN 1 ELSE 0 END) partial,
                SUM(videos) total_videos
            FROM calendar_backfill_job_items WHERE job_id=?
        ''', (job_id,)).fetchone()
        conn.execute('''
            UPDATE calendar_backfill_jobs
            SET processed_ups=?, succeeded_ups=?, empty_ups=?, failed_ups=?,
                partial_ups=?, total_videos=?, updated_at=?, lease_until=?, worker_id=?
            WHERE id=?
        ''', (
            int(counts['processed'] or 0), int(counts['succeeded'] or 0),
            int(counts['empty_count'] or 0), int(counts['failed'] or 0),
            int(counts['partial'] or 0), int(counts['total_videos'] or 0),
            now, now + LEASE_SECONDS, worker_id, job_id,
        ))
        conn.commit()


def _finish_job(job_id, status, error_summary=''):
    now = int(time.time())
    with _write_lock:
        conn = get_conn()
        conn.execute('''
            UPDATE calendar_backfill_jobs
            SET status=?, finished_at=?, updated_at=?, lease_until=NULL,
                worker_id=NULL, error_summary=? WHERE id=?
        ''', (status, now, now, (error_summary or '')[:1000], job_id))
        conn.commit()


def _fail_unstarted_items(job_id, code, message):
    now = int(time.time())
    with _write_lock:
        conn = get_conn()
        conn.execute('''
            UPDATE calendar_backfill_job_items
            SET status='failed', attempts=1, error_code=?, error_message=?,
                started_at=COALESCE(started_at, ?), finished_at=?
            WHERE job_id=? AND status IN ('queued','running')
        ''', (code, message[:500], now, now, job_id))
        count = conn.execute(
            'SELECT COUNT(*) c FROM calendar_backfill_job_items WHERE job_id=?', (job_id,)
        ).fetchone()['c']
        conn.execute('''
            UPDATE calendar_backfill_jobs
            SET processed_ups=?, failed_ups=?, updated_at=? WHERE id=?
        ''', (count, count, now, job_id))
        conn.commit()


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
        _fail_unstarted_items(job_id, 'job_error', str(exc))
        _finish_job(job_id, 'failed', str(exc))


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

