"""调度层 — APScheduler 定时任务配置

V2 配置化调度（2026-07-29）：
- 全量抓取：每天多时段（默认 03:00 + 15:00 凌晨避峰）
- UP 主动态分析：每天 4 次（默认 04:30/10:30/16:30/22:30，错开全量抓取窗口）
- 轻量观测：每 30 分钟（整点 + 半点，如 12:00 / 12:30）
- SQLite 备份：每周一 06:00（避开 04:00 全量抓取）

所有参数走 config.py 环境变量，Docker 部署可调，无需改代码。
"""

from apscheduler.schedulers.background import BackgroundScheduler
from zoneinfo import ZoneInfo
from storage import db as tsdb
from logger import get_logger

from config import (
    CRAWL_HOURS, UP_TRENDS_HOURS, UP_TRENDS_MINUTE,
    CALENDAR_RECENT_HOURS, CALENDAR_RECENT_MINUTE,
    CALENDAR_DAILY_HOUR, CALENDAR_DAILY_MINUTE,
    CALENDAR_WEEKLY_DAY, CALENDAR_WEEKLY_HOUR, CALENDAR_WEEKLY_MINUTE,
)

logger = get_logger(__name__)

# 显式指定调度器时区：避免容器内 tzlocal() 误判（python:3.12-slim 需装 tzdata 才能识别 TZ）
# 双保险——Dockerfile 已装系统 tzdata，此处再显式传 ZoneInfo，确保 cron 按北京时间触发
SCHEDULER_TIMEZONE = ZoneInfo('Asia/Shanghai')


def _enqueue_calendar_recent(days, reason, bucket):
    """调度器只投递，实际网络抓取由持久化 worker 串行执行。"""
    from jobs.calendar_jobs import enqueue_calendar_job
    job, created = enqueue_calendar_job(
        mode='recent', days=days, requested_by='system:scheduler', reason=reason,
        dedupe_key=f'scheduled:recent:{days}:{bucket}', dedupe_window_seconds=24 * 3600,
    )
    logger.info('日历%s任务%s: %s', days, '已创建' if created else '已复用', job['id'])


def _enqueue_calendar_year():
    from datetime import datetime
    from jobs.calendar_jobs import enqueue_calendar_job
    year = datetime.now(SCHEDULER_TIMEZONE).year
    week = datetime.now(SCHEDULER_TIMEZONE).strftime('%G-W%V')
    job, created = enqueue_calendar_job(
        mode='year', year=year, requested_by='system:scheduler',
        reason='每周当前年份完整刷新与软对账',
        dedupe_key=f'scheduled:year:{year}:{week}', dedupe_window_seconds=8 * 86400,
    )
    logger.info('日历年份任务%s: %s', '已创建' if created else '已复用', job['id'])


def setup_scheduler():
    """创建并启动 BackgroundScheduler，返回 scheduler 实例。

    任务函数在函数内 import 避免循环依赖（crawl_jobs → config → ...）。
    """
    # 延迟 import：避免 app.py 顶层 import 时触发 crawl_jobs → collectors 链加载
    from jobs.crawl_jobs import run_crawl_job, run_observe_job, run_analysis_job

    scheduler = BackgroundScheduler(timezone=SCHEDULER_TIMEZONE)

    # 1. 全量抓取：每天多个时段（默认 03:00 + 15:00）
    for hour_str in CRAWL_HOURS.split(','):
        hour = int(hour_str.strip())
        scheduler.add_job(
            run_crawl_job, 'cron', hour=hour, minute=0, args=('scheduled',),
            id=f'crawl_{hour}', name=f'全量抓取 {hour:02d}:00',
        )
        logger.info(f'  注册全量抓取: 每天 {hour:02d}:00')

    # 2. UP 主动态分析：每天多时段（默认 04:30/10:30/16:30/22:30，错开全量抓取窗口）
    #    04:30/16:30 紧跟 04:00/16:00 全量后半小时（复用锁释放间隙）；
    #    10:30/22:30 落在两全量窗口中间，提升 up_obs 时效性（24h→6h 延迟）。
    for hour_str in UP_TRENDS_HOURS.split(','):
        hour = int(hour_str.strip())
        scheduler.add_job(
            run_analysis_job, 'cron',
            hour=hour, minute=UP_TRENDS_MINUTE, args=('scheduled',),
            id=f'up_trends_{hour}', name=f'UP主动态分析 {hour:02d}:{UP_TRENDS_MINUTE:02d}',
        )
        logger.info(f'  注册UP主动态分析: 每天 {hour:02d}:{UP_TRENDS_MINUTE:02d}')

    # 3. 轻量观测：每 30 分钟，对齐整点 + 半点（12:00 / 12:30 / 13:00...）
    # 用 cron 而非 interval：interval 按进程启动时刻偏移（如 17:12、17:42），
    # 数据点时间不整齐；cron 固定分钟位 0,30 保证观测时间可预期。
    scheduler.add_job(
        run_observe_job, 'cron', minute='0,30',
        id='observe', name='轻量观测 整点+半点',
    )
    logger.info('  注册轻量观测: 每 30 分钟（整点 + 半点，如 12:00 / 12:30）')

    # 4. 发布日历独立调度。与全量抓取解耦，由持久化队列自动错峰串行。
    for hour_str in CALENDAR_RECENT_HOURS.split(','):
        hour = int(hour_str.strip())
        scheduler.add_job(
            _enqueue_calendar_recent, 'cron', hour=hour, minute=CALENDAR_RECENT_MINUTE,
            args=(7, '每 6 小时发现新投稿并刷新近期播放量', f'{hour:02d}'),
            id=f'calendar_recent_{hour}', name=f'日历近期回填 {hour:02d}:{CALENDAR_RECENT_MINUTE:02d}',
        )
    scheduler.add_job(
        _enqueue_calendar_recent, 'cron', hour=CALENDAR_DAILY_HOUR,
        minute=CALENDAR_DAILY_MINUTE,
        args=(30, '每日刷新最近 30 天播放量', 'daily'),
        id='calendar_recent_30d', name='日历30天回填',
    )
    scheduler.add_job(
        _enqueue_calendar_year, 'cron', day_of_week=CALENDAR_WEEKLY_DAY,
        hour=CALENDAR_WEEKLY_HOUR, minute=CALENDAR_WEEKLY_MINUTE,
        id='calendar_year_reconcile', name='日历当前年完整对账',
    )
    logger.info('  注册发布日历: 7天窗口 %s @ :%02d；30天每日 %02d:%02d；完整对账 %s %02d:%02d',
                CALENDAR_RECENT_HOURS, CALENDAR_RECENT_MINUTE,
                CALENDAR_DAILY_HOUR, CALENDAR_DAILY_MINUTE,
                CALENDAR_WEEKLY_DAY, CALENDAR_WEEKLY_HOUR, CALENDAR_WEEKLY_MINUTE)

    # 5. SQLite 备份：每周一 06:00。
    scheduler.add_job(
        tsdb.backup_db, 'cron', day_of_week='mon', hour=6,
        id='backup', name='SQLite备份 周一06:00',
    )
    logger.info('  注册SQLite备份: 每周一 06:00')

    scheduler.start()
    return scheduler
