"""发布日历联合投稿去重单元测试。

背景：calendar_videos 表主键是 (bvid, mid)——联合投稿的每个合作者各自写入一条，
同一视频的播放量在聚合 SUM(views) 时被重复计算。
修复：读侧按 bvid 分组取 MAX(views) 再聚合（get_calendar_data / get_calendar_day_videos）。

本测试验证：
- 联合投稿去重（count 与 views 都不重复）
- 同 bvid 多条记录取 MAX 而非 SUM
- 不同视频同一天正常累加
- 关注名单 mid 过滤 + 去重同时生效
- upsert 幂等（同 bvid+mid 重复写入行数不变）
不依赖真实网络与真实 DB（monkeypatch 到临时 SQLite）。
"""
import os
import tempfile
from datetime import datetime, timezone, timedelta

import pytest

import storage.db as db

CN_TZ = timezone(timedelta(hours=8))
# 动态锚点：30 天前（第二日期 = 锚点+2 天）。写死日期是"时间炸弹"——
# 2026-02-16 在 2026-08-28 后滑出 get_publish_habits 的 180 天窗口，导致用例失败。
# 动态锚点保证任意时间运行都落在窗口与当年日历聚合范围内。
_ANCHOR = datetime.now(CN_TZ) - timedelta(days=30)
ANCHOR_STR = _ANCHOR.strftime('%m-%d')
ANCHOR_ISO = _ANCHOR.strftime('%Y-%m-%d')
ANCHOR_TS = int(_ANCHOR.timestamp())
ANCHOR_YEAR = _ANCHOR.year
_ANCHOR2 = _ANCHOR + timedelta(days=2)
ANCHOR2_STR = _ANCHOR2.strftime('%m-%d')
ANCHOR2_ISO = _ANCHOR2.strftime('%Y-%m-%d')


@pytest.fixture
def calendar_db(monkeypatch):
    """临时 SQLite：重定向 DB_PATH/DATA_DIR 并清连接缓存，get_conn 自动执行全部 schema"""
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, 'test.db')
    monkeypatch.setattr(db, 'DB_PATH', db_path)
    monkeypatch.setattr(db, 'DATA_DIR', tmpdir)
    db._thread_local.conn = None
    db.get_conn()  # 建表（V1-V9）
    yield db_path
    db._thread_local.conn = None


def _video(bvid, mid, views, date_str=ANCHOR_STR, title='联合投稿视频'):
    """构造 upsert_calendar_videos 的输入行"""
    dt = datetime.strptime(f'{ANCHOR_YEAR}-{date_str}', '%Y-%m-%d').replace(tzinfo=CN_TZ)
    return {
        'bvid': bvid,
        'mid': mid,
        'pub_date': int(dt.timestamp()),
        'pub_date_str': date_str,
        'views': views,
        'title': title,
    }


# ─── get_calendar_data：日历热力图聚合 ───

def test_calendar_data_dedup_joint_submission(calendar_db):
    """联合投稿：同一 bvid 两个合作者各写一条，count=1 且 views 不翻倍"""
    db.upsert_calendar_videos([
        _video('B1', 1001, 100000),
        _video('B1', 1002, 100000),
    ])
    data = db.get_calendar_data(mids=[1001, 1002], year=ANCHOR_YEAR)
    day = data[ANCHOR_ISO]
    assert day['count'] == 1, '联合投稿不应计为 2 个视频'
    assert day['views'] == 100000, '联合投稿播放量不应叠加'


def test_calendar_data_views_takes_max_not_sum(calendar_db):
    """同 bvid 多条记录（合作者抓取时刻不同），取 MAX 而非 SUM"""
    db.upsert_calendar_videos([
        _video('B1', 1001, 80000),
        _video('B1', 1002, 80000),
    ])
    day = db.get_calendar_data(mids=[1001, 1002], year=ANCHOR_YEAR)[ANCHOR_ISO]
    assert day['views'] == 80000


