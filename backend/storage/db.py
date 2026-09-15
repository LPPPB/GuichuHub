"""SQLite 时序数据层 — 分析的"唯一事实源"

设计依据（docs/架构演进实施检查清单.md）：
- B6: 每线程独立连接（threading.local）+ busy_timeout，Flask threaded 模式安全
- B7: obs 的 ts 为批次时刻 + INSERT OR REPLACE，同批次写入天然幂等
- A2: 指标字段允许 NULL —— NULL=未知（抓取失败），0=实测为零
- A4: videos.observe_tier 分级观测（hot/warm/cold），抓取成本有恒定上界
- A5: backup_db() 用 conn.backup() 在线备份（含 WAL 内容）

双轨制：本模块是历史态仓库；inspiration_db.json 是当前态缓存（前端读）。
"""
import sqlite3
import threading
import time
import os
import glob
import json
from html import unescape as html_unescape
from datetime import datetime, timezone, timedelta
from config import KICHU_TIDS_WITH_PARENT  # 鬼畜分区唯一真源（含 119 父分区兜底），禁止本地硬编码
from runtime_paths import RuntimePaths
from utils.scorer import calc_engagement_quality  # 互动质量唯一真源（权重/满分线），禁止另写权重

CN_TZ = timezone(timedelta(hours=8))

RUNTIME_PATHS = RuntimePaths.from_environment(os.environ)
DATA_DIR = str(RUNTIME_PATHS.business_db.parent)
DB_PATH = str(RUNTIME_PATHS.business_db)
BACKUP_DIR = str(RUNTIME_PATHS.backup_dir)

_thread_local = threading.local()
_write_lock = threading.Lock()   # 单写者多读者
_business_repository = None


def configure_business_repository(repository):
    """Install the PostgreSQL repository used by public storage adapters.

    This transitional injection point lets callers retain the existing public
    functions while the SQLite implementation is replaced function by function.
    """
    global _business_repository
    _business_repository = repository


def get_business_repository():
    """Return the configured PostgreSQL persistence boundary, if any."""
    return _business_repository

# ==================== 连接与迁移 ====================

def get_conn():
    """获取当前线程的数据库连接（B6：连接不跨线程）"""
    conn = getattr(_thread_local, 'conn', None)
    if conn is None:
        os.makedirs(os.path.dirname(DB_PATH) or '.', exist_ok=True)
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=NORMAL')
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA busy_timeout=5000')
        _thread_local.conn = conn
        _migrate(conn)
    return conn


_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS videos (
    bvid TEXT PRIMARY KEY,
    mid INTEGER,
    title TEXT,
    tid INTEGER,
    tname TEXT,
    pub_date INTEGER,
    duration INTEGER,
    first_seen INTEGER NOT NULL,
    source TEXT,                        -- 发现来源，逗号拼接：kichu/music/funny/popular/tracked_up
    observe_tier TEXT DEFAULT 'hot'     -- 观测分级：hot(每小时)/warm(每天)/cold(停测)
);

CREATE TABLE IF NOT EXISTS ups (
    mid INTEGER PRIMARY KEY,
    name TEXT,
    face TEXT,
    tracked INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS video_obs (
    bvid TEXT NOT NULL,
    ts INTEGER NOT NULL,                -- 批次时刻（一次抓取任务一个 ts）
    views INTEGER,
    likes INTEGER,
    coins INTEGER,
    favorites INTEGER,
    shares INTEGER,
    comments INTEGER,
    danmaku INTEGER,
    online_count INTEGER,               -- A2: NULL=未知（抓取失败），0=实测为零
    potential_score REAL,               -- 当时评分，供回测
    PRIMARY KEY (bvid, ts)
);
CREATE INDEX IF NOT EXISTS idx_video_obs_ts ON video_obs(ts);

CREATE TABLE IF NOT EXISTS video_tags (
    bvid TEXT NOT NULL,
    tag TEXT NOT NULL,
    ts INTEGER NOT NULL,
    PRIMARY KEY (bvid, tag)
);

CREATE TABLE IF NOT EXISTS word_obs (
    word TEXT NOT NULL,
    ts INTEGER NOT NULL,
    count INTEGER NOT NULL,
    scope TEXT NOT NULL DEFAULT 'danmaku',   -- danmaku/title/comment
    PRIMARY KEY (word, ts, scope)
);

CREATE TABLE IF NOT EXISTS crawl_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at INTEGER NOT NULL,
    finished_at INTEGER,
    status TEXT NOT NULL,               -- running/success/failed
    trigger_source TEXT,
    stats_json TEXT
);
"""

# ==================== V2 schema：UP 级观测 + 联合投稿 + 收藏 ====================
# 设计依据：docs/V2.0架构设计.md §3.2
# - up_obs 承接 UP 维度观测数据（活跃度排行/新鲜度等）
# - 整批写入用事务包裹（见 upsert_up_obs），崩溃自动回滚，杜绝部分写入
# - 字段默认值用 0 而非 NULL，避免排序时 NULL 漂移
_SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS up_obs (
    mid INTEGER NOT NULL,
    ts INTEGER NOT NULL,                -- 批次时刻，与 video_obs.ts 对齐
    kichu_count INTEGER DEFAULT 0,       -- 鬼畜视频数
    video_count_30d INTEGER DEFAULT 0,  -- 近7天发布数（活跃度主指标，列名保留 30d）
    views_30d INTEGER DEFAULT 0,        -- 近7天累计播放量（列名保留，语义 2026-08-03 改为近7天）
    latest_pub_ts INTEGER DEFAULT 0,    -- 最近发布时间（新鲜度）
    follower_count INTEGER DEFAULT 0,
    activity_score REAL DEFAULT 0,      -- 活跃度评分
    activity_rank INTEGER DEFAULT 0,    -- 活跃度排名
    play_rank INTEGER DEFAULT 0,        -- 播放量排名
    avg_views INTEGER DEFAULT 0,        -- 平均播放量
    PRIMARY KEY (mid, ts)
);
CREATE INDEX IF NOT EXISTS idx_up_obs_ts ON up_obs(ts);

-- 联合投稿 staff 映射（解决播放量重复计算，按合作者数平分）
CREATE TABLE IF NOT EXISTS up_staff_map (
    bvid TEXT NOT NULL,
    mid INTEGER NOT NULL,
    position INTEGER DEFAULT 0,         -- staff 位置（0=主稿）
    PRIMARY KEY (bvid, mid)
);

-- 收藏（取代 V1 的 favorites JSON）
CREATE TABLE IF NOT EXISTS favorites (
    bvid TEXT PRIMARY KEY,
    title TEXT,
    mid INTEGER,
    added_at INTEGER NOT NULL,
    note TEXT
);
"""

# ==================== V3 schema：补齐 play_ranking 所需字段 ====================
# 设计依据：阶段 2 验证发现 up_obs 缺 video_count（总视频数），导致切读 play_ranking
# 后前端"作品数"显示为空。本迁移补齐该字段，使 up_obs 能完整覆盖两个排行。
#
# 字段语义对照：
#   video_count_total  ← play_ranking.video_count = len(videos)（抓取到的总视频数）
#   video_count_30d    ← 近30天发布数（V2 已有，活跃度主指标）
# 两者语义不同：total 是抓取范围全量，30d 是近期活跃量。
#
# 迁移策略：ALTER TABLE ADD COLUMN，存量行默认填 0（=未知），下次刷新自动覆盖为真实值。
# 安全性：ALTER TABLE 在 SQLite 中是 DDL，自动 COMMIT，但本迁移在 _migrate 里
# executescript 后立即写入 schema_version，单次连接内完成，无事务风险。
_SCHEMA_V3 = """
ALTER TABLE up_obs ADD COLUMN video_count_total INTEGER DEFAULT 0;
"""

# ==================== V4 schema：视频维度数据表 ====================
# 4 个字段（timeline/hot_videos/content_types/keyword_cloud）共用一张表
# - 主键 (ts, field) + INSERT OR REPLACE = 同批次重跑幂等
# - payload_json 存 JSON 数组，整组写入、整组读取（前端要的就是完整数组，不需要 SQL 查内部）
# - 每批次只 4 行，干净（vs 塞进 up_obs 要 556 行冗余）
#
# 方案选型：单表+JSON 列 vs 4 张结构化表
#   - 本场景只需整数组返回前端，不需要 SQL 查内部字段
#   - hot_videos 有 20+ 字段且易变（B站 API 改字段就要迁移），JSON 列更灵活
#   - 4 张表会过度设计，写入逻辑分散
_SCHEMA_V4 = """
CREATE TABLE IF NOT EXISTS video_obs_snapshot (
    ts INTEGER NOT NULL,                -- 批次时刻，与 up_obs.ts 对齐
    field TEXT NOT NULL,                -- 字段标识：timeline/hot_videos/content_types/keyword_cloud
    payload_json TEXT NOT NULL,         -- 序列化后的 JSON 数组
    item_count INTEGER DEFAULT 0,       -- 数组长度（便于统计，不用解析 JSON）
    PRIMARY KEY (ts, field)
);
CREATE INDEX IF NOT EXISTS idx_video_obs_snapshot_ts ON video_obs_snapshot(ts);
"""

