"""发布日历增量回填单元测试。

验证 calendar_backfill.py 的修复（2026-08-03）：
- fetch_up_videos_by_year 支持 recent_days 窗口模式：只返回窗口内视频，遇窗口外视频停止
- 年份模式（recent_days=None）行为不变（向后兼容）
- 多页窗口模式：窗口外视频触发停止，不翻更多页
- backfill_calendar(mids=None) 只处理 enabled=True 的 UP（disabled 不参与日历）
- backfill_calendar(mids=显式列表) 不过滤（显式指定即处理）
不依赖真实网络（mock safe_get_with_wbi / load_tracked_list / fetch_up_videos_by_year）。
"""
import os
import tempfile
from datetime import datetime, timezone, timedelta

import pytest

import collectors.calendar_backfill as backfill
import storage.db as db

CN_TZ = timezone(timedelta(hours=8))


@pytest.fixture
def calendar_db(monkeypatch):
    """临时 SQLite"""
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, 'test.db')
    monkeypatch.setattr(db, 'DB_PATH', db_path)
    monkeypatch.setattr(db, 'DATA_DIR', tmpdir)
    db._thread_local.conn = None
    db.get_conn()
    yield db_path
    db._thread_local.conn = None


def _v(bvid, pub_ts, play=100, title='t'):
    return {'bvid': bvid, 'created': pub_ts, 'play': play, 'title': title}


# ─── fetch_up_videos_by_year：窗口模式 ───

def test_fetch_recent_days_stops_at_window_boundary(monkeypatch):
    """窗口模式：窗口内视频全部返回，遇到窗口外视频停止（降序排列后续只会更早）"""
    now = int(datetime.now(tz=CN_TZ).timestamp())
    DAY = 86400
    page = [
        _v('B1', now - 1 * DAY),    # 1 天前（窗口内）
        _v('B2', now - 20 * DAY),   # 20 天前（窗口内）
        _v('B3', now - 35 * DAY),   # 35 天前（窗口外）→ 触发停止
    ]
    monkeypatch.setattr(backfill, 'safe_get_with_wbi', lambda url, params: {
        'data': {'list': {'vlist': page}}
    })
    result = backfill.fetch_up_videos_by_year(123, recent_days=30)
    assert [v['bvid'] for v in result] == ['B1', 'B2']
    assert all(v['mid'] == 123 and v['views'] in (100,) for v in result)


def test_fetch_recent_days_multipage(monkeypatch):
    """多页窗口模式：第一页满页继续翻页，第二页遇窗口外视频停止"""
    now = int(datetime.now(tz=CN_TZ).timestamp())
    DAY = 86400
    page1 = [_v(f'P1-{i}', now - (1 + i) * 3600, play=i) for i in range(50)]  # 满页（PAGE_SIZE=50）
    page2 = [
        _v('P2A', now - 2 * DAY),
        _v('P2B', now - 40 * DAY),  # 窗口外 → 停止
    ]

    def fake_get(url, params):
        return {'data': {'list': {'vlist': page1 if params['pn'] == 1 else page2}}}

    monkeypatch.setattr(backfill, 'safe_get_with_wbi', fake_get)
    result = backfill.fetch_up_videos_by_year(123, recent_days=30)
    assert len(result) == 51
    assert result[-1]['bvid'] == 'P2A'
    assert 'P2B' not in [v['bvid'] for v in result]


def test_fetch_year_mode_unchanged(monkeypatch):
    """年份模式（默认）行为不变：只返回目标年份视频"""
    page = [
        _v('Y1', int(datetime(2026, 7, 1, tzinfo=CN_TZ).timestamp())),
        _v('Y2', int(datetime(2025, 12, 31, tzinfo=CN_TZ).timestamp())),  # 非目标年 → 停止
    ]
    monkeypatch.setattr(backfill, 'safe_get_with_wbi', lambda url, params: {
        'data': {'list': {'vlist': page}}
    })
    result = backfill.fetch_up_videos_by_year(123, year=2026)
    assert [v['bvid'] for v in result] == ['Y1']


def test_fetch_recent_days_no_videos(monkeypatch):
    """窗口内无视频（第一页即窗口外）→ 空列表"""
    now = int(datetime.now(tz=CN_TZ).timestamp())
    DAY = 86400
    page = [_v('OLD', now - 60 * DAY)]  # 60 天前，远在窗口外
    monkeypatch.setattr(backfill, 'safe_get_with_wbi', lambda url, params: {
        'data': {'list': {'vlist': page}}
    })
    result = backfill.fetch_up_videos_by_year(123, recent_days=30)
    assert result == []


# ─── backfill_calendar：enabled 过滤 ───

def test_backfill_filters_disabled(monkeypatch, calendar_db):
    """mids=None 时只处理 enabled=True 的 UP；无 enabled 字段视为启用"""
    tracked = {'ups': [
        {'mid': 1, 'name': 'A', 'enabled': True},
        {'mid': 2, 'name': 'B', 'enabled': False},   # disabled → 过滤
        {'mid': 3, 'name': 'C'},                     # 无字段 → 默认启用
    ]}
    monkeypatch.setattr(backfill, 'load_tracked_list', lambda: tracked)
    calls = []
    monkeypatch.setattr(
        backfill, 'fetch_up_videos_by_year',
        lambda mid, year, recent_days=None: calls.append(mid) or [],
    )
    backfill.backfill_calendar(recent_days=30)
    assert calls == [1, 3], f'应只处理 enabled UP，实际 {calls}'


def test_backfill_explicit_mids_not_filtered(monkeypatch, calendar_db):
    """显式指定 mids 时不做 enabled 过滤（调用方意图明确）"""
    conn = db.get_conn()
    conn.execute("INSERT INTO ups (mid, name) VALUES (?,?)", (1, 'A'))
    conn.execute("INSERT INTO ups (mid, name) VALUES (?,?)", (2, 'B'))
    conn.commit()
    calls = []
    monkeypatch.setattr(
        backfill, 'fetch_up_videos_by_year',
        lambda mid, year, recent_days=None: calls.append(mid) or [],
    )
    backfill.backfill_calendar(mids=[1, 2], recent_days=30)
    assert calls == [1, 2]


def test_backfill_writes_windowed_videos(monkeypatch, calendar_db):
    """增量回填写入的数据可被日历读取（端到端：窗口抓取 → 落库 → 聚合）"""
    now = int(datetime.now(tz=CN_TZ).timestamp())
    DAY = 86400
    tracked = {'ups': [{'mid': 1, 'name': 'A', 'enabled': True}]}
    monkeypatch.setattr(backfill, 'load_tracked_list', lambda: tracked)
    page = [
        _v('W1', now - 2 * DAY, play=5000),
        _v('W2', now - 15 * DAY, play=3000),
        _v('W3', now - 60 * DAY, play=100),   # 窗口外，不抓
    ]
    monkeypatch.setattr(backfill, 'safe_get_with_wbi', lambda url, params: {
        'data': {'list': {'vlist': page}}
    })
    res = backfill.backfill_calendar(recent_days=30)
    assert res['total_ups'] == 1 and res['total_videos'] == 2

    data = db.get_calendar_data(mids=[1], year=2026)
    total_count = sum(v['count'] for v in data.values())
    total_views = sum(v['views'] for v in data.values())
    assert total_count == 2
    assert total_views == 8000
    # 窗口外视频（W3）未被写入
    conn = db.get_conn()
    rows = conn.execute('SELECT bvid, views FROM calendar_videos WHERE mid=1').fetchall()
    assert sorted(r['bvid'] for r in rows) == ['W1', 'W2']
    assert all(r['views'] != 100 for r in rows)