def test_calendar_data_distinct_videos_sum(calendar_db):
    """不同视频同一天：count 与 views 正常累加"""
    db.upsert_calendar_videos([
        _video('B1', 1001, 100000),
        _video('B2', 1001, 50000),
    ])
    day = db.get_calendar_data(mids=[1001], year=ANCHOR_YEAR)[ANCHOR_ISO]
    assert day['count'] == 2
    assert day['views'] == 150000


def test_calendar_data_empty_day(calendar_db):
    """无数据日期不出现，不抛异常"""
    db.upsert_calendar_videos([_video('B1', 1001, 100000, date_str=ANCHOR2_STR)])
    data = db.get_calendar_data(mids=[1001], year=ANCHOR_YEAR)
    assert ANCHOR_ISO not in data
    assert data[ANCHOR2_ISO]['count'] == 1


# ─── get_calendar_day_videos：点击日历当天视频列表 ───

def test_calendar_day_videos_dedup(calendar_db):
    """当天列表：联合投稿合并为一条，views 为 MAX"""
    db.upsert_calendar_videos([
        _video('B1', 1001, 120000),
        _video('B1', 1002, 120000),
    ])
    videos = db.get_calendar_day_videos(ANCHOR_ISO, mids=[1001, 1002])
    assert len(videos) == 1
    assert videos[0]['bvid'] == 'B1'
    assert videos[0]['views'] == 120000


def test_calendar_day_videos_mids_filter_with_dedup(calendar_db):
    """mid 过滤与去重同时生效：名单外视频排除，名单内联合投稿合并"""
    db.upsert_calendar_videos([
        _video('B1', 1001, 120000),   # 名单内 1001
        _video('B1', 1002, 120000),   # 名单内 1002（联合投稿）
        _video('B2', 2000, 999999),   # 名单外 2000
    ])
    videos = db.get_calendar_day_videos(ANCHOR_ISO, mids=[1001, 1002])
    assert [v['bvid'] for v in videos] == ['B1']
    assert videos[0]['views'] == 120000


def test_calendar_day_videos_order_by_views_desc(calendar_db):
    """按播放量降序排序"""
    db.upsert_calendar_videos([
        _video('B1', 1001, 30000),
        _video('B2', 1001, 90000),
        _video('B3', 1001, 60000),
    ])
    videos = db.get_calendar_day_videos(ANCHOR_ISO, mids=[1001])
    assert [v['bvid'] for v in videos] == ['B2', 'B3', 'B1']


def test_calendar_day_videos_empty(calendar_db):
    """无记录日期返回空列表"""
    assert db.get_calendar_day_videos('12-31', mids=[1001]) == []


# ─── 空名单边界：mids=[] 必须返回空，不能误显示全部 UP 的数据 ───

def test_calendar_data_empty_mids_returns_empty(calendar_db):
    """空名单（mids=[]）：返回空日历，而不是把所有 UP 的历史数据都显示出来"""
    db.upsert_calendar_videos([
        _video('B1', 1001, 100000),
        _video('B2', 2000, 50000),   # 不在任何名单的 UP
    ])
    assert db.get_calendar_data(mids=[], year=ANCHOR_YEAR) == {}
    # 对照组：mids=None（无名单兜底）仍返回全部
    data = db.get_calendar_data(mids=None, year=ANCHOR_YEAR)
    assert data[ANCHOR_ISO]['count'] == 2


def test_calendar_day_videos_empty_mids_returns_empty(calendar_db):
    """空名单（mids=[]）：当天明细返回空列表，不显示名单外 UP 的视频"""
    db.upsert_calendar_videos([
        _video('B1', 1001, 100000),
        _video('B2', 2000, 50000),
    ])
    assert db.get_calendar_day_videos(ANCHOR_ISO, mids=[]) == []
    # 对照组：mids=None 返回全部
    assert len(db.get_calendar_day_videos(ANCHOR_ISO, mids=None)) == 2