# ==================== V5 schema：补齐 up_details 三字段 ====================
# up_obs 原缺 sign/following_count/latest_videos，导致 get_up_details 返回 None/[]，
# 前端 UP 详情页签名和最近视频无法展示。补列后 load_analysis 纯 DB 构造。
#
# 字段语义：
#   sign              ← up_trends[i].sign（UP 签名，文本）
#   following_count    ← up_trends[i].following_count（关注数，整数）
#   latest_videos_json ← JSON.dumps(up_trends[i].latest_videos)（最近 5 条视频，JSON 数组）
# latest_videos 用 JSON 列而非结构化表：每 UP 仅 5 条、前端要整组返回、字段易变，
#   与 video_obs_snapshot 的 JSON 列方案一致，避免过度设计。
#
# 迁移策略：ALTER TABLE ADD COLUMN，存量行默认 ''/0/'[]'，下次刷新覆盖为真实值。
_SCHEMA_V5 = """
ALTER TABLE up_obs ADD COLUMN sign TEXT DEFAULT '';
ALTER TABLE up_obs ADD COLUMN following_count INTEGER DEFAULT 0;
ALTER TABLE up_obs ADD COLUMN latest_videos_json TEXT DEFAULT '[]';
"""
# V5 组合迁移的幂等列清单：(列名, DDL)。executescript 逐条隐式提交非原子，
# 部分失败后再启动会因 duplicate column 崩溃，迁移时逐列检查补齐。
_V5_COLUMNS = [
    ('sign', "ALTER TABLE up_obs ADD COLUMN sign TEXT DEFAULT ''"),
    ('following_count', "ALTER TABLE up_obs ADD COLUMN following_count INTEGER DEFAULT 0"),
    ('latest_videos_json', "ALTER TABLE up_obs ADD COLUMN latest_videos_json TEXT DEFAULT '[]'"),
]

_SCHEMA_V6 = """
ALTER TABLE up_obs ADD COLUMN kichu_count_30d INTEGER DEFAULT 0;
"""

_SCHEMA_V7 = """
CREATE TABLE IF NOT EXISTS calendar_videos (
    bvid TEXT NOT NULL,
    mid INTEGER NOT NULL,
    pub_date INTEGER NOT NULL,
    pub_date_str TEXT NOT NULL,
    views INTEGER DEFAULT 0,
    title TEXT DEFAULT '',
    PRIMARY KEY (bvid, mid)
);
CREATE INDEX IF NOT EXISTS idx_calendar_videos_date ON calendar_videos(pub_date_str);
CREATE INDEX IF NOT EXISTS idx_calendar_videos_mid ON calendar_videos(mid);
"""

# ==================== V8 schema：videos 表补 pic 列 ====================
# 背景：爆发榜 get_bursting_videos 从 videos 表取数据，但 pic（封面URL）未持久化，
# 只能靠运行时缓存补充（cache.get('kichu_rank') 等）。缓存只保留最新一批且不覆盖
# 所有分区，导致大量 hot tier 爆发视频封面为空。
# 修复：给 videos 表加 pic 列，record_video 时持久化封面URL，爆发榜直接从 DB 取。
# 迁移策略：ALTER TABLE ADD COLUMN，存量行默认 NULL，下次抓取自动填充。
_SCHEMA_V8 = """
ALTER TABLE videos ADD COLUMN pic TEXT;
"""

# ==================== V9 schema：up_card_cache 表 ====================
# 背景：UP主列表内联分区标签（biliscope 式），get_up_card 翻页拉 UP 全量投稿
# 计算词云 + 分区 top3 + 统计，结果缓存此表 TTL 1 天，避免列表渲染/悬停反复翻页。
# 独立表理由同 favorites：缓存数据不混入 ups 抓取表（ups 被批量 REPLACE 会覆盖）。
_SCHEMA_V9 = """
CREATE TABLE IF NOT EXISTS up_card_cache (
    mid INTEGER PRIMARY KEY,
    payload_json TEXT NOT NULL,
    fetched_at INTEGER NOT NULL
);
"""

# ==================== V10 schema：video_obs 精度标记 ====================
# 背景：B 站同接 total 是展示字符串（<1000 精确 / "1000+" 千取整 / "1.1万" 万取整），
# video_obs 之前只存解析数值（如 1000），前端折线图无法区分"952（精确）"与
# "1000+（近似）"。新增 online_precision 列：'exact'/'k_plus'/'w'/NULL（老数据未知），
# 观测与抓取落库时同步写入，供前端按精度渲染标记点与 tooltip。
# 迁移策略：ALTER TABLE ADD COLUMN，存量行默认 NULL（未知精度，按精确展示兜底）。
_SCHEMA_V10 = """
ALTER TABLE video_obs ADD COLUMN online_precision TEXT;
"""

# ==================== V11 schema：发布日历可靠回填 ====================
# calendar_videos 保留现有结构以兼容存量数据；新增抓取时间/软失效字段，
# 并用独立关联表保存联合投稿的全部作者。任务表用于跨刷新、跨进程追踪回填进度。
_SCHEMA_V11 = """
CREATE TABLE IF NOT EXISTS calendar_video_authors (
    bvid TEXT NOT NULL,
    mid INTEGER NOT NULL,
    last_seen_at INTEGER NOT NULL DEFAULT 0,
    missing_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    PRIMARY KEY (bvid, mid)
);
CREATE INDEX IF NOT EXISTS idx_calendar_video_authors_mid
    ON calendar_video_authors(mid, status);

CREATE TABLE IF NOT EXISTS calendar_backfill_jobs (
    id TEXT PRIMARY KEY,
    mode TEXT NOT NULL,
    year INTEGER,
    days INTEGER,
    status TEXT NOT NULL DEFAULT 'queued',
    reason TEXT DEFAULT '',
    requested_by TEXT DEFAULT 'system',
    dedupe_key TEXT,
    total_ups INTEGER NOT NULL DEFAULT 0,
    processed_ups INTEGER NOT NULL DEFAULT 0,
    succeeded_ups INTEGER NOT NULL DEFAULT 0,
    empty_ups INTEGER NOT NULL DEFAULT 0,
    failed_ups INTEGER NOT NULL DEFAULT 0,
    partial_ups INTEGER NOT NULL DEFAULT 0,
    total_videos INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    started_at INTEGER,
    finished_at INTEGER,
    updated_at INTEGER NOT NULL,
    lease_until INTEGER,
    worker_id TEXT,
    error_summary TEXT DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_calendar_jobs_active_dedupe
    ON calendar_backfill_jobs(dedupe_key)
    WHERE dedupe_key IS NOT NULL AND status IN ('queued', 'running');
CREATE INDEX IF NOT EXISTS idx_calendar_jobs_status_created
    ON calendar_backfill_jobs(status, created_at);

CREATE TABLE IF NOT EXISTS calendar_backfill_job_items (
    job_id TEXT NOT NULL,
    mid INTEGER NOT NULL,
    name TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'queued',
    pages INTEGER NOT NULL DEFAULT 0,
    videos INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    error_code TEXT DEFAULT '',
    error_message TEXT DEFAULT '',
    started_at INTEGER,
    finished_at INTEGER,
    PRIMARY KEY (job_id, mid),
    FOREIGN KEY (job_id) REFERENCES calendar_backfill_jobs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_calendar_job_items_status
    ON calendar_backfill_job_items(job_id, status);
"""

_V11_CALENDAR_COLUMNS = [
    ('fetched_at', "ALTER TABLE calendar_videos ADD COLUMN fetched_at INTEGER NOT NULL DEFAULT 0"),
    ('last_seen_at', "ALTER TABLE calendar_videos ADD COLUMN last_seen_at INTEGER NOT NULL DEFAULT 0"),
    ('missing_count', "ALTER TABLE calendar_videos ADD COLUMN missing_count INTEGER NOT NULL DEFAULT 0"),
    ('status', "ALTER TABLE calendar_videos ADD COLUMN status TEXT NOT NULL DEFAULT 'active'"),
]

# 迁移列表：(版本号, SQL)。新增表结构变更在此追加 (N, "...") 即可
_MIGRATIONS = [
    (1, _SCHEMA_V1),
    (2, _SCHEMA_V2),
    (3, _SCHEMA_V3),
    (4, _SCHEMA_V4),
    (5, _SCHEMA_V5),
    (6, _SCHEMA_V6),
    (7, _SCHEMA_V7),
    (8, _SCHEMA_V8),
    (9, _SCHEMA_V9),
    (10, _SCHEMA_V10),
    (11, _SCHEMA_V11),
]


def _column_exists(conn, table, column):
    return any(r['name'] == column for r in conn.execute(f'PRAGMA table_info({table})'))


