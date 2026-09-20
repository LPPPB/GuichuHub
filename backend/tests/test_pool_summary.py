"""视频池求和（pool_summary）落库 + owner 归属 单元测试。

覆盖 2026-08-03 两条口径改造：
1. _recompute_active_scores_by_staff 由"联合投稿按合作者平分"改为 owner（第一作者）全额归属
2. 视频池求和结果落库 video_obs_snapshot.pool_summary，读层 load_analysis 用它覆盖
   up_obs 的 UP 聚合口径（owner 不在追踪名单的视频不会缺失）
"""
import time

import pytest

from storage import db


def _make_up_trends(mids):
    """构造最小 up_trends 列表"""
    return [{'mid': m, 'name': f'UP{m}'} for m in mids]


def test_recompute_owner_attribution(monkeypatch):
    """联合投稿播放量全额归属 owner，空间来源合作者不再拿份额；详情失败回退空间归属"""
    from collectors.bilibili_user import _recompute_active_scores_by_staff

    now = int(time.time())
    videos = [
        # B1：单人投稿，owner=1001
        {'bvid': 'B1', 'views': 1000, 'pub_date': now - 86400, 'up_mid': 1001, 'tid': 22},
        # B2：联合投稿（从 UP222 空间抓取），owner 仍是 1001 → 全额给 1001，222 不拿
        {'bvid': 'B2', 'views': 500, 'pub_date': now - 86400, 'up_mid': 222, 'tid': 26},
        # B3：详情获取失败 → 回退空间归属 up_mid=333
        {'bvid': 'B3', 'views': 200, 'pub_date': now - 86400, 'up_mid': 333, 'tid': 0},
    ]

    def fake_detail(bvid):
        if bvid == 'B3':
            return None  # 模拟 B3 详情获取失败
        return {'owner': {'mid': 1001}}

    monkeypatch.setattr('collectors.bilibili_user.fetch_video_detail', fake_detail)
    monkeypatch.setattr('collectors.bilibili_user.time.sleep', lambda s: None)

    up_trends = _make_up_trends([1001, 222, 333, 111])
    _recompute_active_scores_by_staff(videos, up_trends)
    by_mid = {u['mid']: u for u in up_trends}

    # owner=1001 拿走 B1+B2 全额播放：1500，count 2，鬼畜 2（tid 22/26 均在 KICHU_TIDS）
    assert by_mid[1001]['total_recent_views'] == 1500
    assert by_mid[1001]['recent_video_count'] == 2
    assert by_mid[1001]['recent_kichu_count'] == 2
    assert by_mid[1001]['avg_views'] == 750
    # 空间来源 UP222 不再拿任何份额（旧平分逻辑会给 250）
    assert by_mid[222]['total_recent_views'] == 0
    assert by_mid[222]['recent_video_count'] == 0
    # 无关 UP 不受影响
    assert by_mid[111]['total_recent_views'] == 0
    # B3 详情失败回退空间归属 333
    assert by_mid[333]['total_recent_views'] == 200
    assert by_mid[333]['recent_video_count'] == 1
    assert by_mid[333]['avg_views'] == 200


def test_recompute_owner_empty_recent(monkeypatch):
    """无近 N 天视频时全部清零"""
    from collectors.bilibili_user import _recompute_active_scores_by_staff

    videos = [{'bvid': 'B1', 'views': 100, 'pub_date': int(time.time()) - 30 * 86400, 'up_mid': 1}]
    up_trends = _make_up_trends([1])
    _recompute_active_scores_by_staff(videos, up_trends, recent_days=7)
    assert up_trends[0]['total_recent_views'] == 0
    assert up_trends[0]['recent_video_count'] == 0
    assert up_trends[0]['avg_views'] == 0


def test_pool_summary_whitelist_write_and_read(postgres_runtime):
    """pool_summary 字段写入白名单 + 读回（新增字段不破坏 4 字段原结构）"""
    ts = int(time.time())
    db.upsert_video_obs_snapshot_batch(ts, {
        'pool_summary': {'total_views': 88888, 'total_videos': 7, 'avg_views_per_video': 12698},
    })

    from storage.video_snapshot_reader import get_video_snapshot_fields
    fields = get_video_snapshot_fields(ts)
    assert fields['pool_summary'] == {
        'total_views': 88888, 'total_videos': 7, 'avg_views_per_video': 12698,
    }


def test_apply_pool_summary_overrides_and_keeps_other_keys():
    """pool_summary 覆盖总量字段、写入显式 pool_* 键、保留其他 summary 键；pool 缺失原样返回"""
    from storage.up_trends_reader import _apply_pool_summary

    s = _apply_pool_summary(
        {'total_ups': 5, 'total_views': 100, 'total_videos': 2, 'avg_views_per_video': 50, 'kichu_up_count': 3},
        {'total_views': 999, 'total_videos': 10, 'avg_views_per_video': 99},
    )
    assert s['total_views'] == 999          # 覆盖为视频池口径
    assert s['total_videos'] == 10
    assert s['avg_views_per_video'] == 99
    assert s['pool_total_views'] == 999     # 显式字段
    assert s['pool_total_videos'] == 10
    assert s['pool_avg_views_per_video'] == 99
    assert s['total_ups'] == 5              # 其他键保留
    assert s['kichu_up_count'] == 3

    # pool 缺失 → 原样（老批次无 pool_summary）
    s2 = _apply_pool_summary({'total_views': 1}, None)
    assert s2 == {'total_views': 1}


def test_load_analysis_uses_pool_summary(postgres_runtime):
    """load_analysis 的 summary 总量字段来自 pool_summary（覆盖 up_obs SUM(views_30d)）"""
    ts = int(time.time())
    postgres_runtime.business.upsert_up_observations(ts, [{
        'mid': 1001, 'name': 'UP甲', 'face': '', 'kichu_video_count': 1,
        'recent_kichu_count': 1, 'recent_video_count': 2, 'total_recent_views': 3000,
        'latest_pub_date': ts, 'follower_count': 100, 'avg_views': 1500,
        'video_count': 5, 'sign': '', 'following_count': 0, 'latest_videos': [],
    }], play_ranking=[{'mid': 1001}], active_ranking=[{'mid': 1001}])

    # 写 pool_summary：total_views=88888（≠ up_obs SUM(views_30d)=3000，用于验证覆盖）
    db.upsert_video_obs_snapshot_batch(ts, {
        'pool_summary': {'total_views': 88888, 'total_videos': 7, 'avg_views_per_video': 12698},
    })

    from storage.up_trends_reader import load_analysis
    res = load_analysis()
    summary = res['analysis']['summary']
    # 总播放/视频数/平均播放全部走视频池口径
    assert summary['total_views'] == 88888
    assert summary['pool_total_views'] == 88888
    assert summary['pool_total_videos'] == 7
    assert summary['pool_avg_views_per_video'] == 12698
    # 非总量字段仍来自 up_obs（未被 pool 覆盖）
    assert summary['total_ups'] == 1
