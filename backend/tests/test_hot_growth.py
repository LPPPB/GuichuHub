# -*- coding: utf-8 -*-
"""高增速视频榜单元测试。

验证 get_hot_growth_videos（storage/video_snapshot_reader.py）：
- 按每小时播放增量降序（speed 主键）
- MIN_GAP_HOURS=1：距最新观测不足 1h 的历史点不作为起点（过滤分钟级批次噪声）
- 停涨/倒退视频不入榜
- 同一批次 all_videos 与 hot_videos 双字段去重（同视频只计一个观测点）
- 元数据（title/_coauthors/cover/url）透传
- 仅一次观测的视频无法算增速被跳过
- limit 生效；空库返回 []
边界与异常数据：
- views 缺失/非法字符串跳过、字符串数字 int() 归一
- 缺 bvid 脏数据跳过
- 损坏 payload_json 批次 / 非列表 payload 跳过，不阻断其余批次
- lookback 窗口过滤旧批次；lookback=0/负数 → []
- 起点播放为 0 → growth_rate=None（除零保护）
- 无 _coauthors 时 up_name 兜底构造；两者皆无 → 空列表
- 全部不合格（单点/停涨）→ []；limit 超过可用数返回全部
- 同批次双字段 views 冲突 → 保留先写入观测
"""
import json
import os
import tempfile

import pytest

import storage.db as db
from storage.video_snapshot_reader import get_hot_growth_videos


@pytest.fixture
def growth_db(monkeypatch):
    """临时 SQLite：重定向 DB_PATH/DATA_DIR 并清连接缓存，get_conn 自动执行全部 schema"""
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, 'test.db')
    monkeypatch.setattr(db, 'DB_PATH', db_path)
    monkeypatch.setattr(db, 'DATA_DIR', tmpdir)
    db._thread_local.conn = None
    db.get_conn()
    yield db_path
    db._thread_local.conn = None


def _seed_batch(ts, videos, with_hot=True):
    """写入一个批次。真实场景 all_videos=全量、hot_videos=播放量TOP10 子集，
    这里同时写两个字段以验证同批次去重。"""
    db.upsert_video_obs_snapshot(ts, 'all_videos', videos)
    if with_hot:
        db.upsert_video_obs_snapshot(ts, 'hot_videos', videos)


def _video(bvid, title, views, up_name='测试UP'):
    return {
        'bvid': bvid, 'title': title, 'views': views, 'cover': f'http://i0.hdslb.com/{bvid}.jpg',
        'url': f'https://www.bilibili.com/video/{bvid}', 'pub_date': 1000000000,
        'up_name': up_name, 'up_mid': 10001,
    }


def test_sort_by_speed_desc(growth_db):
    """按每小时播放增量降序：A 500/时 > D 250/时 > B 200/时 > C 150/时"""
    t0 = 1000000000
    _seed_batch(t0, [
        _video('A', '猛涨视频', 1000),
        _video('B', '中速视频', 2000),
        _video('C', '慢速视频', 3000),
        _video('D', '中快视频', 4000),
    ])
    _seed_batch(t0 + 2 * 3600, [
        _video('A', '猛涨视频', 2000),   # (2000-1000)/2 = 500/时
        _video('B', '中速视频', 2400),   # 200/时
        _video('C', '慢速视频', 3300),   # 150/时
        _video('D', '中快视频', 4500),   # 250/时
    ])
    items = get_hot_growth_videos()
    assert [v['bvid'] for v in items] == ['A', 'D', 'B', 'C']
    assert items[0]['speed'] == pytest.approx(500.0)
    assert items[0]['growth_views'] == 1000
    assert items[0]['growth_rate'] == pytest.approx(100.0)