def _migrate(conn):
    """按 schema_version 顺序执行未应用的迁移"""
    conn.execute('''
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at INTEGER NOT NULL
        )
    ''')
    row = conn.execute('SELECT MAX(version) AS v FROM schema_version').fetchone()
    current = row['v'] if row and row['v'] else 0
    for version, sql in _MIGRATIONS:
        if version > current:
            if version == 5:
                # V5 是三条 ALTER 的组合迁移：executescript 逐条隐式提交非原子，
                # 部分失败后再启动会因 duplicate column 崩溃。改为逐列幂等执行，
                # 已存在的列跳过（不重复 ALTER），未应用的补齐。
                for col, ddl in _V5_COLUMNS:
                    if not _column_exists(conn, 'up_obs', col):
                        conn.execute(ddl)
            elif version == 11:
                # 与 V5 同理，多列 ALTER 必须逐列幂等；其余建表语句可安全重放。
                for col, ddl in _V11_CALENDAR_COLUMNS:
                    if not _column_exists(conn, 'calendar_videos', col):
                        conn.execute(ddl)
                conn.executescript(sql)
                now = int(time.time())
                conn.execute('''
                    UPDATE calendar_videos
                    SET fetched_at = CASE WHEN fetched_at = 0 THEN ? ELSE fetched_at END,
                        last_seen_at = CASE WHEN last_seen_at = 0 THEN ? ELSE last_seen_at END
                ''', (now, now))
                conn.execute('''
                    INSERT OR IGNORE INTO calendar_video_authors
                    (bvid, mid, last_seen_at, missing_count, status)
                    SELECT bvid, mid, ?, 0, 'active' FROM calendar_videos
                ''', (now,))
            else:
                conn.executescript(sql)
            conn.execute(
                'INSERT INTO schema_version (version, applied_at) VALUES (?, ?)',
                (version, int(time.time()))
            )
    conn.commit()

# ==================== 批次记录 ====================

def begin_crawl_run(trigger):
    """开始一个抓取批次，返回 run_id"""
    if _business_repository is not None:
        return _business_repository.begin_crawl_run(trigger, int(time.time()))
    with _write_lock:
        conn = get_conn()
        cur = conn.execute(
            "INSERT INTO crawl_runs (started_at, status, trigger_source) VALUES (?, 'running', ?)",
            (int(time.time()), trigger)
        )
        conn.commit()
        return cur.lastrowid


def finish_crawl_run(run_id, status, stats=None):
    if _business_repository is not None:
        _business_repository.finish_crawl_run(run_id, status, stats or {}, int(time.time()))
        return
    with _write_lock:
        conn = get_conn()
        conn.execute(
            "UPDATE crawl_runs SET finished_at=?, status=?, stats_json=? WHERE id=?",
            (int(time.time()), status, json.dumps(stats or {}, ensure_ascii=False), run_id)
        )
        conn.commit()

# ==================== 视频登记与观测写入 ====================

def record_video(video, ts, source):
    """登记视频维度 + 写入一次观测 + 关联标签（单事务）。

    A2: 指标缺失传 None（落库为 NULL=未知）；0 表示实测为零。
    B7: ts 传批次时刻（一批抓取共用一个 ts），INSERT OR REPLACE 幂等。
    C13: 所有发现过的视频都登记（含落选者），保留假阴性分析能力。
    """
    if _business_repository is not None:
        payload = dict(video)
        payload.setdefault('first_seen', ts)
        payload.setdefault('source', source)
        _business_repository.record_video(payload)
        return
    bvid = video.get('bvid')
    if not bvid:
        return
    # 封面URL：parse_video_item/parse_region_rank_item 返回 cover 字段，统一取 cover 或 pic
    pic_url = video.get('cover') or video.get('pic')
    with _write_lock:
        conn = get_conn()
        row = conn.execute('SELECT source FROM videos WHERE bvid=?', (bvid,)).fetchone()
        if row:
            sources = set(filter(None, (row['source'] or '').split(',')))
            sources.add(source)
            # COALESCE：调用侧未提供的字段（None）保留已有值，不覆盖
            conn.execute('''
                UPDATE videos SET
                    mid = COALESCE(?, mid),
                    title = COALESCE(?, title),
                    tid = COALESCE(?, tid),
                    tname = COALESCE(?, tname),
                    pub_date = COALESCE(?, pub_date),
                    duration = COALESCE(?, duration),
                    pic = COALESCE(?, pic),
                    source = ?
                WHERE bvid=?
            ''', (video.get('mid'), (html_unescape(video.get('title') or ''))[:200] or None,
                  video.get('tid'), video.get('tname') or None,
                  video.get('pub_date'), video.get('duration'),
                  pic_url, ','.join(sorted(sources)), bvid))
        else:
            conn.execute('''
                INSERT INTO videos (bvid, mid, title, tid, tname, pub_date, duration, first_seen, source, pic)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            ''', (bvid, video.get('mid'), (html_unescape(video.get('title') or ''))[:200],
                  video.get('tid'), video.get('tname'),
                  video.get('pub_date'), video.get('duration'),
                  ts, source, pic_url))

        conn.execute('''
            INSERT OR REPLACE INTO video_obs
            (bvid, ts, views, likes, coins, favorites, shares, comments, danmaku, online_count, online_precision, potential_score)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        ''', (bvid, ts,
              video.get('views'), video.get('likes'), video.get('coins'),
              video.get('favorites'), video.get('shares'), video.get('comments'),
              video.get('danmaku'), video.get('online_count_raw', video.get('online_count')),
              video.get('online_precision'),
              video.get('potential_score')))

        for tag in (video.get('tags') or []):
            tag = (tag or '').strip()
            if tag:
                conn.execute(
                    'INSERT OR REPLACE INTO video_tags (bvid, tag, ts) VALUES (?,?,?)',
                    (bvid, tag, ts))
        conn.commit()


def record_obs(bvid, ts, metrics):
    """只写观测（轻量观测任务用，不动维度表）。

    metrics 中缺失的键落库为 NULL（A2）。
    """
    if _business_repository is not None:
        _business_repository.record_observation(bvid, ts, metrics)
        return
    with _write_lock:
        conn = get_conn()
        conn.execute('''
            INSERT OR REPLACE INTO video_obs
            (bvid, ts, views, likes, coins, favorites, shares, comments, danmaku, online_count, online_precision, potential_score)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        ''', (bvid, ts,
              metrics.get('views'), metrics.get('likes'), metrics.get('coins'),
              metrics.get('favorites'), metrics.get('shares'), metrics.get('comments'),
              metrics.get('danmaku'), metrics.get('online_count'),
              metrics.get('online_precision'),
              metrics.get('potential_score')))
        conn.commit()


def record_words(words, ts, scope='danmaku'):
    """写入弹幕热词观测。words: [{'word': w, 'count': c}, ...]"""
    if _business_repository is not None:
        _business_repository.record_words(words, ts, scope)
        return
    with _write_lock:
        conn = get_conn()
        conn.executemany('''
            INSERT OR REPLACE INTO word_obs (word, ts, count, scope) VALUES (?,?,?,?)
        ''', [(w['word'], ts, w['count'], scope) for w in words if w.get('word')])
        conn.commit()


def mark_candidates_hot(bvids):
    """候选池内视频强制标记 hot（A4：即使 pub_date 较老也保持高频观测）"""
    if not bvids:
        return
    with _write_lock:
        conn = get_conn()
        conn.executemany(
            "UPDATE videos SET observe_tier='hot' WHERE bvid=?", [(b,) for b in bvids])
        conn.commit()

# ==================== 观测分级退役（A4） ====================

def refresh_observe_tiers(now=None):
    """重评观测分级：抓取成本恒定上界，不随历史数据增长。

    hot:  pub_date ≤ 14天（每小时观测）
    warm: 14天 < pub_date ≤ 60天，或 60天外但仍有增长（每天观测）
    cold: 60天外且最近两次观测播放增量 < 500（已定型，停测）
    """
    now = now or int(time.time())
    day14 = now - 14 * 86400
    day60 = now - 60 * 86400
    cold_count = 0
    with _write_lock:
        conn = get_conn()
        conn.execute("UPDATE videos SET observe_tier='hot' WHERE pub_date > ?", (day14,))
        conn.execute(
            "UPDATE videos SET observe_tier='warm' WHERE pub_date <= ? AND pub_date > ?",
            (day14, day60))
        old_rows = conn.execute(
            "SELECT bvid FROM videos WHERE pub_date <= ?", (day60,)).fetchall()
        for row in old_rows:
            obs = conn.execute(
                'SELECT views FROM video_obs WHERE bvid=? ORDER BY ts DESC LIMIT 2',
                (row['bvid'],)).fetchall()
            if (len(obs) >= 2
                    and obs[0]['views'] is not None and obs[1]['views'] is not None
                    and obs[0]['views'] - obs[1]['views'] < 500):
                conn.execute(
                    "UPDATE videos SET observe_tier='cold' WHERE bvid=?", (row['bvid'],))
                cold_count += 1
            else:
                conn.execute(
                    "UPDATE videos SET observe_tier='warm' WHERE bvid=?", (row['bvid'],))
        conn.commit()
    return cold_count

# ==================== 观测目标查询 ====================

def get_observation_targets(now=None, hot_limit=500):
    """返回本轮需要观测的 bvid 列表。

    hot 全部（上限 hot_limit）+ warm 中距上次观测超过 20 小时的。
    cold 不观测（已定型）。
    """
    now = now or int(time.time())
    conn = get_conn()
    hot = conn.execute(
        "SELECT bvid FROM videos WHERE observe_tier='hot' ORDER BY first_seen DESC LIMIT ?",
        (hot_limit,)).fetchall()
    warm = conn.execute('''
        SELECT v.bvid FROM videos v
        WHERE v.observe_tier='warm'
          AND COALESCE((SELECT MAX(o.ts) FROM video_obs o WHERE o.bvid = v.bvid), 0) < ?
        LIMIT 2000
    ''', (now - 20 * 3600,)).fetchall()
    return [r['bvid'] for r in hot] + [r['bvid'] for r in warm]