def test_publish_habits_empty_mids_returns_empty(calendar_db):
    """空名单（mids=[]）：发布习惯返回空，不统计全部 UP"""
    db.upsert_calendar_videos([_video('B1', 1001, 100000)])
    habits = db.get_publish_habits(mids=[], days=180)
    assert habits['hourly'] == [] and habits['weekly'] == []
    assert habits['meta'] == {
        'days': 180, 'video_count': 0, 'fetched_at': None, 'latest_pub_date': None,
    }
    # 对照组：mids=None 有数据
    habits_all = db.get_publish_habits(mids=None, days=180)
    assert sum(h['count'] for h in habits_all['hourly']) == 1
    assert habits_all['meta']['video_count'] == 1
    assert habits_all['meta']['fetched_at']
    assert datetime.fromtimestamp(habits_all['meta']['latest_pub_date'], CN_TZ).date() == _ANCHOR.date()


# ─── upsert 幂等 ───

def test_upsert_calendar_videos_idempotent(calendar_db):
    """同 bvid+mid 重复写入（增量抓取）行数不变"""
    rows = [_video('B1', 1001, 50000)]
    db.upsert_calendar_videos(rows)
    db.upsert_calendar_videos(rows)
    db.upsert_calendar_videos(rows)
    conn = db.get_conn()
    cnt = conn.execute('SELECT COUNT(*) AS c FROM calendar_videos').fetchone()['c']
    assert cnt == 1


# ─── N1：去重优先保留名单内 mid 的行 ───
# 背景：_dedup_calendar_videos 曾按"播放量最高/最新插入"物理删除副本，
# 若保留的行 mid 不在追踪名单，读侧 mid IN (...) 过滤后该视频从追踪 UP 日历消失。

def test_calendar_dedup_keeps_tracked_mid_views_lower(calendar_db):
    """名单只含单一合作者：即使名单外副本播放量更高，也保留名单内行，视频不消失"""
    db.upsert_calendar_videos([
        _video('B1', 1001, 80000),   # 名单内 1001
        _video('B1', 1002, 90000),   # 名单外 1002（播放量更高，旧逻辑会挤掉 1001）
    ], tracked_mids=[1001])
    day = db.get_calendar_data(mids=[1001], year=ANCHOR_YEAR)[ANCHOR_ISO]
    assert day['count'] == 1, '名单内视频不应从日历消失'
    assert day['views'] == 90000
    videos = db.get_calendar_day_videos(ANCHOR_ISO, mids=[1001])
    assert len(videos) == 1 and videos[0]['bvid'] == 'B1'


def test_calendar_dedup_keeps_tracked_mid_same_views(calendar_db):
    """名单外副本后插入且同播放量：也不能靠 rowid 更大把名单内行挤掉"""
    db.upsert_calendar_videos([
        _video('B1', 1001, 80000),   # 名单内（先插入，rowid 小）
        _video('B1', 1002, 80000),   # 名单外（后插入，rowid 大）
    ], tracked_mids=[1001])
    day = db.get_calendar_data(mids=[1001], year=ANCHOR_YEAR)[ANCHOR_ISO]
    assert day['count'] == 1
    assert day['views'] == 80000


def test_calendar_dedup_views_max_within_tracked(calendar_db):
    """多名合作者都在名单内：仍按播放量取最高行，名单偏好不影响正常去重"""
    db.upsert_calendar_videos([
        _video('B1', 1001, 80000),
        _video('B1', 1002, 95000),
    ], tracked_mids=[1001, 1002])
    day = db.get_calendar_data(mids=[1001, 1002], year=ANCHOR_YEAR)[ANCHOR_ISO]
    assert day['count'] == 1
    assert day['views'] == 95000


def test_calendar_dedup_without_tracked_keeps_old_behavior(calendar_db):
    """tracked_mids 不传（None）：退化为旧行为，纯按播放量/rowid 去重"""
    db.upsert_calendar_videos([
        _video('B1', 1001, 80000),
        _video('B1', 1002, 90000),
    ])
    day = db.get_calendar_data(mids=None, year=ANCHOR_YEAR)[ANCHOR_ISO]
    assert day['count'] == 1
    assert day['views'] == 90000
