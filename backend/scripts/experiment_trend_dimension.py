# -*- coding: utf-8 -*-
"""实验：潜力分纳入趋势维度（P0）后，真实数据排名变化是否符合预期。

数据：data/inspiration_db.json 的 hot_videos（最近一次抓取的真实候选池子集，
旧算法筛完的 Top 榜，批内归一样本比线上略小，趋势方向可参考）。

对比：
- 旧公式：score = (heat + quality) / 2 × momentum × 100（无趋势维度，2026-08-02 前线上版）
- 新公式：score = (heat + quality + trend) / 3 × momentum × 100（trend_score 第三维并列归一）

预期（用户确认的目标行为）：
- Spearman 相关度 < 1.0（趋势维度确实改变了排序）
- trend 高（爆发期）的视频排名上升；trend 低/0（停滞期）的视频排名下降
- 不再出现"trend=0 停滞视频压过 trend≈100 爆发视频"的倒挂

运行：cd backend && .\\.venv\\Scripts\\python.exe scripts/experiment_trend_dimension.py
"""
import sys
import os
import json
import copy
import math

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')

from utils.scorer import (
    score_potential_batch, calc_engagement_quality, calc_online_index, _batch_minmax,
)
from config import ONLINE_FACTOR_BASE, ONLINE_FACTOR_WEIGHT


def old_score_batch(candidates, now):
    """旧公式基线：heat/quality 双维 + momentum 乘数（无趋势维度）。

    与 score_potential_batch 仅差 trend 维度，其余逻辑保持一致，
    保证对比口径唯一变量 = 趋势维度。
    """
    heat_raw, quality_raw = [], []
    for v in candidates:
        views = int(v.get('views') or 0)
        shares = int(v.get('shares') or 0)
        comments = int(v.get('comments') or 0)
        danmaku = int(v.get('danmaku') or 0)
        duration = max(1, int(v.get('duration') or 0))
        spread = (math.log(shares + 1) + math.log(comments + 1)
                  + math.log(danmaku / duration + 1)) / 3
        heat_raw.append(spread * math.log(views + 1))
        quality_raw.append(math.log(calc_engagement_quality(v) + 1))

    heat_n = _batch_minmax(heat_raw)
    quality_n = _batch_minmax(quality_raw)

    for v, heat, quality in zip(candidates, heat_n, quality_n):
        pub = v.get('pub_date') or now
        age_days = max(0.0, (now - pub) / 86400)
        freshness = 1.1 - 0.4 * min(age_days / 21, 1.0)
        if v.get('online_count') is None:
            online_factor = 1.0
        else:
            online_factor = ONLINE_FACTOR_BASE + ONLINE_FACTOR_WEIGHT * (calc_online_index(v) / 100)
        momentum = min(freshness * online_factor, 1.0)
        v['old_score'] = round(min(100, max(0, (heat + quality) / 2 * momentum * 100)), 1)


def spearman(rank_a, rank_b):
    n = len(rank_a)
    if n < 2:
        return 1.0
    d2 = sum((a - b) ** 2 for a, b in zip(rank_a, rank_b))
    return 1 - 6 * d2 / (n * (n * n - 1))


def main():
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           '..', 'data', 'inspiration_db.json')
    with open(db_path, encoding='utf-8') as f:
        db = json.load(f)

    videos = db.get('hot_videos', [])
    if not videos:
        print('inspiration_db.json 中没有 hot_videos 数据')
        return

    now = max(int(v.get('pub_date') or 0) for v in videos) + 86400  # 评估时刻 = 数据新鲜度 + 1 天

    old_videos = copy.deepcopy(videos)
    new_videos = copy.deepcopy(videos)
    old_score_batch(old_videos, now)
    score_potential_batch(new_videos, now)

    old_rank = sorted(range(len(old_videos)), key=lambda i: old_videos[i]['old_score'], reverse=True)
    new_rank = sorted(range(len(new_videos)), key=lambda i: new_videos[i]['potential_score'], reverse=True)

    old_pos = {old_videos[i]['bvid']: pos + 1 for pos, i in enumerate(old_rank)}
    new_pos = {new_videos[i]['bvid']: pos + 1 for pos, i in enumerate(new_rank)}

    n = len(videos)
    print(f'样本: {n} 条 hot_videos（真实抓取子集，评估时刻 now={now}）')
    missing_trend = sum(1 for v in videos if not v.get('trend_score'))
    print(f'trend_score 缺失: {missing_trend} 条（缺失按 0 处理，中性偏低）')

    # 趋势维度有效性：新排名与 trend_score 的 Spearman
    trend_rank = sorted(range(n), key=lambda i: float(videos[i].get('trend_score') or 0), reverse=True)
    print(f'Spearman(旧榜 vs 新榜): {spearman([old_pos[new_videos[i]["bvid"]] for i in new_rank], list(range(1, n + 1))):.3f}')
    print(f'Spearman(新榜 vs trend): {spearman([new_pos[videos[i]["bvid"]] for i in trend_rank], list(range(1, n + 1))):.3f}  (>0 = 新榜更贴近增速)')
    print()

    print(f'{"新榜":>4} {"旧榜":>4} {"位移":>5} {"trend":>6} {"旧分":>6} {"新分":>6}  标题')
    print('-' * 100)
    for pos, i in enumerate(new_rank, 1):
        nv = new_videos[i]
        op = old_pos[nv['bvid']]
        delta = op - pos
        mark = f'{delta:+d}' if delta else '·'
        title = nv['title'][:40]
        print(f'{pos:>4} {op:>4} {mark:>5} {float(nv.get("trend_score") or 0):>6.1f} '
              f'{old_videos[i]["old_score"]:>6.1f} {nv["potential_score"]:>6.1f}  {title}')

    new_in = [b for b in new_pos if new_pos[b] <= 10 and old_pos[b] > 10]
    dropped = [b for b in old_pos if old_pos[b] <= 10 and new_pos[b] > 10]
    print()
    if new_in:
        print(f'新进入 Top10（{len(new_in)} 条）:')
        for b in new_in:
            nv = next(v for v in new_videos if v['bvid'] == b)
            print(f'  [{old_pos[b]} -> {new_pos[b]}] trend={float(nv.get("trend_score") or 0):.1f} {nv["title"][:44]}')
    if dropped:
        print(f'跌出 Top10（{len(dropped)} 条）:')
        for b in dropped:
            nv = next(v for v in new_videos if v['bvid'] == b)
            print(f'  [{old_pos[b]} -> {new_pos[b]}] trend={float(nv.get("trend_score") or 0):.1f} {nv["title"][:44]}')

    # 验证倒挂修复：旧榜第1若 trend≈0（停滞），新榜应显著后移
    print()
    stagnant_first = next((v for v in videos if old_pos[v['bvid']] == 1 and (v.get('trend_score') or 0) < 20), None)
    if stagnant_first:
        b = stagnant_first['bvid']
        print(f'倒挂检查: 旧榜第1「{stagnant_first["title"][:30]}」trend={stagnant_first.get("trend_score", 0):.1f}（停滞），新榜第 {new_pos[b]} 名')
    else:
        print('倒挂检查: 旧榜第1 trend≥20，无停滞视频占榜首')
    rising_top = next((v for v in videos if new_pos[v['bvid']] <= 3 and (v.get('trend_score') or 0) >= 70), None)
    if rising_top:
        b = rising_top['bvid']
        print(f'爆发验证: 新榜前3「{rising_top["title"][:30]}」trend={rising_top.get("trend_score", 0):.1f}（爆发期），旧榜第 {old_pos[b]} 名')


if __name__ == '__main__':
    main()