# ==================== 单视频观测时序（折线图）====================

def get_video_obs_trend(bvid, hours=48):
    """查询单个视频近 hours 小时的观测时序数据（用于 VideoCard 折线图）。

    返回按时间升序的观测点列表，每个点含 8 个互动指标 + 同接 + 潜力分。
    online_count 为 None 表示该轮抓取失败，前端折线图断点处理。
    online_precision 为同接精度标记（exact/k_plus/w），NULL=老数据未知，
    前端据此把近似点渲染为空心标记 + tooltip 显示"（约）"。
    """
    now = int(time.time())
    start_ts = now - hours * 3600
    conn = get_conn()
    rows = conn.execute('''
        SELECT ts, views, likes, coins, favorites, shares, comments, danmaku, online_count, online_precision, potential_score
        FROM video_obs
        WHERE bvid=? AND ts>=?
        ORDER BY ts ASC
    ''', (bvid, start_ts)).fetchall()
    return [dict(r) for r in rows]


# ==================== 播放增速榜 / 爆发预警 ====================

def get_bursting_videos(window_hours=2, threshold=2.0, limit=20):
    """计算 hot 视频的播放增速，返回按增速降序的列表 + 爆发标记。

    爆发判定（相对阈值）：当前窗口增速 >= 参考窗口增速 × threshold
      - 当前窗口：[latest_ts - window_hours, latest_ts]
      - 参考窗口：[latest_ts - 2*window_hours, latest_ts - window_hours]
    仅统计 observe_tier='hot' 的视频（14天内，有高频观测点）。

    分区过滤（2026-08-01 修复）：videos 表混入素材发掘/UP动态抓取的非鬼畜视频
    （音乐区/搞笑区 hot tier 多达 300+），爆发榜必须只保留鬼畜分区。
    tid 集合来自 config.KICHU_TIDS_WITH_PARENT（鬼畜子分区 + 119 父分区兜底），
    与采集/评分共用同一真源，避免 SQL 硬编码漂移。
    """
    import json
    from collections import defaultdict

    now = int(time.time())
    win_sec = window_hours * 3600
    # 回看 48 小时：速度计算只需最新窗口，同时为迷你趋势线提供足够观测点（2h/次 ≈ 24 点）
    lookback = now - 48 * 3600
    conn = get_conn()

    tids = sorted(KICHU_TIDS_WITH_PARENT)
    tid_placeholders = ','.join('?' * len(tids))
    rows = conn.execute(f'''
        SELECT v.bvid, v.title, v.tid, v.tname, v.pub_date, v.mid, v.pic,
               u.name as owner_name,
               o.ts, o.views
        FROM videos v
        JOIN video_obs o ON v.bvid = o.bvid
        LEFT JOIN ups u ON v.mid = u.mid
        WHERE v.observe_tier = 'hot'
          AND v.tid IN ({tid_placeholders})
          AND o.ts >= ?
          AND o.views IS NOT NULL
        ORDER BY v.bvid, o.ts ASC
    ''', (*tids, lookback)).fetchall()

    # 按 bvid 分组观测点 + 提取视频元信息
    by_bvid = defaultdict(list)
    meta = {}
    for r in rows:
        bvid = r['bvid']
        by_bvid[bvid].append({'ts': r['ts'], 'views': r['views']})
        if bvid not in meta:
            meta[bvid] = {
                'bvid': bvid, 'title': html_unescape(r['title'] or ''), 'pic': r['pic'],
                'owner': {'name': r['owner_name']} if r['owner_name'] else None,
                'tid': r['tid'], 'pubdate': r['pub_date'],
            }

    results = []
    for bvid, pts in by_bvid.items():
        if len(pts) < 2:
            continue
        # pts 已按 ts ASC（SQL ORDER BY）
        latest = pts[-1]
        latest_ts = latest['ts']

        # 当前窗口起点：第一个 >= latest_ts - win_sec 的点
        win1_start = next((p for p in pts if p['ts'] >= latest_ts - win_sec), None)
        if not win1_start or win1_start['ts'] >= latest_ts:
            continue
        dt1 = (latest_ts - win1_start['ts']) / 3600.0
        if dt1 <= 0:
            continue
        speed1 = (latest['views'] - win1_start['views']) / dt1
        if speed1 <= 0:
            continue  # 停涨或数据异常，不入榜

        # 参考窗口起点：第一个 >= win1_start.ts - win_sec 的点
        win2_start = next((p for p in pts if p['ts'] >= win1_start['ts'] - win_sec), None)
        speed2 = None
        is_bursting = False
        if win2_start and win2_start['ts'] < win1_start['ts']:
            dt2 = (win1_start['ts'] - win2_start['ts']) / 3600.0
            if dt2 > 0:
                speed2 = (win1_start['views'] - win2_start['views']) / dt2
                if speed2 > 0 and speed1 >= speed2 * threshold:
                    is_bursting = True

        m = meta[bvid]
        # 迷你趋势线：播放量序列，均匀降采样到 ≤12 点
        spark = [p['views'] for p in pts]
        if len(spark) > 12:
            step = (len(spark) - 1) / 11.0
            spark = [spark[int(round(i * step))] for i in range(12)]
        results.append({
            **m,
            'views': latest['views'],
            'speed': round(speed1, 1),
            'prev_speed': round(speed2, 1) if speed2 is not None and speed2 > 0 else None,
            'speed_ratio': round(speed1 / speed2, 2) if speed2 and speed2 > 0 else None,
            'is_bursting': is_bursting,
            'latest_ts': latest_ts,
            'obs_count': len(pts),
            'spark': spark,
        })

    # 按当前窗口增速降序
    results.sort(key=lambda x: x['speed'], reverse=True)
    return results[:limit]


# ==================== UP 级观测写入 ====================

def upsert_up_obs(ts, up_list, play_ranking=None, active_ranking=None):
    """整批写入 UP 级观测（整批事务原子）。

    安全设计（防部分写入导致静默数据错误）：
      1. 整批在一个 BEGIN ... COMMIT 事务里，崩溃自动回滚，不留半截
      2. 主键 (mid, ts) + INSERT OR REPLACE = 同一批次重跑幂等
      3. 字段缺失传 None（落库为 NULL），但默认值 0 防排序漂移
      4. 排名通过 play_ranking/active_ranking 列表反查 mid 填入，调用方无需预计算

    V3 新增字段：
      video_count_total ← up_list[i].video_count（总视频数，对应 play_ranking.video_count）
    V5 新增字段：
      sign / following_count / latest_videos_json ← up_list 对应字段
    V6 新增字段：
      kichu_count_30d ← up_list[i].recent_kichu_count（近30天鬼畜视频数，与 video_count_30d 同数据源）

    参数:
      ts: 批次时刻（epoch 秒）
      up_list: [{'mid':..., 'kichu_video_count':..., 'total_recent_views':...,
                 'video_count':..., 'recent_video_count':..., 'latest_pub_date':...,
                 'follower_count':..., 'avg_views':..., 'sign':..., 'following_count':...,
                 'latest_videos':..., 'recent_kichu_count':...}, ...]
      play_ranking: 播放量排行列表（analysis.play_ranking），用于反查 play_rank
      active_ranking: 活跃度排行列表（analysis.creator_ranking），用于反查 activity_rank

    返回: 写入行数（应等于 len(up_list)）
    """
    if not up_list:
        return 0
    if _business_repository is not None:
        return _business_repository.upsert_up_observations(
            ts, up_list, play_ranking, active_ranking,
        )

    # 预构建 mid → rank 映射（排名从 1 开始）
    play_rank_map = {}
    if play_ranking:
        for idx, up in enumerate(play_ranking, 1):
            play_rank_map[up.get('mid')] = idx

    active_rank_map = {}
    if active_ranking:
        for idx, up in enumerate(active_ranking, 1):
            active_rank_map[up.get('mid')] = idx

    rows = []
    for up in up_list:
        mid = up.get('mid')
        if mid is None:
            continue
        rows.append((
            mid, ts,
            up.get('kichu_video_count') or 0,
            up.get('recent_video_count') or 0,   # 近30天发布数 = recent_video_count
            up.get('total_recent_views') or 0,
            up.get('latest_pub_date') or 0,
            up.get('follower_count') or 0,
            0.0,                                  # activity_score（暂留 0，后续算法迭代填）
            active_rank_map.get(mid, 0),
            play_rank_map.get(mid, 0),
            up.get('avg_views') or 0,
            up.get('video_count') or 0,           # V3: 总视频数 = video_count
            up.get('sign') or '',                 # V5: UP 签名
            up.get('following_count') or 0,       # V5: 关注数
            json.dumps(up.get('latest_videos') or [], ensure_ascii=False),  # V5: 最近视频 JSON
            up.get('recent_kichu_count') or 0,    # V6: 近30天鬼畜视频数
        ))

    with _write_lock:
        conn = get_conn()
        try:
            # 整批事务：BEGIN ... COMMIT，崩溃自动回滚
            conn.execute('BEGIN')
            conn.executemany('''
                INSERT OR REPLACE INTO up_obs
                (mid, ts, kichu_count, video_count_30d, views_30d, latest_pub_ts,
                 follower_count, activity_score, activity_rank, play_rank, avg_views,
                 video_count_total, sign, following_count, latest_videos_json, kichu_count_30d)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''', rows)
            conn.execute('COMMIT')
        except Exception:
            # 任何异常都回滚，不留半截数据（防场景3：部分写入后崩溃）
            conn.execute('ROLLBACK')
            raise
    return len(rows)


