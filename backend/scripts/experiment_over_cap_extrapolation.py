# -*- coding: utf-8 -*-
"""实验：超播放上限视频的潜力分外推合理性验证（2026-08-02）

背景：score_potential_batch 新增 extra 参数后，超 POTENTIAL_VIEWS_MAX（100 万）的
已火视频若已有观测数据，会用候选池批内边界外推潜力分（不参与批内归一），
供 kichu_rank 展示、不进潜力榜（hot_videos）。

本脚本模拟同一超限视频在不同播放量（101万/150万/200万/300万/500万/1000万）
与不同假设下的 potential_score 变化，验证外推逻辑：
1. 外推分数始终 ≤100、不因越界归一破上限被 clamp
2. heat 维度：超限视频播放量远超候选池 → 边界裁剪到 1.0 饱和（"批内已最强"）
3. 同接率随播放量稀释（同接绝对数固定时）→ online_factor 从加成滑向基底 0.8
4. quality 维度随互动假设变化：互动率恒定则稳定；绝对互动固定则被稀释压向 0
5. 无观测（online_count=None）→ 同接中性 ×1.0，与候选池 A2 语义一致
6. 脚本内维度分解（复用 scorer 的 _minmax_bounds/_minmax_apply）与实际
   potential_score 交叉验证一致

运行：backend 目录下 ./.venv/Scripts/python.exe scripts/experiment_over_cap_extrapolation.py
"""
import sys
import os
import math

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import ONLINE_FACTOR_BASE, ONLINE_FACTOR_WEIGHT, POTENTIAL_VIEWS_MAX
from utils.scorer import (
    score_potential_batch, calc_engagement_quality, calc_online_index,
    _minmax_bounds, _minmax_apply,
)

NOW = 1700000000


def mk(bvid, views, likes, coins, favs, shares, comments, danmaku,
       online, age_hours=20, trend=50, duration=90):
    """构造视频 dict（字段对齐 score_potential_batch 读取的键）。"""
    return {
        'bvid': bvid, 'views': views, 'likes': likes, 'coins': coins,
        'favorites': favs, 'shares': shares, 'comments': comments,
        'danmaku': danmaku, 'duration': duration,
        'pub_date': NOW - int(age_hours * 3600),
        'online_count': online, 'trend_score': trend,
    }


def build_candidates():
    """固定候选池：4 条且同接全有效，激活批内归一（n>=3 且失败率 0）。

    与线上比例近似（真实候选池 20~30 条），数值只用于相对验证。
    """
    return [
        mk('c1', 100000, 5000, 3000, 2000, 8000, 3000, 500, 500, age_hours=20, trend=95),
        mk('c2', 80000, 1000, 200, 150, 5000, 1500, 300, 300, age_hours=20, trend=60),
        mk('c3', 60000, 3000, 500, 400, 200, 500, 200, 50, age_hours=20, trend=40),
        mk('c4', 40000, 300, 50, 30, 80, 100, 80, 10, age_hours=20, trend=5),
    ]


def raw_heat(v):
    """与 scorer 同款热度公式（独立实现，交叉验证用）。"""
    views = int(v.get('views') or 0)
    shares = int(v.get('shares') or 0)
    comments = int(v.get('comments') or 0)
    danmaku = int(v.get('danmaku') or 0)
    duration = max(1, int(v.get('duration') or 0))
    spread = (math.log(shares + 1) + math.log(comments + 1)
              + math.log(danmaku / duration + 1)) / 3
    return spread * math.log(views + 1)


def make_over_cap(bvid, views, online, trend, mode='ratio'):
    """构造超限视频。mode='ratio'：互动按播放量等比（互动率恒定，
    展示 heat 饱和 + 同接率稀释）；mode='fixed'：互动绝对数固定
    （互动率随播放量稀释，更接近真实已火视频的互动衰减）。"""
    if mode == 'ratio':
        likes = views * 0.02; coins = views * 0.004; favs = views * 0.005
        shares = views * 0.003; comments = views * 0.005; danmaku = views * 0.003
    else:
        likes = 20000; coins = 8000; favs = 5000
        shares = 30000; comments = 10000; danmaku = 2000
    return mk(bvid, views, int(likes), int(coins), int(favs),
              int(shares), int(comments), int(danmaku), online,
              age_hours=20, trend=trend)


