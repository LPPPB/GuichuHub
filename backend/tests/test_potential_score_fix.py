# -*- coding: utf-8 -*-
"""potential_score 修复回归测试（#1 并列满分失真 / #4 门槛与评分口径矛盾 / P0 趋势维度）

构造包含"高动能（高同接）"与"高转发"的 mock 数据，验证修复后的评分行为：
- #1：极端组合（批内双维度归一第一 + 新稿高同接）不再破 100 被 clamp，
      分数 ≤100；仅批内唯一第一可达满分 100（相对分语义），不会出现多个并列满分
      导致排序退化为原始发现顺序
- #4：转发型视频（shares 高、赞币藏低）不再被低估——评分 quality 维度与
      入池门槛 calc_engagement_quality 使用同一套权重（转发5 最高）
- P0：趋势维度（trend_score）作为第三维并列归一——累积数据相近时，
      增速快的视频排名更高，停滞老视频不再靠累积播放量压过爆发新视频
- 连带：score_material_batch 的新鲜度乘数同样封顶 1.0

注：2026-08-01 移除 kichu_fitness（适配度）后，评分不再含该乘法门控，
批内唯一第一理论上限即 100 分（相对分语义下正常，关键是不得并列）。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.scorer import score_potential_batch, score_material_batch

# 固定评估时刻（与真实抓取一样显式传 now，避免依赖系统时钟）
NOW = 1700000000


def mk(bvid, views, likes, coins, favs, shares, comments, danmaku,
       online, age_hours=20, trend=50):
    """构造一条候选视频（字段对齐 score_potential_batch 读取的键）。"""
    return {
        'bvid': bvid,
        'views': views,
        'likes': likes,
        'coins': coins,
        'favorites': favs,
        'shares': shares,
        'comments': comments,
        'danmaku': danmaku,
        'duration': 90,
        'pub_date': NOW - int(age_hours * 3600),
        'online_count': online,
        'trend_score': trend,
    }


# ==================== #1 并列满分失真 ====================

def test_extreme_video_single_full_score_no_saturation():
    """修复#1：极端视频分 ≤100 且批内唯一第一满分，不得破 100 被 clamp、不得并列。

    修复前：freshness(0.7~1.1)×online_factor(0.8~1.2) 乘积可达 1.32，分数破 100 被
    clamp 成并列满分，稳定排序退化为原始发现顺序；修复后动能补正封顶 1.0。
    """
    # v1 是批内绝对极端值：播放/互动/同接/趋势全部最高，且是 20 小时前的新稿
    v1 = mk('v1', 100000, 5000, 3000, 2000, 8000, 3000, 500, 500, age_hours=20, trend=95)
    v2 = mk('v2', 80000, 1000, 200, 150, 5000, 1500, 300, 300, age_hours=20, trend=60)
    v3 = mk('v3', 60000, 3000, 500, 400, 200, 500, 200, 50, age_hours=20, trend=40)
    v4 = mk('v4', 50000, 500, 100, 50, 100, 200, 100, 20, age_hours=20, trend=20)
    v5 = mk('v5', 40000, 300, 50, 30, 80, 100, 80, 10, age_hours=20, trend=5)
    cands = [v1, v2, v3, v4, v5]

    score_potential_batch(cands, NOW)

    scores = sorted((v['potential_score'] for v in cands), reverse=True)
    assert scores[0] <= 100, f'分数破 100 被 clamp: {scores[0]}'
    assert scores[0] == v1['potential_score'], '批内第一应拿最高分'
    assert len(set(scores)) == len(scores), f'出现并列分，排名锚定失真: {scores}'


def test_two_equal_extreme_videos_still_distinguishable():
    """修复#1：两个同样极端的视频在同一批内不因 clamp 并列满分。"""
    a = mk('a', 100000, 5000, 3000, 2000, 8000, 3000, 500, 500, age_hours=20, trend=90)
    b = mk('b', 90000, 4800, 2800, 1900, 7500, 2900, 480, 480, age_hours=20, trend=85)
    c = mk('c', 40000, 300, 50, 30, 80, 100, 80, 10, age_hours=20, trend=5)
    cands = [a, b, c]

    score_potential_batch(cands, NOW)

    assert a['potential_score'] <= 100 and b['potential_score'] <= 100
    assert a['potential_score'] != b['potential_score'], '两个极端视频并列满分，#1 未修复'