def register_up(mid, name='', face=''):
    """登记 UP 到 ups 表（INSERT OR REPLACE 幂等，主键 mid）。

    用于审核通过后的即时落地：保证 ups 表先有该 UP 行，
    后续视频抓取/联合投稿解析时 mid 关联不缺行。
    仅更新基本信息，不动其它列。
    """
    if mid is None:
        return False
    with _write_lock:
        conn = get_conn()
        conn.execute('''
            INSERT OR REPLACE INTO ups (mid, name, face, tracked) VALUES (?,?,?,1)
        ''', (mid, name or '', face or ''))
        conn.commit()
    return True


# ==================== 视频维度数据写入 ====================

# 合法字段白名单（防 SQL 注入，field 直接拼 SQL 必须校验）
# pool_summary：近7天去重视频池的总播放/视频数/平均播放（2026-08-03 新增，总播放量唯一真源）
_VIDEO_SNAPSHOT_FIELDS = frozenset({
    'timeline', 'hot_videos', 'all_videos', 'content_types', 'keyword_cloud', 'pool_summary'
})


def upsert_video_obs_snapshot(ts, field, payload):
    """写入单个视频维度字段。

    安全设计：
      1. 主键 (ts, field) + INSERT OR REPLACE = 同批次重跑幂等
      2. field 白名单校验，防 SQL 注入（field 直接拼 SQL）
      3. payload_json 用 ensure_ascii=False，体积更小且中文可读
      4. item_count 冗余存长度，便于统计查询不用解析 JSON

    参数:
      ts: 批次时刻（epoch 秒）
      field: 'timeline' / 'hot_videos' / 'content_types' / 'keyword_cloud'
      payload: list[dict]，会被 json.dumps 序列化

    返回: payload 长度
    """
    if field not in _VIDEO_SNAPSHOT_FIELDS:
        raise ValueError(f'非法 field: {field}，允许: {sorted(_VIDEO_SNAPSHOT_FIELDS)}')
    if _business_repository is not None:
        return _business_repository.upsert_snapshot_document(ts, field, payload)

    payload_json = json.dumps(payload, ensure_ascii=False)
    with _write_lock:
        conn = get_conn()
        conn.execute('''
            INSERT OR REPLACE INTO video_obs_snapshot
            (ts, field, payload_json, item_count) VALUES (?,?,?,?)
        ''', (ts, field, payload_json, len(payload)))
        conn.commit()
    return len(payload)


def upsert_video_obs_snapshot_batch(ts, fields_dict):
    """一次写入 4 个字段（单事务，原子）。

    本函数用单事务包裹，4 个字段一起成功或一起失败，不留半截。

    参数:
      ts: 批次时刻
      fields_dict: {'timeline': [...], 'hot_videos': [...],
                    'content_types': [...], 'keyword_cloud': [...]}

    返回: 写入字段数（应等于 len(fields_dict)）

    异常:
      - 非法 field 名 → 立即抛 ValueError（在事务前校验，不留半截）
      - 任何 DB 异常 → 事务回滚，向上抛
    """
    # 事务前校验所有 field，防中途失败留半截
    for field in fields_dict:
        if field not in _VIDEO_SNAPSHOT_FIELDS:
            raise ValueError(f'非法 field: {field}，允许: {sorted(_VIDEO_SNAPSHOT_FIELDS)}')
    if _business_repository is not None:
        return _business_repository.upsert_snapshot_batch(ts, fields_dict)

    with _write_lock:
        conn = get_conn()
        try:
            # 整批事务：BEGIN ... COMMIT，崩溃自动回滚
            conn.execute('BEGIN')
            for field, payload in fields_dict.items():
                payload_json = json.dumps(payload, ensure_ascii=False)
                conn.execute('''
                    INSERT OR REPLACE INTO video_obs_snapshot
                    (ts, field, payload_json, item_count) VALUES (?,?,?,?)
                ''', (ts, field, payload_json, len(payload)))
            conn.execute('COMMIT')
        except Exception:
            # 任何异常都回滚，不留半截数据（与 upsert_up_obs 一致）
            conn.execute('ROLLBACK')
            raise
    return len(fields_dict)


# ==================== 备份（A5） ====================

def backup_db(keep=4):
    """在线备份（conn.backup 含 WAL 内容，一致性快照），保留最近 keep 份。

    注意：不要直接复制 .db 文件——WAL 模式下未 checkpoint 的数据在 -wal 里。
    """
    backup_dir = BACKUP_DIR
    os.makedirs(backup_dir, exist_ok=True)
    ts_str = datetime.now(CN_TZ).strftime('%Y%m%d_%H%M%S')
    backup_path = os.path.join(backup_dir, f'kichu_{ts_str}.db')
    source = get_conn()
    dest = sqlite3.connect(backup_path)
    try:
        source.backup(dest)
    finally:
        dest.close()
    backups = sorted(glob.glob(os.path.join(backup_dir, 'kichu_*.db')))
    for old in backups[:-keep]:
        os.remove(old)
    return backup_path


# ==================== 发布日历（V7） ====================

def upsert_calendar_videos(videos, tracked_mids=None):
    """整批写入日历视频，并保存联合投稿的全部作者关系。

    ``calendar_videos`` 继续保留每个 bvid 一条代表行，避免破坏存量库；
    ``calendar_video_authors`` 保存所有 (bvid, mid) 关系，读侧通过 EXISTS
    过滤启用名单。这样代表行属于已停用合作者时，视频也不会从日历消失。

    返回真实写入统计，而不是输入列表长度。
    """
    fetched = len(videos or [])
    normalized = {}
    authors = set()
    for raw in videos or []:
        bvid = str(raw.get('bvid') or '').strip()
        try:
            mid = int(raw.get('mid'))
            pub_date = int(raw.get('pub_date'))
            views = int(raw.get('views') or 0)
        except (TypeError, ValueError):
            continue
        if not bvid or mid <= 0 or pub_date <= 0:
            continue
        row = {
            'bvid': bvid,
            'mid': mid,
            'pub_date': pub_date,
            'pub_date_str': datetime.fromtimestamp(pub_date, tz=CN_TZ).strftime('%m-%d'),
            'views': max(0, views),
            'title': (raw.get('title') or '')[:200],
        }
        authors.add((bvid, mid))
        current = normalized.get(bvid)
        if current is None or row['views'] >= current['views']:
            normalized[bvid] = row

    if not normalized:
        return {
            'fetched': fetched, 'valid': 0, 'inserted': 0,
            'updated': 0, 'unchanged': 0, 'invalid': fetched,
        }

    now = int(time.time())
    if _business_repository is not None:
        return _business_repository.upsert_calendar_videos(
            list(normalized.values()), authors, fetched, now,
        )
    with _write_lock:
        conn = get_conn()
        existing = {}
        bvids = list(normalized)
        # SQLite 默认变量上限通常为 999，分块读取保证大批次安全。
        for offset in range(0, len(bvids), 500):
            chunk = bvids[offset:offset + 500]
            ph = ','.join('?' * len(chunk))
            rows = conn.execute(f'''
                SELECT bvid, pub_date, views, title
                FROM calendar_videos WHERE bvid IN ({ph})
            ''', chunk).fetchall()
            for row in rows:
                old = existing.get(row['bvid'])
                if old is None or row['views'] >= old['views']:
                    existing[row['bvid']] = dict(row)

        inserted = updated = unchanged = 0
        for bvid, row in normalized.items():
            old = existing.get(bvid)
            if old is None:
                inserted += 1
            elif (old['pub_date'] == row['pub_date']
                  and old['views'] == row['views']
                  and (old['title'] or '') == row['title']):
                unchanged += 1
            else:
                updated += 1

        conn.executemany('''
            INSERT INTO calendar_videos
            (bvid, mid, pub_date, pub_date_str, views, title,
             fetched_at, last_seen_at, missing_count, status)
            VALUES (?,?,?,?,?,?,?,?,0,'active')
            ON CONFLICT(bvid, mid) DO UPDATE SET
                pub_date=excluded.pub_date,
                pub_date_str=excluded.pub_date_str,
                views=MAX(calendar_videos.views, excluded.views),
                title=excluded.title,
                fetched_at=excluded.fetched_at,
                last_seen_at=excluded.last_seen_at,
                missing_count=0,
                status='active'
        ''', [(
            v['bvid'], v['mid'], v['pub_date'], v['pub_date_str'],
            v['views'], v['title'], now, now,
        ) for v in normalized.values()])
        conn.executemany('''
            INSERT INTO calendar_video_authors
            (bvid, mid, last_seen_at, missing_count, status)
            VALUES (?,?,?,0,'active')
            ON CONFLICT(bvid, mid) DO UPDATE SET
                last_seen_at=excluded.last_seen_at,
                missing_count=0,
                status='active'
        ''', [(bvid, mid, now) for bvid, mid in authors])

        # 代表行只保留播放量最高的一条；作者关系已经独立保存，不再依赖代表 mid。
        _dedup_calendar_videos(conn)
        conn.executemany('''
            UPDATE calendar_videos
            SET fetched_at=?, last_seen_at=?, missing_count=0, status='active'
            WHERE bvid=?
        ''', [(now, now, bvid) for bvid in normalized])
        conn.commit()
    return {
        'fetched': fetched,
        'valid': len(normalized),
        'inserted': inserted,
        'updated': updated,
        'unchanged': unchanged,
        'invalid': fetched - len(authors),
    }


