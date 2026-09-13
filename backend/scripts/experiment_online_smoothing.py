# -*- coding: utf-8 -*-
"""实验：平滑同接（L2）对最近 24h 真实视频数据排名的影响。

数据：data/inspiration_db.json 的 hot_videos（最近一次抓取候选池子集，
JSON 中的 online_count 是那轮抓取的单点实测值）+ video_obs 表最近 24h 历史序列。

对比：
- 单点榜：online_count = 本轮实测单点值（旧逻辑，受单时刻采样/失败影响）
- 平滑榜：online_count = _smooth_online(bvid, 本轮值)（新逻辑，跨轮滑动加权 0.5/0.3/0.2）

预期：
- 有历史序列的视频：单点异常值被平滑拉回，排名更稳
- 单点失败（None）的视频：有历史时回退历史，不再被误判为"没人看"
- 无历史（冷启动）的视频：退化为单点，排名不变

运行：cd backend && .\\.venv\\Scripts\\python.exe scripts/experiment_online_smoothing.py
"""
import sys
import os
import json
import copy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')

from utils.scorer import score_potential_batch
from collectors.bilibili import _smooth_online
from storage.db import get_video_obs_trend


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

    now = max(int(v.get('pub_date') or 0) for v in videos) + 86400

    # 计算每条视频的 单点值 / 平滑值 / 历史点数
    raw_map, smooth_map, hist_map = {}, {}, {}
    for v in videos:
        raw = v.get('online_count')  # JSON 存的是该轮实测单点值
        history = get_video_obs_trend(v['bvid'], hours=24)
        hist_pts = [h['online_count'] for h in history if h.get('online_count') is not None]
        raw_map[v['bvid']] = raw
        smooth_map[v['bvid']] = _smooth_online(v['bvid'], raw, hours=24)
        hist_map[v['bvid']] = len(hist_pts)

    def build(online_of):
        out = copy.deepcopy(videos)
        for v in out:
            v['online_count'] = online_of[v['bvid']]
        score_potential_batch(out, now)
        return out

    old_videos = build(raw_map)
    new_videos = build(smooth_map)

    old_rank = sorted(range(len(old_videos)), key=lambda i: old_videos[i]['potential_score'], reverse=True)
    new_rank = sorted(range(len(new_videos)), key=lambda i: new_videos[i]['potential_score'], reverse=True)
    old_pos = {old_videos[i]['bvid']: pos + 1 for pos, i in enumerate(old_rank)}
    new_pos = {new_videos[i]['bvid']: pos + 1 for pos, i in enumerate(new_rank)}

    n = len(videos)
    n_hist = sum(1 for b in hist_map if hist_map[b] > 0)
    print(f'样本: {n} 条 hot_videos；有 24h 历史观测序列: {n_hist} 条；无历史(冷启动): {n - n_hist} 条')
    print(f'Spearman(单点榜 vs 平滑榜): '
          f'{spearman([old_pos[new_videos[i]["bvid"]] for i in new_rank], list(range(1, n + 1))):.3f}')
    print()

    print(f'{"新榜":>4} {"旧榜":>4} {"位移":>5} {"单点":>6} {"平滑":>6} {"史":>2}  标题')
    print('-' * 96)
    for pos, i in enumerate(new_rank, 1):
        nv = new_videos[i]
        b = nv['bvid']
        op = old_pos[b]
        delta = op - pos
        mark = f'{delta:+d}' if delta else '·'
        raw = raw_map[b]
        sm = smooth_map[b]
        r = 'None' if raw is None else f'{raw}'
        s = 'None' if sm is None else f'{sm}'
        title = nv['title'][:38]
        print(f'{pos:>4} {op:>4} {mark:>5} {r:>6} {s:>6} {hist_map[b]:>2}  {title}')

    new_in = [b for b in new_pos if new_pos[b] <= 10 and old_pos[b] > 10]
    dropped = [b for b in old_pos if old_pos[b] <= 10 and new_pos[b] > 10]
    print()
    if new_in:
        print(f'新进入 Top10（{len(new_in)} 条）:')
        for b in new_in:
            nv = next(v for v in new_videos if v['bvid'] == b)
            print(f'  [{old_pos[b]} -> {new_pos[b]}] 单点={raw_map[b]} 平滑={smooth_map[b]} 史={hist_map[b]} {nv["title"][:40]}')
    if dropped:
        print(f'跌出 Top10（{len(dropped)} 条）:')
        for b in dropped:
            nv = next(v for v in new_videos if v['bvid'] == b)
            print(f'  [{old_pos[b]} -> {new_pos[b]}] 单点={raw_map[b]} 平滑={smooth_map[b]} 史={hist_map[b]} {nv["title"][:40]}')

    # 平滑效果最大案例：单点与平滑差异最大的前 5
    print()
    diffs = [(b, abs((raw_map[b] or 0) - (smooth_map[b] or 0))) for b in raw_map]
    diffs = sorted(diffs, key=lambda x: x[1], reverse=True)[:5]
    print('单点→平滑变化最大的 5 条:')
    for b, d in diffs:
        nv = next(v for v in new_videos if v['bvid'] == b)
        print(f'  单点={raw_map[b]} -> 平滑={smooth_map[b]} (Δ{d}) 史={hist_map[b]} [{old_pos[b]}->{new_pos[b]}] {nv["title"][:38]}')


if __name__ == '__main__':
    main()