# ==================== P0 趋势维度 ====================

def test_trend_dimension_orders_rising_first():
    """P0：趋势维度生效——累积数据相近时，增速快的视频排名更高。

    修复前：heat=累积播放/互动、quality=累积互动率、freshness=发布年龄
    均不衡量"最近增速"，停滞老视频（trend=0）可凭累积量压过爆发新视频。
    修复后 trend 作为第三维并列归一：rising 与 stagnant 数据完全一致、
    仅 trend 不同 → rising 应显著领先（真实案例见归档：别信狗叫 trend=0
    排第1 vs 大狗老吴 trend=96.4 排第5）。
    """
    rising = mk('r', 60000, 2000, 500, 300, 1500, 800, 200, 200, age_hours=120, trend=90)
    stagnant = mk('s', 60000, 2000, 500, 300, 1500, 800, 200, 200, age_hours=120, trend=0)
    weak = mk('w', 50000, 300, 50, 30, 80, 100, 80, 10, age_hours=120, trend=10)
    cands = [rising, stagnant, weak]

    score_potential_batch(cands, NOW)

    assert rising['potential_score'] > stagnant['potential_score'], (
        f'爆发视频未领先停滞视频: rising={rising["potential_score"]} '
        f'<= stagnant={stagnant["potential_score"]}'
    )
    assert rising['potential_score'] <= 100, '趋势维度导致分数破 100'


# ==================== #4 门槛/评分口径矛盾 ====================

def test_share_heavy_video_not_underestimated():
    """修复#4：同播放、同接一致时，转发型视频不再被低估。

    批内 4 个视频激活 min-max 归一（n>=3）；互动率控制在 8% 满分线内避免 eq 饱和。
    修复前 quality 只算赞币藏：a 的赞币藏远低于 b → b 赢；
    修复后 quality 复用 calc_engagement_quality（转发×5 最高权重）→ a 双维度确认，赢。
    """
    share_heavy = mk('a', 500000, 100, 50, 20, 3000, 1000, 200, 100, age_hours=20)
    like_heavy = mk('b', 500000, 4000, 1500, 800, 50, 1000, 200, 100, age_hours=20)
    weak_c = mk('c', 500000, 800, 100, 50, 200, 300, 80, 50, age_hours=20)
    weak_d = mk('d', 500000, 300, 50, 20, 80, 100, 50, 30, age_hours=20)
    cands = [share_heavy, like_heavy, weak_c, weak_d]

    score_potential_batch(cands, NOW)

    assert share_heavy['potential_score'] > like_heavy['potential_score'], (
        f'转发型仍被低估：#4 未修复 '
        f'(share_heavy={share_heavy["potential_score"]} <= like_heavy={like_heavy["potential_score"]})'
    )


def test_engagement_quality_weighting():
    """修复#4 基础：calc_engagement_quality 中转发权重最高（5）。

    同播放量下，转发 3000 的视频 eq 分应高于点赞 4000 的视频（互动率均未饱和）。
    """
    from utils.scorer import calc_engagement_quality

    a = mk('a', 500000, 100, 50, 20, 3000, 1000, 200, 100)
    b = mk('b', 500000, 4000, 1500, 800, 50, 1000, 200, 100)
    eq_a = calc_engagement_quality(a)
    eq_b = calc_engagement_quality(b)
    assert eq_a > eq_b, f'转发权重未生效: eq_a={eq_a} <= eq_b={eq_b}'
    assert eq_a < 100 and eq_b < 100, '测试数据互动率过饱和，eq 被 clamp，无法验证权重'


# ==================== 连带：material_score 封顶 ====================