def _dedup_calendar_videos(conn, keep_mids=None):
    """联合投稿去重：同一 bvid 只保留一个副本。

    保留优先级（高→低）：
      1. mid 在 keep_mids（追踪名单）内 —— 名单内行必须存活，
         否则读侧 mid 过滤后追踪 UP 的视频会从日历消失（N1）
      2. views 更高（合作者抓取时刻不同播放量有差异，取更接近最新值的行）
      3. rowid 更大（同 views 保留最新插入行）
    keep_mids 为空/None 时不做名单偏好，纯按 views/rowid 去重（旧行为）。
    """
    if keep_mids:
        ph = ','.join('?' * len(keep_mids))
        conn.execute(f'''
            DELETE FROM calendar_videos
            WHERE EXISTS (
                SELECT 1 FROM calendar_videos o
                WHERE o.bvid = calendar_videos.bvid
                  AND (
                      (calendar_videos.mid NOT IN ({ph}) AND o.mid IN ({ph}))
                      OR
                      ((calendar_videos.mid IN ({ph})) = (o.mid IN ({ph}))
                       AND (o.views > calendar_videos.views
                            OR (o.views = calendar_videos.views AND o.rowid > calendar_videos.rowid)))
                  )
            )
        ''', (*keep_mids, *keep_mids, *keep_mids, *keep_mids))
    else:
        conn.execute('''
            DELETE FROM calendar_videos
            WHERE EXISTS (
                SELECT 1 FROM calendar_videos o
                WHERE o.bvid = calendar_videos.bvid
                  AND (o.views > calendar_videos.views
                       OR (o.views = calendar_videos.views AND o.rowid > calendar_videos.rowid))
            )
        ''')


def get_calendar_data(mids=None, year=None):
    """读取日历热力图数据，按日期聚合

    参数:
      mids: UP mid 列表；None = 全部（无名单兜底），空列表 = 空名单返回空（不误显示全部）
      year: 年份，None = 当前年份

    返回: dict { 'YYYY-MM-DD': {'count': N, 'views': N}, ... }
    """
    now = int(time.time())
    if year is None:
        year = datetime.fromtimestamp(now, tz=CN_TZ).year
    year_start = int(datetime(year, 1, 1, tzinfo=CN_TZ).timestamp())
    year_end = int(datetime(year + 1, 1, 1, tzinfo=CN_TZ).timestamp()) - 1

    conn = get_conn()
    if mids == []:
        # 空名单：没有任何 UP 在观测，返回空日历（防止误显示全部 UP 的历史数据）
        return {}
    author_filter = ''
    params = [year_start, year_end]
    if mids is not None:
        placeholders = ','.join('?' * len(mids))
        author_filter = f'''
          AND EXISTS (
              SELECT 1 FROM calendar_video_authors a
              WHERE a.bvid = calendar_videos.bvid
                AND a.status = 'active' AND a.mid IN ({placeholders})
          )'''
        params.extend(mids)
    rows = conn.execute(f'''
        SELECT strftime('%Y-%m-%d', pub_date, 'unixepoch', '+8 hours') AS day,
               COUNT(*) AS cnt, SUM(views) AS total_views
        FROM calendar_videos
        WHERE pub_date BETWEEN ? AND ? AND status = 'active'{author_filter}
        GROUP BY day
        ORDER BY day
    ''', params).fetchall()

    result = {}
    for r in rows:
        result[r['day']] = {
            'count': r['cnt'],
            'views': r['total_views'] or 0,
        }
    return result


def get_calendar_freshness(mids=None, year=None):
    """返回当前名单、指定年份日历数据的最近抓取时间。"""
    if mids == []:
        return None
    params = []
    date_filter = ''
    if year is not None:
        year_start = int(datetime(int(year), 1, 1, tzinfo=CN_TZ).timestamp())
        year_end = int(datetime(int(year) + 1, 1, 1, tzinfo=CN_TZ).timestamp())
        date_filter = ' AND pub_date >= ? AND pub_date < ?'
        params.extend([year_start, year_end])
    author_filter = ''
    if mids is not None:
        ph = ','.join('?' * len(mids))
        author_filter = f'''
          AND EXISTS (
              SELECT 1 FROM calendar_video_authors a
              WHERE a.bvid = calendar_videos.bvid
                AND a.status='active' AND a.mid IN ({ph})
          )'''
        params.extend(mids)
    row = get_conn().execute(f'''
        SELECT MAX(fetched_at) AS fetched_at FROM calendar_videos
        WHERE status='active'{date_filter}{author_filter}
    ''', params).fetchone()
    return int(row['fetched_at']) if row and row['fetched_at'] else None


def get_calendar_recent_series(mids=None, days=60):
    """最近 N 个自然日发布序列，缺失日期显式补零。"""
    days = max(1, min(int(days or 60), 366))
    today = datetime.now(CN_TZ).date()
    start_date = today - timedelta(days=days - 1)
    start_ts = int(datetime.combine(start_date, datetime.min.time(), tzinfo=CN_TZ).timestamp())
    end_ts = int(datetime.combine(today + timedelta(days=1), datetime.min.time(), tzinfo=CN_TZ).timestamp())
    if mids == []:
        aggregated = {}
    else:
        params = [start_ts, end_ts]
        author_filter = ''
        if mids is not None:
            ph = ','.join('?' * len(mids))
            author_filter = f'''
              AND EXISTS (
                  SELECT 1 FROM calendar_video_authors a
                  WHERE a.bvid = calendar_videos.bvid
                    AND a.status='active' AND a.mid IN ({ph})
              )'''
            params.extend(mids)
        rows = get_conn().execute(f'''
            SELECT strftime('%Y-%m-%d', pub_date, 'unixepoch', '+8 hours') AS day,
                   COUNT(*) AS cnt, SUM(views) AS total_views
            FROM calendar_videos
            WHERE pub_date>=? AND pub_date<? AND status='active'{author_filter}
            GROUP BY day ORDER BY day
        ''', params).fetchall()
        aggregated = {
            row['day']: {'count': int(row['cnt']), 'views': int(row['total_views'] or 0)}
            for row in rows
        }
    result = []
    for offset in range(days):
        day = (start_date + timedelta(days=offset)).isoformat()
        value = aggregated.get(day, {'count': 0, 'views': 0})
        result.append({'date': day, **value})
    return result


def get_calendar_day_videos(date_str, mids=None, limit=50):
    """查询某天发布的视频列表，按播放量降序。

    新接口使用 YYYY-MM-DD；暂时兼容旧 MM-DD 调用，避免升级过程中的读侧中断。
    """
    limit = max(1, min(int(limit or 50), 100))
    conn = get_conn()
    if mids == []:
        return []
    if len(date_str) == 10:
        try:
            day = datetime.strptime(date_str, '%Y-%m-%d').replace(tzinfo=CN_TZ)
        except ValueError:
            return []
        date_filter = 'pub_date >= ? AND pub_date < ?'
        params = [int(day.timestamp()), int((day + timedelta(days=1)).timestamp())]
    elif len(date_str) == 5:
        date_filter = 'pub_date_str = ?'
        params = [date_str]
    else:
        return []

    author_filter = ''
    if mids is not None:
        placeholders = ','.join('?' * len(mids))
        author_filter = f'''
          AND EXISTS (
              SELECT 1 FROM calendar_video_authors a
              WHERE a.bvid = calendar_videos.bvid
                AND a.status = 'active' AND a.mid IN ({placeholders})
          )'''
        params.extend(mids)
    params.append(limit)
    rows = conn.execute(f'''
        SELECT bvid, mid, title, views, pub_date, fetched_at
        FROM calendar_videos
        WHERE {date_filter} AND status = 'active'{author_filter}
        ORDER BY views DESC
        LIMIT ?
    ''', params).fetchall()
    return [dict(r) for r in rows]


