# -*- coding: utf-8 -*-
"""双轨验证：对比库中已落库的 potential_score（旧算法基线）与重算分数。

读取 data/inspiration_db.json 中最近一次抓取的 hot_videos（含旧算法落库的
potential_score 作为旧榜基线），用新算法重算并对比排名。

注意：库中 hot_videos 是旧算法筛完的 Top30，并非完整候选池，批内归一的
样本集比线上略小，排名对比仅供参考趋势，绝对分数不可直接等价。
另外，本脚本只在"下次爬虫运行之前"有效——爬虫改用新算法后，库中
potential_score 就是新算法的分数，新旧对比将失去意义。
"""
import sys
import os
import json
import copy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')

from utils.scorer import score_potential_batch


def spearman(rank_a, rank_b):
    """两个排名列表（同序对应）的 Spearman 相关系数。"""
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

    # 旧榜：按库中已落库的 potential_score 排名
    old_rank = sorted(range(len(videos)),
                      key=lambda i: videos[i].get('potential_score', 0),
                      reverse=True)

    # 新榜：新算法重算（在副本上跑，不改库文件）
    new_videos = copy.deepcopy(videos)
    score_potential_batch(new_videos)
    new_rank = sorted(range(len(new_videos)),
                      key=lambda i: new_videos[i]['potential_score'],
                      reverse=True)

    # bvid -> 新/旧名次
    old_pos = {videos[i]['bvid']: pos + 1 for pos, i in enumerate(old_rank)}
    new_pos = {new_videos[i]['bvid']: pos + 1 for pos, i in enumerate(new_rank)}

    print(f'样本: {len(videos)} 条（旧算法 Top30 子集）')
    print(f'Spearman 排名相关: {spearman([old_pos[new_videos[i]["bvid"]] for i in new_rank], list(range(1, len(new_rank) + 1))):.3f}')
    print()
    print(f'{"新榜":>4} {"旧榜":>4} {"变化":>6} {"旧分":>6} {"新分":>6}  标题')
    print('-' * 90)
    for pos, i in enumerate(new_rank, 1):
        nv = new_videos[i]
        old_score = next(v.get('potential_score', 0) for v in videos if v['bvid'] == nv['bvid'])
        op = old_pos[nv['bvid']]
        delta = op - pos
        mark = f'{delta:+d}' if delta else '·'
        title = nv['title'][:38]
        print(f'{pos:>4} {op:>4} {mark:>6} {old_score:>6} {nv["potential_score"]:>6}  {title}')

    new_in = [b for b in new_pos if new_pos[b] <= 10 and old_pos[b] > 10]
    dropped = [b for b in old_pos if old_pos[b] <= 10 and new_pos[b] > 10]
    print()
    if new_in:
        print('新进入 Top10:')
        for b in new_in:
            v = next(v for v in new_videos if v['bvid'] == b)
            print(f'  [{old_pos[b]} -> {new_pos[b]}] {v["title"][:50]}')
    if dropped:
        print('跌出 Top10:')
        for b in dropped:
            v = next(v for v in new_videos if v['bvid'] == b)
            print(f'  [{old_pos[b]} -> {new_pos[b]}] {v["title"][:50]}')


if __name__ == '__main__':
    main()