def test_material_score_capped_at_100():
    """连带修复：score_material_batch 新鲜度乘数封顶，极端素材分 ≤100 且不破上限。

    批内至少 3 条激活 min-max 归一（n<3 时退化 0.5，无法区分相对强弱）。
    """
    def mk_material(bvid, views, shares, comments, danmaku, age_hours=20):
        return {
            'bvid': bvid,
            'views': views,
            'shares': shares,
            'comments': comments,
            'danmaku': danmaku,
            'duration': 90,
            'pub_date': NOW - int(age_hours * 3600),
        }

    top = mk_material('m1', 1000000, 50000, 20000, 5000, age_hours=20)
    mid = mk_material('m2', 200000, 5000, 2000, 800, age_hours=20)
    weak = mk_material('m3', 50000, 100, 200, 100, age_hours=20)
    cands = [top, mid, weak]

    score_material_batch(cands, NOW)

    assert top['material_score'] <= 100, (
        f'素材分破 100 被 clamp: {top["material_score"]}'
    )
    assert top['material_score'] > mid['material_score'] > weak['material_score']


# ==================== L1/L2 同接失真修复 ====================

def test_online_batch_relative_factor():
    """L1：同接指数批内相对归一——同一批内同接率更高者获得更高动能乘数。

    修复前：online_factor 用绝对指数（0.8+0.4×idx/100），整批同接都高（晚间高峰）
    或都低（凌晨）时乘数趋同、无区分；修复后按批内相对值，时段效应批内抵消。
    hot/mild/cold 的播放、互动、趋势完全一致，仅同接率不同 → 分数差纯由同接驱动。
    用 12 天龄数据使 momentum 不封顶（freshness≈0.871），保证乘数差异可见。
    """
    hot = mk('h', 100000, 1000, 200, 150, 500, 800, 200, 5000, age_hours=288, trend=50)
    mild = mk('m', 100000, 1000, 200, 150, 500, 800, 200, 500, age_hours=288, trend=50)
    cold = mk('c', 100000, 1000, 200, 150, 500, 800, 200, 20, age_hours=288, trend=50)
    cands = [hot, mild, cold]

    score_potential_batch(cands, NOW)

    assert hot['potential_score'] > mild['potential_score'] > cold['potential_score'], (
        f'同接批内相对化未生效: hot={hot["potential_score"]} '
        f'mild={mild["potential_score"]} cold={cold["potential_score"]}'
    )


def test_online_high_failure_ratio_fuses_neutral():
    """L1：同接抓取失败率 >50%（风控/接口故障）时整轮中性化。

    修复前：成功视频拿动能加成、失败视频中性 → 同批标准不统一，排名失真。
    修复后：失败率 >50% 判定数据不可靠，全部 ×1.0 中性（放弃动能维度）。
    """
    ok = mk('a', 100000, 1000, 200, 150, 500, 800, 200, 5000, age_hours=288, trend=50)
    f1 = mk('b', 100000, 1000, 200, 150, 500, 800, 200, 50, age_hours=288, trend=50)
    f1['online_count'] = None
    f2 = mk('c', 100000, 1000, 200, 150, 500, 800, 200, 50, age_hours=288, trend=50)
    f2['online_count'] = None
    cands = [ok, f1, f2]  # 失败率 2/3 ≈ 66.7% > 50%

    score_potential_batch(cands, NOW)

    scores = [v['potential_score'] for v in cands]
    assert len(set(scores)) == 1, f'熔断未生效，分数未中性化: {scores}'


def test_online_weights_latest_dominant():
    """L2：同接滑动窗口权重最新轮占比最大（3 轮 0.5/0.3/0.2）。"""
    from collectors.bilibili import _online_weights
    assert _online_weights(1) == [1.0]
    assert _online_weights(2) == [0.4, 0.6]
    assert _online_weights(3) == [0.2, 0.3, 0.5]