def reconcile_calendar_author(mid, year, seen_bvids, missing_threshold=2):
    """完整年份扫描成功后，对单个作者做软失效对账。

    只有完整成功的扫描才调用本函数；连续两次未出现才置为 unavailable，
    避免一次 B 站分页抖动误删数据。返回本次标记统计。
    """
    year_start = int(datetime(year, 1, 1, tzinfo=CN_TZ).timestamp())
    year_end = int(datetime(year + 1, 1, 1, tzinfo=CN_TZ).timestamp())
    seen = {str(v) for v in (seen_bvids or []) if v}
    with _write_lock:
        conn = get_conn()
        rows = conn.execute('''
            SELECT a.bvid, a.missing_count
            FROM calendar_video_authors a
            JOIN calendar_videos v ON v.bvid = a.bvid
            WHERE a.mid=? AND v.pub_date>=? AND v.pub_date<?
        ''', (int(mid), year_start, year_end)).fetchall()
        missing = [r for r in rows if r['bvid'] not in seen]
        restored = sum(1 for r in rows if r['bvid'] in seen and r['missing_count'] > 0)
        for row in missing:
            next_count = int(row['missing_count'] or 0) + 1
            status = 'unavailable' if next_count >= missing_threshold else 'active'
            conn.execute('''
                UPDATE calendar_video_authors
                SET missing_count=?, status=? WHERE bvid=? AND mid=?
            ''', (next_count, status, row['bvid'], int(mid)))
        if seen:
            ph = ','.join('?' * len(seen))
            conn.execute(f'''
                UPDATE calendar_video_authors
                SET missing_count=0, status='active'
                WHERE mid=? AND bvid IN ({ph})
            ''', (int(mid), *seen))
        conn.commit()
    return {
        'checked': len(rows),
        'missing': len(missing),
        'unavailable': sum(1 for r in missing if int(r['missing_count'] or 0) + 1 >= missing_threshold),
        'restored': restored,
    }


# ==================== 互动质量分析（宝藏视频） ====================

def get_interaction_quality(limit=20, min_views=1000, max_views=1000000):
    """互动质量榜：识别"低播放高互动"的宝藏视频（选材信号）。

    数据：最新批次视频观测（video_obs）+ 视频元数据（videos）+ UP 名（ups）。
    仅统计鬼畜分区视频（KICHU_TIDS_WITH_PARENT），播放量区间 [min_views, max_views]
    （超百万已火无选材意义，过低播放样本不稳定）。

    互动率均"÷ 播放量"归一为百分比，可跨播放量对比：
      - coin_ratio 投币率（真金白银，最强质量信号）
      - fav_ratio 收藏率 / like_ratio 点赞率 / share_ratio 分享率
      - danmaku_ratio 弹幕率（讨论热度）/ online_ratio 同接率（当下动能）
    综合互动分 = 复用 utils.scorer.calc_engagement_quality 单一真源
    （转发5 > 弹幕2.5 = 评论2 = 投币2 > 收藏1.5 > 点赞1，8% 加权互动率满分），
    与潜力分门槛/评分口径一致，避免同类榜单结论矛盾。
    宝藏标记：播放低于中位数 且 投币率高于中位数（播放未涨但互动强 = 潜力）。
    """
    import statistics
    conn = get_conn()
    latest_ts = conn.execute('SELECT MAX(ts) FROM video_obs').fetchone()[0]
    if not latest_ts:
        return []

    tids = sorted(KICHU_TIDS_WITH_PARENT)
    placeholders = ','.join('?' * len(tids))
    rows = conn.execute(f'''
        SELECT o.bvid, o.views, o.likes, o.coins, o.favorites, o.shares,
               o.comments, o.danmaku, o.online_count,
               v.title, v.mid, v.tname, v.pub_date, u.name AS author
        FROM video_obs o
        JOIN videos v ON o.bvid = v.bvid
        LEFT JOIN ups u ON v.mid = u.mid
        WHERE o.ts = ?
          AND v.tid IN ({placeholders})
          AND o.views BETWEEN ? AND ?
    ''', (latest_ts, *tids, min_views, max_views)).fetchall()

    if not rows:
        return []

    def pct(num, views):
        return round(num / views * 100, 3) if views and num else 0.0

    items = []
    for r in rows:
        views = r['views'] or 0
        if views <= 0:
            continue
        coin_r = pct(r['coins'], views)
        fav_r = pct(r['favorites'], views)
        # 综合互动分：复用 calc_engagement_quality（单一真源，含 8% 满分线封顶），
        # 与潜力分门槛/评分同权重，历史曾另写 (投币×3+收藏×2+分享+评论+弹幕) 权重漂移，已统一。
        engagement = calc_engagement_quality({
            'views': views,
            'likes': r['likes'] or 0,
            'coins': r['coins'] or 0,
            'favorites': r['favorites'] or 0,
            'shares': r['shares'] or 0,
            'comments': r['comments'] or 0,
            'danmaku': r['danmaku'] or 0,
        })
        items.append({
            'bvid': r['bvid'],
            'title': r['title'] or '',
            'mid': r['mid'],
            'author': r['author'] or '',
            'tname': r['tname'] or '',
            'pub_date': r['pub_date'] or 0,
            'views': views,
            'likes': r['likes'] or 0,
            'coins': r['coins'] or 0,
            'favorites': r['favorites'] or 0,
            'shares': r['shares'] or 0,
            'comments': r['comments'] or 0,
            'danmaku': r['danmaku'] or 0,
            'online_count': r['online_count'],
            'coin_ratio': coin_r,
            'fav_ratio': fav_r,
            'like_ratio': pct(r['likes'], views),
            'share_ratio': pct(r['shares'], views),
            'danmaku_ratio': pct(r['danmaku'], views),
            'online_ratio': pct(r['online_count'], views),
            'engagement_score': engagement,
        })

    # 宝藏标记：播放低于中位数 且 投币率高于中位数
    views_median = statistics.median([i['views'] for i in items])
    coin_median = statistics.median([i['coin_ratio'] for i in items])
    for i in items:
        i['is_treasure'] = bool(i['views'] < views_median and i['coin_ratio'] > coin_median)

    items.sort(key=lambda x: x['engagement_score'], reverse=True)
    return items[:limit]


# ==================== 发布习惯分析 ====================

def get_publish_habits(mids=None, days=180):
    """发布习惯：按小时/星期聚合发布量与平均播放（指导发稿时机）。

    数据：calendar_videos（全量投稿，含标题/播放）。
    只统计近 days 天（默认 180 天），避免远古数据稀释规律。
    小时/星期均按北京时间（+8）计算；星期索引 0=周一 ... 6=周日。

    返回:
      hourly: [{hour: 0-23, count, avg_views}]
      weekly: [{weekday: 0-6, count, avg_views}]
      meta: {days, video_count, fetched_at, latest_pub_date}
    """
    now = int(time.time())
    since = now - days * 86400
    conn = get_conn()
    if mids is None:
        params = [since]
        author_filter = ''
    elif not mids:
        # 空名单：没有任何 UP 在观测，返回空（防止误统计全部 UP 的历史数据）
        return {
            'hourly': [], 'weekly': [],
            'meta': {'days': days, 'video_count': 0, 'fetched_at': None, 'latest_pub_date': None},
        }
    else:
        params = [since] + list(mids)
        mids_ph = ','.join('?' * len(mids))
        author_filter = f'''
          AND EXISTS (
              SELECT 1 FROM calendar_video_authors a
              WHERE a.bvid = calendar_videos.bvid
                AND a.status = 'active' AND a.mid IN ({mids_ph})
          )'''

    hourly = []
    rows = conn.execute(f'''
        SELECT CAST(strftime('%H', pub_date, 'unixepoch', '+8 hours') AS INTEGER) AS h,
               COUNT(*) AS cnt, AVG(views) AS avg_v
        FROM calendar_videos
        WHERE pub_date >= ? AND status = 'active'{author_filter}
        GROUP BY h ORDER BY h
    ''', params).fetchall()
    for r in rows:
        hourly.append({'hour': r['h'], 'count': r['cnt'], 'avg_views': int(r['avg_v'] or 0)})

    weekly = []
    # strftime('%w')：0=周日；(+6)%7 转成周一=0 的索引
    rows = conn.execute(f'''
        SELECT (CAST(strftime('%w', pub_date, 'unixepoch', '+8 hours') AS INTEGER) + 6) % 7 AS w,
               COUNT(*) AS cnt, AVG(views) AS avg_v
        FROM calendar_videos
        WHERE pub_date >= ? AND status = 'active'{author_filter}
        GROUP BY w ORDER BY w
    ''', params).fetchall()
    for r in rows:
        weekly.append({'weekday': r['w'], 'count': r['cnt'], 'avg_views': int(r['avg_v'] or 0)})

    summary = conn.execute(f'''
        SELECT COUNT(*) AS video_count,
               MAX(fetched_at) AS fetched_at,
               MAX(pub_date) AS latest_pub_date
        FROM calendar_videos
        WHERE pub_date >= ? AND status = 'active'{author_filter}
    ''', params).fetchone()
    meta = {
        'days': days,
        'video_count': int(summary['video_count'] or 0),
        'fetched_at': int(summary['fetched_at']) if summary['fetched_at'] else None,
        'latest_pub_date': int(summary['latest_pub_date']) if summary['latest_pub_date'] else None,
    }
    return {'hourly': hourly, 'weekly': weekly, 'meta': meta}


# ==================== UP 涨粉榜 ====================