def test_min_gap_filters_short_interval(growth_db):
    """仅 <1h 间隔的观测 → 无合格起点 → 不入榜；有更早观测则用 >=1h 的最近点作起点"""
    t0 = 1000000000
    _seed_batch(t0, [_video('SHORT', '只有分钟级间隔', 1000)])
    # 0.1h 后第二次观测（全部历史都在 1h 内，无法选起点）
    _seed_batch(t0 + 0.1 * 3600, [_video('SHORT', '只有分钟级间隔', 1005)], with_hot=False)

    # 有 >=1h 起点的视频：T0(1000) → T0+0.1h(1005) → T0+5h(2005)
    _seed_batch(t0, [_video('GAP', '跨小时增速', 1000)])
    _seed_batch(t0 + 0.1 * 3600, [_video('GAP', '跨小时增速', 1005)], with_hot=False)
    _seed_batch(t0 + 5 * 3600, [_video('GAP', '跨小时增速', 2005)], with_hot=False)

    items = get_hot_growth_videos()
    bvids = [v['bvid'] for v in items]
    assert 'SHORT' not in bvids          # 全部历史在 1h 内 → 跳过
    assert 'GAP' in bvids                # 起点应为 T0+0.1h（距最新 4.9h）
    gap = next(v for v in items if v['bvid'] == 'GAP')
    assert gap['growth_views'] == 1000   # 2005-1005（起点是 0.1h 点而非 T0）
    assert gap['speed'] == pytest.approx(1000 / 4.9, abs=0.1)


def test_stagnant_or_shrinking_excluded(growth_db):
    """停涨（delta=0）与倒退（delta<0）的视频不入榜"""
    t0 = 1000000000
    _seed_batch(t0, [
        _video('STOP', '停涨', 5000),
        _video('DOWN', '倒退', 3000),
        _video('UP', '上涨', 1000),
    ])
    _seed_batch(t0 + 2 * 3600, [
        _video('STOP', '停涨', 5000),    # delta=0
        _video('DOWN', '倒退', 2500),    # delta=-500
        _video('UP', '上涨', 2000),      # delta=1000
    ])
    items = get_hot_growth_videos()
    bvids = [v['bvid'] for v in items]
    assert bvids == ['UP']
    assert 'STOP' not in bvids and 'DOWN' not in bvids


def test_same_batch_dedup_across_fields(growth_db):
    """同一批次 all_videos 与 hot_videos 都含的视频只计一个观测点（obs_count 正确）"""
    t0 = 1000000000
    v = _video('DUP', '双字段视频', 1000)
    _seed_batch(t0, [v])                      # 同时写 all_videos + hot_videos
    # 最新批次 all_videos 与 hot_videos 都含 DUP（views 已更新到 2000）
    v2 = dict(v, views=2000)
    _seed_batch(t0 + 2 * 3600, [v2])
    db.upsert_video_obs_snapshot(t0 + 2 * 3600, 'hot_videos', [v2])

    items = get_hot_growth_videos()
    assert len(items) == 1
    assert items[0]['bvid'] == 'DUP'
    assert items[0]['obs_count'] == 2          # 2 个 ts，非 4 个（双字段不重复计）
    assert items[0]['views'] == 2000           # 最新批次 views 已更新


def test_meta_fields_passed_through(growth_db):
    """元数据（title/_coauthors/cover/url/pub_date）透传到结果"""
    t0 = 1000000000
    v = {
        'bvid': 'META', 'title': '联合投稿视频', 'views': 1000,
        'cover': 'http://i0.hdslb.com/meta.jpg', 'url': 'https://www.bilibili.com/video/META',
        'pub_date': 999000000,
        '_coauthors': [{'mid': 1, 'name': '作者A'}, {'mid': 2, 'name': '作者B'}],
    }
    _seed_batch(t0, [v])
    _seed_batch(t0 + 2 * 3600, [dict(v, views=1500)], with_hot=False)

    items = get_hot_growth_videos()
    assert len(items) == 1
    item = items[0]
    assert item['title'] == '联合投稿视频'
    assert item['_coauthors'] == [{'mid': 1, 'name': '作者A'}, {'mid': 2, 'name': '作者B'}]
    assert item['cover'] == 'http://i0.hdslb.com/meta.jpg'
    assert item['url'].endswith('/META')
    assert item['pub_date'] == 999000000


def test_single_observation_skipped(growth_db):
    """仅一次观测的视频无法算增速，不入榜"""
    t0 = 1000000000
    _seed_batch(t0, [_video('ONLY', '只出现一次', 1000)])
    assert get_hot_growth_videos() == []


def test_limit_and_empty(growth_db):
    """limit 截断；空库返回 []"""
    t0 = 1000000000
    videos = [_video(f'L{i}', f'视频{i}', 1000 + i * 100) for i in range(5)]
    _seed_batch(t0, videos)
    _seed_batch(t0 + 2 * 3600, [
        dict(v, views=v['views'] + 1000 * (5 - i)) for i, v in enumerate(videos)
    ], with_hot=False)
    items = get_hot_growth_videos(limit=2)
    assert len(items) == 2

    # 空库：全新临时库（换 DB_PATH）
    import tempfile as _tf
    empty_dir = _tf.mkdtemp()
    db._thread_local.conn = None
    db.DB_PATH = os.path.join(empty_dir, 'empty.db')
    db.DATA_DIR = empty_dir
    db.get_conn()
    assert get_hot_growth_videos() == []