def test_smooth_online_uses_history_and_skips_failures(monkeypatch):
    """L2：平滑值 = 历史加权 + 本轮；失败轮（None）不参与，不拉低不抬高。"""
    import collectors.bilibili as b

    monkeypatch.setattr(b, 'get_video_obs_trend',
                        lambda bvid, hours=48: [
                            {'online_count': 100},
                            {'online_count': 200},
                            {'online_count': None},  # 失败轮跳过
                        ])
    # 历史最近2条 [100, 200] + 本轮 400 → 权重 [0.2, 0.3, 0.5] → 20+60+200=280
    assert b._smooth_online('BV1', 400) == 280
    # 本轮失败（None）→ 回退历史 [100, 200] → 权重 [0.4, 0.6] → 40+120=160
    assert b._smooth_online('BV1', None) == 160
    # 冷启动：无历史 → 返回本轮原值
    monkeypatch.setattr(b, 'get_video_obs_trend', lambda bvid, hours=48: [])
    assert b._smooth_online('BV1', 300) == 300
    assert b._smooth_online('BV1', None) is None


# ==================== extra：超上限已火视频外推潜力分（2026-08-02） ====================

def test_extra_over_cap_gets_score_without_joining_candidates():
    """超播放上限视频：用候选池边界外推潜力分写入自身，但候选列表不变。

    用户需求：超过 100 万播放上限的"已火"视频，若已有观测数据仍计算潜力分并写入
    （供鬼畜区排行榜展示，卡片分数不再为空），潜力评分榜仍将其过滤（extra 不进
    candidates）。extra 不参与批内归一——否则 295 万播放会把整批 heat 压扁。
    """
    v1 = mk('v1', 100000, 5000, 3000, 2000, 8000, 3000, 500, 500, age_hours=20, trend=95)
    v2 = mk('v2', 80000, 1000, 200, 150, 5000, 1500, 300, 300, age_hours=20, trend=60)
    v3 = mk('v3', 60000, 3000, 500, 400, 200, 500, 200, 50, age_hours=20, trend=40)
    cands = [v1, v2, v3]
    over_cap = mk('hot1', 3000000, 20000, 8000, 5000, 30000, 10000, 2000, 500,
                  age_hours=20, trend=90)

    score_potential_batch(cands, NOW, extra=[over_cap])

    # 超限视频拿到潜力分（且不超过 100，不被 clamp）
    assert over_cap.get('potential_score') is not None
    assert 0 <= over_cap['potential_score'] <= 100
    # 候选也全部拿到分数
    assert all(v['potential_score'] is not None for v in cands)


def test_extra_does_not_affect_candidate_scores():
    """extra 不参与批内归一 → 候选分数与不带 extra 时完全一致。"""
    def build():
        return [
            mk('v1', 100000, 5000, 3000, 2000, 8000, 3000, 500, 500, age_hours=20, trend=95),
            mk('v2', 80000, 1000, 200, 150, 5000, 1500, 300, 300, age_hours=20, trend=60),
            mk('v3', 60000, 3000, 500, 400, 200, 500, 200, 50, age_hours=20, trend=40),
        ]
    base = build()
    score_potential_batch(base, NOW)
    with_extra = build()
    score_potential_batch(with_extra, NOW, extra=[
        mk('hot1', 3000000, 20000, 8000, 5000, 30000, 10000, 2000, 500,
           age_hours=20, trend=90)
    ])
    for a, b in zip(base, with_extra):
        assert a['potential_score'] == b['potential_score'], (
            f'extra 污染了候选归一: {a["bvid"]} {a["potential_score"]} != {b["potential_score"]}'
        )


def test_extra_without_online_neutral_factor():
    """extra 无历史同接（online_count=None）→ 同接中性 ×1.0，分数仍可计算。"""
    v1 = mk('v1', 100000, 5000, 3000, 2000, 8000, 3000, 500, 500, age_hours=20, trend=95)
    v2 = mk('v2', 80000, 1000, 200, 150, 5000, 1500, 300, 300, age_hours=20, trend=60)
    v3 = mk('v3', 60000, 3000, 500, 400, 200, 500, 200, 50, age_hours=20, trend=40)
    over_no_obs = mk('hot2', 2500000, 15000, 6000, 4000, 20000, 8000, 1500, 400,
                     age_hours=20, trend=85)
    over_no_obs['online_count'] = None  # 无观测数据

    score_potential_batch([v1, v2, v3], NOW, extra=[over_no_obs])

    assert over_no_obs.get('potential_score') is not None
    assert 0 <= over_no_obs['potential_score'] <= 100