def get_follower_growth(days=7, limit=10):
    """涨粉榜：最新批次 vs 窗口起点批次的粉丝数差值（识别涨粉最快的UP）。

    数据：up_obs（每批次含 follower_count）。
    窗口起点 = 最新批次前 days 天内的最早批次（有粉丝数据），与最新批次对比。
    返回按涨粉数降序，附涨粉率。
    """
    conn = get_conn()
    latest_ts = conn.execute('SELECT MAX(ts) FROM up_obs').fetchone()[0]
    if not latest_ts:
        return []
    since = latest_ts - days * 86400
    prev_row = conn.execute('''
        SELECT ts FROM up_obs
        WHERE ts >= ? AND follower_count > 0
        ORDER BY ts ASC LIMIT 1
    ''', (since,)).fetchone()
    if not prev_row:
        return []
    prev_ts = prev_row['ts']

    rows = conn.execute('''
        SELECT u.mid, u.name, u.face, o.ts, o.follower_count
        FROM up_obs o
        LEFT JOIN ups u ON o.mid = u.mid
        WHERE o.ts IN (?, ?)
    ''', (prev_ts, latest_ts)).fetchall()

    by_mid = {}
    for r in rows:
        by_mid.setdefault(r['mid'], {})[r['ts']] = r['follower_count']

    items = []
    for mid, ts_map in by_mid.items():
        if latest_ts not in ts_map or prev_ts not in ts_map:
            continue
        before = ts_map[prev_ts] or 0
        now = ts_map[latest_ts] or 0
        growth = now - before
        items.append({
            'mid': mid,
            'name': next((r['name'] for r in rows if r['mid'] == mid), '') or '',
            'face': next((r['face'] for r in rows if r['mid'] == mid), '') or '',
            'follower_before': before,
            'follower_now': now,
            'growth': growth,
            'growth_rate': round(growth / before * 100, 2) if before > 0 else 0.0,
            'start_ts': prev_ts,
            'end_ts': latest_ts,
        })

    items.sort(key=lambda x: x['growth'], reverse=True)
    return items[:limit]


# ==================== 标签热度分析（爆款标签） ====================

def get_tag_heat(limit=30, min_count=2):
    """标签热度：鬼畜分区视频的标签出现频次 + 平均播放/互动，识别爆款标签。

    数据：video_tags（视频标签）+ videos（分区）+ video_obs（每个视频最新批次互动）。
    爆款判定：该标签下的视频平均播放高于全体标签中位数
    （标签越热 = 该主题已被市场验证有流量，是二创选题信号）。
    """
    import statistics
    conn = get_conn()
    latest_ts = conn.execute('SELECT MAX(ts) FROM video_obs').fetchone()[0]
    if not latest_ts:
        return []

    tids = sorted(KICHU_TIDS_WITH_PARENT)
    placeholders = ','.join('?' * len(tids))
    rows = conn.execute(f'''
        SELECT t.tag, COUNT(DISTINCT t.bvid) AS cnt,
               AVG(o.views) AS avg_views,
               AVG(o.likes) AS avg_likes,
               AVG(o.coins) AS avg_coins,
               AVG(o.favorites) AS avg_favs
        FROM video_tags t
        JOIN videos v ON t.bvid = v.bvid
        JOIN (
            SELECT bvid, views, likes, coins, favorites
            FROM video_obs
            WHERE (bvid, ts) IN (
                SELECT bvid, MAX(ts) FROM video_obs GROUP BY bvid
            )
        ) o ON o.bvid = t.bvid
        WHERE v.tid IN ({placeholders})
        GROUP BY t.tag
        HAVING cnt >= ?
    ''', (*tids, min_count)).fetchall()

    # 标签表保存原始事实，过滤在读层执行：开发者修改规则后无需重抓历史视频，
    # 标签热度接口即可立刻按新口径重算。
    from collectors.bilibili import is_useless_tag
    items = []
    for r in rows:
        if is_useless_tag(r['tag']):
            continue
        items.append({
            'tag': r['tag'],
            'count': r['cnt'],
            'avg_views': int(r['avg_views'] or 0),
            'avg_likes': int(r['avg_likes'] or 0),
            'avg_coins': int(r['avg_coins'] or 0),
            'avg_favs': int(r['avg_favs'] or 0),
        })

    if not items:
        return []
    # 爆款标记：平均播放高于全体中位数
    median_views = statistics.median([i['avg_views'] for i in items])
    for i in items:
        i['is_hot'] = i['avg_views'] > median_views

    items.sort(key=lambda x: (x['count'], x['avg_views']), reverse=True)
    return items[:limit]


# ==================== 弹幕热词升温榜 ====================

def get_rising_words(recent_batches=2, base_batches=6, min_recent=3, limit=30,
                     return_meta=False):
    """弹幕热词升温榜：按观测批次和批次总词量归一化后比较。

    旧实现直接把“近 6 小时总词频 / 前 24 小时总词频”，在全量抓取每天仅两次、
    偶尔缺批的情况下，实际常退化成两个快照相除。现在固定取最近 N 个完整批次和
    此前 M 个完整批次，并计算每批每一万词出现率，避免窗口长度、批次数量和抓取
    弹幕总量不同造成假升温。历史表只保存 Top100，因此未出现按 0 计。
    """
    import math
    import time
    from analytics.filters import filter_danmaku_words
    conn = get_conn()
    recent_batches = max(1, min(int(recent_batches), 12))
    base_batches = max(1, min(int(base_batches), 30))
    batch_rows = conn.execute('''
        SELECT ts, SUM(count) AS total_count
        FROM word_obs
        WHERE scope = 'danmaku'
        GROUP BY ts
        ORDER BY ts DESC
        LIMIT ?
    ''', (recent_batches + base_batches,)).fetchall()

    meta = {
        'method': 'batch_rate_per_10k',
        'recent_batch_count': min(len(batch_rows), recent_batches),
        'base_batch_count': max(0, len(batch_rows) - recent_batches),
        'requested_recent_batches': recent_batches,
        'requested_base_batches': base_batches,
        'latest_ts': batch_rows[0]['ts'] if batch_rows else None,
        'is_stale': True,
        'data_age_hours': None,
        'sufficient': len(batch_rows) >= recent_batches + 1,
    }
    if not batch_rows:
        return ([], meta) if return_meta else []

    latest_ts = batch_rows[0]['ts']
    age_hours = max(0.0, (time.time() - latest_ts) / 3600)
    meta['data_age_hours'] = round(age_hours, 1)
    meta['is_stale'] = age_hours > 18

    recent_rows = batch_rows[:recent_batches]
    base_rows = batch_rows[recent_batches:]
    if not base_rows:
        return ([], meta) if return_meta else []

    recent_ts = [r['ts'] for r in recent_rows]
    base_ts = [r['ts'] for r in base_rows]
    all_ts = recent_ts + base_ts
    totals = {r['ts']: max(int(r['total_count'] or 0), 1) for r in batch_rows}
    placeholders = ','.join('?' * len(all_ts))
    rows = conn.execute(f'''
        SELECT word, ts, count
        FROM word_obs
        WHERE scope = 'danmaku' AND ts IN ({placeholders})
    ''', all_ts).fetchall()

    by_word = {}
    for r in rows:
        by_word.setdefault(r['word'], {})[r['ts']] = int(r['count'] or 0)

    items = []
    for word, observations in by_word.items():
        recent_counts = [observations.get(ts, 0) for ts in recent_ts]
        base_counts = [observations.get(ts, 0) for ts in base_ts]
        recent_avg = sum(recent_counts) / len(recent_ts)
        base_avg = sum(base_counts) / len(base_ts)
        recent_presence = sum(1 for value in recent_counts if value > 0)
        base_presence = sum(1 for value in base_counts if value > 0)
        if recent_avg < min_recent:
            continue

        recent_rate = sum((observations.get(ts, 0) / totals[ts]) * 10000
                          for ts in recent_ts) / len(recent_ts)
        base_rate = sum((observations.get(ts, 0) / totals[ts]) * 10000
                        for ts in base_ts) / len(base_ts)
        is_new = base_presence == 0
        # 新词至少要连续出现在两个近期批次；只有一个近期批次时允许展示但置信度较低。
        if is_new and recent_presence < min(2, len(recent_ts)):
            continue

        # 每万词率加轻度平滑，低基数词不会因基准接近 0 获得无限倍率。
        growth_ratio = (recent_rate + 0.5) / (base_rate + 0.5)
        # 低于 15% 的波动更接近抓取样本噪声，不冠以“升温”。
        if not is_new and growth_ratio <= 1.15:
            continue
        coverage = recent_presence / len(recent_ts)
        trend_score = math.log2(max(growth_ratio, 1.0)) * math.log1p(recent_avg) * (0.6 + 0.4 * coverage)
        items.append({
            'word': word,
            'recent_count': round(recent_avg),
            'base_count': round(base_avg),
            'recent_rate': round(recent_rate, 2),
            'base_rate': round(base_rate, 2),
            'recent_presence': recent_presence,
            'base_presence': base_presence,
            'growth_ratio': round(growth_ratio, 2),
            'trend_score': round(trend_score, 3),
            'is_new': is_new,
        })

    # 广告/品牌/平台等干扰词清洗（只保留 filter 通过的词）
    kept = {w['word'] for w in filter_danmaku_words([{'word': i['word'], 'count': i['recent_count']} for i in items])}
    items = [i for i in items if i['word'] in kept]

    items.sort(key=lambda x: (x['trend_score'], x['recent_rate']), reverse=True)
    result = items[:limit]
    return (result, meta) if return_meta else result