# ==================== 边界情况与异常数据 ====================

def test_non_numeric_views_skipped_or_coerced(growth_db):
    """views 缺失/非法字符串 → 跳过；字符串数字 → int() 归一后正常统计"""
    t0 = 1000000000
    _seed_batch(t0, [
        {'bvid': 'BAD1', 'title': '无views', 'views': None},
        {'bvid': 'BAD2', 'title': '非法views', 'views': 'abc'},
        {'bvid': 'STR', 'title': '字符串数字', 'views': '1000'},
    ], with_hot=False)
    _seed_batch(t0 + 2 * 3600, [
        {'bvid': 'BAD1', 'title': '无views', 'views': None},
        {'bvid': 'BAD2', 'title': '非法views', 'views': 'abc'},
        {'bvid': 'STR', 'title': '字符串数字', 'views': '2000'},
    ], with_hot=False)
    items = get_hot_growth_videos()
    assert [v['bvid'] for v in items] == ['STR']
    assert items[0]['views'] == 2000          # 字符串被 int() 归一
    assert items[0]['growth_views'] == 1000
    assert items[0]['speed'] == pytest.approx(500.0)


def test_missing_bvid_skipped(growth_db):
    """缺 bvid 的脏数据被跳过，不影响其他视频"""
    t0 = 1000000000
    _seed_batch(t0, [
        {'title': '缺bvid', 'views': 1000},
        _video('GOOD', '正常视频', 1000),
    ], with_hot=False)
    _seed_batch(t0 + 2 * 3600, [
        {'title': '缺bvid', 'views': 2000},
        _video('GOOD', '正常视频', 2000),
    ], with_hot=False)
    items = get_hot_growth_videos()
    assert [v['bvid'] for v in items] == ['GOOD']


def test_corrupted_payload_skipped(growth_db):
    """损坏的 payload_json 批次被跳过，不阻断其余批次"""
    t0 = 1000000000
    conn = db.get_conn()
    # 批次1：非法 JSON 直写库（绕过 upsert 的 json 序列化，模拟手工损坏）
    conn.execute(
        "INSERT INTO video_obs_snapshot (ts, field, payload_json, item_count) VALUES (?,?,?,?)",
        (t0, 'all_videos', '{not-valid-json', 1),
    )
    conn.commit()
    # 批次2、3：正常观测
    _seed_batch(t0, [_video('OK', '正常视频', 1000)], with_hot=False)
    _seed_batch(t0 + 2 * 3600, [_video('OK', '正常视频', 2000)], with_hot=False)
    items = get_hot_growth_videos()
    assert [v['bvid'] for v in items] == ['OK']


def test_non_list_payload_skipped(growth_db):
    """payload 非列表（dict 等）视为异常跳过，不崩溃"""
    t0 = 1000000000
    conn = db.get_conn()
    conn.execute(
        "INSERT INTO video_obs_snapshot (ts, field, payload_json, item_count) VALUES (?,?,?,?)",
        (t0, 'all_videos', json.dumps({'bvid': 'DICT', 'views': 1000}), 1),
    )
    conn.commit()
    _seed_batch(t0, [_video('OK', '正常视频', 1000)], with_hot=False)
    _seed_batch(t0 + 2 * 3600, [_video('OK', '正常视频', 2000)], with_hot=False)
    items = get_hot_growth_videos()
    assert [v['bvid'] for v in items] == ['OK']


def test_lookback_window_filters_old_batches(growth_db):
    """超过 lookback 窗口的旧批次不参与增速计算；扩大窗口后重新纳入"""
    t0 = 1000000000
    old = t0 - 30 * 86400
    _seed_batch(old, [_video('OLD', '窗口外视频', 100)])
    _seed_batch(old + 2 * 3600, [_video('OLD', '窗口外视频', 1000)])
    _seed_batch(t0, [_video('NEW', '窗口内视频', 1000)])
    _seed_batch(t0 + 2 * 3600, [_video('NEW', '窗口内视频', 3000)])

    items = get_hot_growth_videos()  # 默认 14 天：OLD 的批次全在窗口外
    assert [v['bvid'] for v in items] == ['NEW']

    items2 = get_hot_growth_videos(lookback_days=31)  # 扩大窗口：OLD 重新纳入
    bvids2 = [v['bvid'] for v in items2]
    assert 'OLD' in bvids2 and 'NEW' in bvids2