def decompose_extra(v, cands, now):
    """按 scorer 的 extra 分支同款逻辑计算维度分解（交叉验证）。"""
    heat_raw = [raw_heat(c) for c in cands]
    quality_raw = [math.log(calc_engagement_quality(c) + 1) for c in cands]
    trend_raw = [max(0.0, float(c.get('trend_score') or 0)) for c in cands]
    online_idx = [calc_online_index(c) for c in cands if c.get('online_count') is not None]
    online_reliable = (1 - len(online_idx) / max(1, len(cands)) <= 0.5
                       and len(online_idx) >= 3)

    heat = _minmax_apply(raw_heat(v), _minmax_bounds(heat_raw))
    quality = _minmax_apply(math.log(calc_engagement_quality(v) + 1),
                            _minmax_bounds(quality_raw))
    trend = _minmax_apply(max(0.0, float(v.get('trend_score') or 0)),
                          _minmax_bounds(trend_raw))

    pub = v.get('pub_date') or now
    age_days = max(0.0, (now - pub) / 86400)
    freshness = 1.1 - 0.4 * min(age_days / 21, 1.0)

    ob = _minmax_bounds(online_idx) if online_reliable else None
    if ob is None or v.get('online_count') is None:
        online_factor = 1.0
    else:
        online_factor = (ONLINE_FACTOR_BASE + ONLINE_FACTOR_WEIGHT
                         * _minmax_apply(calc_online_index(v), ob))
    momentum = min(freshness * online_factor, 1.0)
    score = round(min(100, max(0, (heat + quality + trend) / 3 * momentum * 100)), 1)
    return heat, quality, trend, online_factor, momentum, score


def run_series(views_list, online, trend, mode, label):
    """对一组播放量逐个计算 extra 分数，输出表格。"""
    base = build_candidates()
    score_potential_batch(base, NOW)
    top = max(base, key=lambda v: v['potential_score'])
    print(f'\n===== {label} =====')
    print(f'候选池第一名: {top["bvid"]} = {top["potential_score"]} 分（对照）'
          f' | 上限 POTENTIAL_VIEWS_MAX = {POTENTIAL_VIEWS_MAX:,}')
    print('  播放量(万) |  潜力分 |  heat   | quality |  trend  | online× | momentum | 同接率')
    print('  ' + '-' * 84)
    max_score = 0.0
    for i, V in enumerate(views_list):
        cands = build_candidates()
        v = make_over_cap(f'x{i}', V, online, trend, mode)
        score_potential_batch(cands, NOW, extra=[v])
        heat, quality, t, of, momentum, calc = decompose_extra(v, cands, NOW)
        actual = v.get('potential_score')
        assert actual == calc, f'分解与实际不一致: {V} → {actual} vs {calc}'
        max_score = max(max_score, actual)
        online_rate = (online / V * 100) if online else 0.0
        print(f'   {V / 10000:8.0f}  | {actual:7.1f} | {heat:5.2f}  | {quality:5.2f}  | '
              f'{t:5.2f}  |  {of:4.2f}  |  {momentum:4.2f}  | {online_rate:6.3f}%')
    print(f'  -> 分数区间 {max_score:.1f} 封顶检查: 全部 ≤100 = {max_score <= 100}')
    return max_score


def main():
    views_list = [1_010_000, 1_500_000, 2_000_000, 3_000_000, 5_000_000, 10_000_000]
    print('=' * 96)
    print('实验：超播放上限视频的潜力分外推（score_potential_batch extra 参数）')
    print('=' * 96)

    # A：互动率恒定 + 同接绝对数固定 → 主要展示同接率随播放量稀释
    run_series(views_list, online=800, trend=90, mode='ratio',
               label='场景A 互动率恒定、同接=800 固定：播放量↑ → 同接率↓ → 动能滑落')

    # B：互动绝对数固定（互动率被稀释）→ 叠加展示 quality 随播放量衰减
    run_series(views_list, online=800, trend=90, mode='fixed',
               label='场景B 互动绝对数固定（更接近真实已火视频互动衰减）、同接=800')

    # C：无观测数据（online_count=None）→ 同接中性 ×1.0，仅看 heat/quality/trend
    run_series(views_list, online=None, trend=90, mode='fixed',
               label='场景C 无观测数据（同接中性 ×1.0，对应无 video_obs 历史）')

    # D：同接敏感度——固定播放量 300 万，同接从 50 → 5000
    print(f'\n===== 场景D 同接敏感度（播放量固定 300 万、互动率恒定）=====')
    for online in (50, 200, 800, 2000, 5000):
        cands = build_candidates()
        v = make_over_cap('d', 3_000_000, online, trend=90, mode='ratio')
        score_potential_batch(cands, NOW, extra=[v])
        heat, quality, t, of, momentum, calc = decompose_extra(v, cands, NOW)
        print(f'   同接 {online:5d} | 潜力分 {v["potential_score"]:6.1f} | '
              f'online_factor {of:.2f} | 同接率 {online / 30000:6.3f}%')

    # E：不变量验证——extra 不改变候选池分数
    print(f'\n===== 场景E 不变量：extra 不参与归一 → 候选池分数完全一致 =====')
    a = build_candidates()
    score_potential_batch(a, NOW)
    b = build_candidates()
    score_potential_batch(b, NOW, extra=[
        make_over_cap('e', 3_000_000, 800, trend=90, mode='ratio')
    ])
    same = all(x['potential_score'] == y['potential_score'] for x, y in zip(a, b))
    print(f'   候选池分数一致 = {same}'
          + ('  ✓' if same else '  ✗ 外推污染了候选归一！'))


if __name__ == '__main__':
    main()
