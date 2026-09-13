"""排行榜进榜门槛单元测试（G2 修复：门槛窗口与排序窗口统一为近7天）。

覆盖 2026-08-07 修复（见 docs/互粉UP主动态-板块数据口径与问题分析.md G2）：
  - 原 ACTIVE_RECENT_DAYS=30（近30天有发布）→ 统一为 VIEW_RECENT_DAYS=7（近7天有发布）
  - total_recent_views > 0 已隐含"近7天有发布"，门槛窗口与排序字段同源
  - 门槛作为防御：防 total_recent_views 计算异常时误入榜

核心回归守护：test_threshold_7d_not_30d_defense —— 构造"近7-30天发布 + 播放>0"
的异常场景，验证门槛窗口是7天而非30天。若有人把门槛改回30d，此测试会失败。
"""
import time

from collectors.bilibili_user import _select_active_ups, VIEW_RECENT_DAYS


def _up(mid, latest_pub_date, total_recent_views):
    """构造最小 up_trends 项"""
    return {
        'mid': mid,
        'name': f'UP{mid}',
        'latest_pub_date': latest_pub_date,
        'total_recent_views': total_recent_views,
        'recent_video_count': 1 if total_recent_views > 0 else 0,
    }


# ── 正常路径：业务逻辑验证 ──────────────────────────────────────────

def test_within_7d_with_views_enters():
    """近7天有发布 + 播放>0 → 进榜"""
    now = int(time.time())
    up_trends = [_up(1001, now - 3 * 86400, 5000)]
    result = _select_active_ups(up_trends, now=now)
    assert len(result) == 1
    assert result[0]['mid'] == 1001


def test_within_7d_zero_views_excluded():
    """近7天有发布但 total_recent_views=0（视频被删/私密）→ 不进榜（条件2拦截）"""
    now = int(time.time())
    up_trends = [_up(1003, now - 3 * 86400, 0)]
    result = _select_active_ups(up_trends, now=now)
    assert len(result) == 0


def test_boundary_7d_exact_included():
    """边界：latest_pub_date 恰好 = now - 7d → 进榜（>= 含等号）"""
    now = int(time.time())
    up_trends = [_up(1004, now - 7 * 86400, 100)]
    result = _select_active_ups(up_trends, now=now)
    assert len(result) == 1


def test_boundary_8d_excluded():
    """边界：latest_pub_date = now - 8d → 不进榜（> 7d 窗口外）"""
    now = int(time.time())
    up_trends = [_up(1005, now - 8 * 86400, 100)]
    result = _select_active_ups(up_trends, now=now)
    assert len(result) == 0


# ── G2 核心回归守护：门槛窗口是7天而非30天 ──────────────────────────

def test_threshold_7d_not_30d_defense():
    """G2 核心守护：门槛窗口必须是7天，不是30天。

    构造异常场景——UP 在15天前发布（7-30天内），且 total_recent_views>0
    （模拟 _recompute 计算异常未清零）。正常业务下此场景不成立（近7天无发布
    则 total_recent_views 应为0），此测试专门验证防御门槛的窗口：

    - 7天门槛（修复后）：latest_pub_date(15d前) < now-7d → 拦截 ✓
    - 30天门槛（修复前）：latest_pub_date(15d前) >= now-30d → 通过，
      且 total_recent_views>0 → 误入榜 ✗

    若有人把门槛改回 ACTIVE_RECENT_DAYS=30，此测试会失败。
    """
    now = int(time.time())
    up_trends = [_up(1007, now - 15 * 86400, 9999)]  # 异常：15天前发布 + 播放>0
    result = _select_active_ups(up_trends, now=now)
    assert len(result) == 0, "门槛窗口应拦截7-30天前的 UP（防御 total_recent_views 异常）"


def test_published_within_30d_but_not_7d_zero_views_excluded():
    """近7-30天有发布 + 播放0 → 不进榜（双条件均拦截）。

    这是 G2 文档描述的典型场景：UP 10天前发了爆款但近7天0播放。
    修复前30天门槛会让它通过门槛，但 total_recent_views=0 仍拦截（条件2）。
    修复后7天门槛也拦截（条件1）——双保险，行为不变但语义清晰。
    """
    now = int(time.time())
    up_trends = [_up(1002, now - 10 * 86400, 0)]
    result = _select_active_ups(up_trends, now=now)
    assert len(result) == 0


def test_view_recent_days_is_7():
    """回归守护：VIEW_RECENT_DAYS 常量必须是7（防止有人改常量值绕过门槛测试）"""
    assert VIEW_RECENT_DAYS == 7


# ── 边界与混合场景 ──────────────────────────────────────────────────

def test_missing_latest_pub_date_excluded():
    """latest_pub_date=0（缺失）→ 不进榜（0 < active_cutoff）"""
    now = int(time.time())
    up_trends = [_up(1006, 0, 5000)]
    result = _select_active_ups(up_trends, now=now)
    assert len(result) == 0


def test_mixed_ups_filter_correctly():
    """混合场景：3个进榜 + 3个不进榜，验证多 UP 过滤正确性"""
    now = int(time.time())
    up_trends = [
        _up(1, now - 1 * 86400, 1000),    # 进榜：7天内 + 播放>0
        _up(2, now - 5 * 86400, 500),     # 进榜：7天内 + 播放>0
        _up(3, now - 7 * 86400, 100),     # 进榜：边界7天 + 播放>0
        _up(4, now - 10 * 86400, 0),      # 不进榜：7天外 + 0播放
        _up(5, now - 3 * 86400, 0),       # 不进榜：7天内 + 0播放
        _up(6, now - 15 * 86400, 999),    # 不进榜：7天外 + 播放>0（异常，门槛拦截）
    ]
    result = _select_active_ups(up_trends, now=now)
    mids = [u['mid'] for u in result]
    assert mids == [1, 2, 3]


def test_empty_list_returns_empty():
    """空列表 → 返回空"""
    assert _select_active_ups([], now=int(time.time())) == []


def test_now_defaults_to_current_time():
    """now 缺省时用 time.time()（验证默认参数不报错）"""
    up_trends = [_up(1008, int(time.time()) - 86400, 100)]
    result = _select_active_ups(up_trends)  # 不传 now
    assert len(result) == 1