def test_prev_views_zero_growth_rate_none(growth_db):
    """起点播放为 0 → growth_rate=None（除零保护），增速仍正常计算"""
    t0 = 1000000000
    _seed_batch(t0, [_video('ZERO', '从零起涨', 0)])
    _seed_batch(t0 + 2 * 3600, [_video('ZERO', '从零起涨', 1000)])
    items = get_hot_growth_videos()
    assert len(items) == 1
    assert items[0]['growth_rate'] is None
    assert items[0]['growth_views'] == 1000
    assert items[0]['speed'] == pytest.approx(500.0)


def test_coauthors_fallback_from_up_name(growth_db):
    """无 _coauthors 时用 up_name/up_mid 构造单作者数组"""
    t0 = 1000000000
    v = {'bvid': 'FALL', 'title': '单作者', 'views': 1000, 'up_name': '某UP', 'up_mid': 42}
    _seed_batch(t0, [v], with_hot=False)
    _seed_batch(t0 + 2 * 3600, [dict(v, views=1500)], with_hot=False)
    items = get_hot_growth_videos()
    assert items[0]['_coauthors'] == [{'mid': 42, 'name': '某UP'}]


def test_no_author_meta_empty_list(growth_db):
    """无 _coauthors 且无 up_name → _coauthors 为空列表（前端解析安全）"""
    t0 = 1000000000
    v = {'bvid': 'NOAU', 'title': '无作者信息', 'views': 1000}
    _seed_batch(t0, [v], with_hot=False)
    _seed_batch(t0 + 2 * 3600, [dict(v, views=1500)], with_hot=False)
    items = get_hot_growth_videos()
    assert items[0]['_coauthors'] == []


def test_all_ineligible_returns_empty(growth_db):
    """有观测数据但全部不合格（单点/停涨）→ 返回 []"""
    t0 = 1000000000
    _seed_batch(t0, [_video('ONLY', '只出现一次', 100)])          # 单点
    _seed_batch(t0, [_video('STOP', '停涨视频', 500)])
    _seed_batch(t0 + 2 * 3600, [_video('STOP', '停涨视频', 500)])  # delta=0
    assert get_hot_growth_videos() == []


def test_limit_larger_than_available(growth_db):
    """limit 超过可用数量 → 返回全部可用"""
    t0 = 1000000000
    _seed_batch(t0, [_video('A1', '视频A', 1000), _video('A2', '视频B', 2000)])
    _seed_batch(t0 + 2 * 3600, [_video('A1', '视频A', 2000), _video('A2', '视频B', 4000)])
    items = get_hot_growth_videos(limit=100)
    assert len(items) == 2


def test_nonpositive_lookback_returns_empty(growth_db):
    """lookback_days=0/负数 → 窗口不含历史批次 → 无可对比观测 → []"""
    t0 = 1000000000
    _seed_batch(t0, [_video('T', '测试视频', 1000)])
    _seed_batch(t0 + 2 * 3600, [_video('T', '测试视频', 2000)])
    assert get_hot_growth_videos(lookback_days=0) == []
    assert get_hot_growth_videos(lookback_days=-5) == []


def test_same_ts_conflicting_views_keeps_first(growth_db):
    """同批次双字段 views 不一致（数据异常）→ 保留先写入的观测，不重复计"""
    t0 = 1000000000
    db.upsert_video_obs_snapshot(t0, 'all_videos', [_video('CF', '冲突视频', 1000)])
    db.upsert_video_obs_snapshot(t0, 'hot_videos', [_video('CF', '冲突视频', 999)])  # 不一致
    _seed_batch(t0 + 2 * 3600, [_video('CF', '冲突视频', 2000)], with_hot=False)
    items = get_hot_growth_videos()
    assert len(items) == 1
    assert items[0]['obs_count'] == 2        # 同批次双字段只计一个点
    assert items[0]['growth_views'] == 1000  # 起点用先写入的 all_videos(1000) 而非 hot_videos(999)
