import re
import math

from config import (
    ONLINE_INDEX_THRESHOLD, ONLINE_FACTOR_BASE, ONLINE_FACTOR_WEIGHT,
    ONLINE_TARGET_RATE, ONLINE_MIN_SIGNIFICANT, ONLINE_CURVE_POWER,
    POTENTIAL_VIEWS_MAX, POTENTIAL_VIEWS_MIN,
    POTENTIAL_ENGAGEMENT_MIN, POTENTIAL_AGE_DAYS,
    MATERIAL_VIEWS_MIN, MATERIAL_AGE_DAYS,
)

def calc_trend_score(views, likes, coins, favorites, shares, comments, danmaku, pub_date_timestamp):
    import time
    now = time.time()
    hours_passed = max(1, (now - pub_date_timestamp) / 3600)
    
    views_per_hour = views / hours_passed
    
    # 互动权重与 calc_engagement_quality 单一真源一致（转发5 > 弹幕2.5 = 评论2 = 投币2 > 收藏1.5 > 点赞1），
    # 避免同一"互动质量"概念多处权重漂移导致榜单口径矛盾。
    total_engagement = (likes * 1.0 + coins * 2.0 + favorites * 1.5
                        + shares * 5.0 + comments * 2.0 + danmaku * 2.5)
    engagement_rate = total_engagement / max(views, 1) * 100
    
    virality_score = min(100, views_per_hour / 5000 * 40 + engagement_rate * 15)
    
    decay = max(0, 1 - (hours_passed / 168) * 0.5)
    final_score = virality_score * decay
    
    return min(100, max(0, round(final_score, 1)))

def get_trend_label(trend_score):
    if trend_score >= 70:
        return '爆发期'
    elif trend_score >= 45:
        return '上升期'
    elif trend_score >= 20:
        return '平稳期'
    else:
        return '衰退期'

def calc_meme_heat(related_views, video_count, engagement_sum):
    base = related_views * 0.1 + video_count * 5000 + engagement_sum * 0.5
    return int(base)


def is_potential_candidate(video, now=None):
    """判断视频是否适合进入"鬼畜潜力视频"候选池。

    硬门槛过滤：排除已经爆火的大视频、过冷门的噪声视频、
    无互动的旧视频。"非鬼畜拦截"由分区硬约束（tid∈KICHU_TIDS）承担。
    门槛参数全部来自 config.py（POTENTIAL_*），可 .env 调优。
    """
    import time
    now = now or time.time()

    views = int(video.get('views') or 0)
    pub = video.get('pub_date') or 0
    engagement = calc_engagement_quality(video)

    if views < POTENTIAL_VIEWS_MIN:
        return False
    if views > POTENTIAL_VIEWS_MAX:  # 超过上限=已经火了，不再是潜力（config可调）
        return False
    if engagement < POTENTIAL_ENGAGEMENT_MIN:
        return False
    if pub == 0:
        return False
    if (now - pub) > POTENTIAL_AGE_DAYS * 86400:
        return False
    return True


def calc_engagement_quality(video):
    """计算视频综合互动质量（0-100）。

    转发权重较高，因为搞笑/鬼畜类视频常被大量转发。
    """
    views = max(1, int(video.get('views') or 0))
    likes = int(video.get('likes') or 0)
    coins = int(video.get('coins') or 0)
    favorites = int(video.get('favorites') or 0)
    shares = int(video.get('shares') or 0)
    comments = int(video.get('comments') or 0)
    danmaku = int(video.get('danmaku') or 0)

    # 加权总互动量，转发权重最高
    total_engagement = (
        likes * 1.0 +
        coins * 2.0 +
        favorites * 1.5 +
        shares * 5.0 +
        comments * 2.0 +
        danmaku * 2.5
    )

    engagement_rate = total_engagement / views

    # 8% 加权互动率视为满分（鬼畜视频互动通常较高）
    TARGET_RATE = 0.08
    score = engagement_rate / TARGET_RATE * 100
    return round(min(100, max(0, score)), 1)


def calc_online_index(video):
    """计算同接指数（0-100），反映视频当下的传播动能。

    两项改进 over 纯线性比值：
    1. 噪声过滤：同接数 < ONLINE_MIN_SIGNIFICANT 视为偶发噪声（UP主自检/单点点击），
       不足以判断传播状态，直接归零。避免"6K播放+1同接"拿满分。
    2. 幂次曲线：用 ONLINE_CURVE_POWER 控制映射弧度（默认 0.7），
       让中段更敏感——0.5%同接率线性只得50分，0.7次方得62分，更贴合"不少了"的体感。

    用比值而非绝对数：1万播放+100同接（1%）是起飞，200万播放+50同接（0.0025%）是衰退。
    """
    views = max(1, int(video.get('views') or 0))
    online_count = int(video.get('online_count') or 0)

    if online_count < ONLINE_MIN_SIGNIFICANT:
        return 0.0

    online_rate = online_count / views
    raw_score = (online_rate / ONLINE_TARGET_RATE) ** ONLINE_CURVE_POWER * 100
    return round(min(100, max(0, raw_score)), 1)


def _minmax_bounds(values):
    """批内 Min-Max 归一参考边界 (lo, hi)。

    样本过少（<3）或极差为零时返回 None——归一无区分度，
    退化为 0.5 中位（见 _batch_minmax/_minmax_apply）。
    """
    n = len(values)
    if n < 3:
        return None
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return None
    return (lo, hi)


def _minmax_apply(value, bounds):
    """用批内边界外推归一（越界裁剪到 [0,1]）；无边界时退化 0.5。

    供 score_potential_batch 的 extra 视频使用：extra（超播放上限的已火视频）
    不参与批内归一（否则 295 万播放会把整批 heat 压扁），用候选池边界外推，
    保证分数与榜单同口径、可比。
    """
    if bounds is None:
        return 0.5
    lo, hi = bounds
    return min(1.0, max(0.0, (value - lo) / (hi - lo)))


def _batch_minmax(values):
    """批内 Min-Max 归一到 0~1。

    样本过少或极差为零时退化为 0.5（中位），避免除零及
    单视频榜单出现全满分/全零分。
    """
    bounds = _minmax_bounds(values)
    if bounds is None:
        return [0.5] * len(values)
    lo, hi = bounds
    return [(v - lo) / (hi - lo) for v in values]


def score_potential_batch(candidates, now=None, extra=None):
    """批量计算潜力指数，就地写入每个视频的 potential_score（0-100）。

    借鉴哈基米音乐排行榜算法：ln 平滑 + 批内 Min-Max 归一 +
    热度/质量/趋势三维拆分 + 乘法新鲜度 + 同接补正。
    趋势维度（trend_score，内含 14 天 decay 窗口）衡量"最近增速"，
    修正历史缺陷：heat=累积播放/互动让停滞老视频靠时间堆积排前列，
    而爆发新视频因累积量小被压后（真实案例见归档 P0）。
    分数是批内相对值，仅用于本期榜单排序，跨期不可比。

    extra（可选）：不参与批内归一的附加视频——用于超播放上限 POTENTIAL_VIEWS_MAX
    的"已火"视频。它们不进潜力榜（是否上榜由调用方候选过滤决定），但若调用方有
    历史观测数据（已填 online_count），仍用候选池批内边界外推潜力分写入自身，
    保证与榜单同口径、可供展示。extra 的同接缺失/批内同接不可靠时中性 ×1.0；
    candidates 为空（无归一参照）时 extra 不计算。
    """
    import time
    now = now or time.time()
    if not candidates:
        return candidates

    heat_raw = []
    quality_raw = []
    trend_raw = []
    for v in candidates:
        views = int(v.get('views') or 0)
        shares = int(v.get('shares') or 0)
        comments = int(v.get('comments') or 0)
        danmaku = int(v.get('danmaku') or 0)
        duration = max(1, int(v.get('duration') or 0))
        # 热度 = 传播向(转发/评论/弹幕密度)均值 × 播放体量，全部 ln 平滑
        spread = (math.log(shares + 1) + math.log(comments + 1)
                  + math.log(danmaku / duration + 1)) / 3
        heat_raw.append(spread * math.log(views + 1))

        # 质量 = 综合互动率：直接复用入池门槛 calc_engagement_quality 的权重
        # （转发5 > 弹幕2.5 = 评论2 = 投币2 > 收藏1.5 > 点赞1，除以播放与体量无关），
        # 保证"门槛认什么、评分就认什么"。历史矛盾（#4）：门槛给转发最高权重，
        # 评分却只算赞币藏，导致转发型爆款过得了门槛却在评分里被低估。
        # 复用同一函数作为唯一真源，避免两处权重日后漂移。
        quality_raw.append(math.log(calc_engagement_quality(v) + 1))

        # 趋势 = 最近增速（trend_score 已随 _build_video_dict 写入每个视频，
        # 且 _enrich_with_stats 用真实 stat 重算过）。对缺字段视频取 0（中性偏低，
        # 未知增速不视为高潜力）。trend_score 自带 decay 使 14 天前视频趋 0，
        # 天然压制"增长停滞的老视频"靠累积播放量刷热度。
        trend_raw.append(max(0.0, float(v.get('trend_score') or 0)))

    heat_n = _batch_minmax(heat_raw)
    quality_n = _batch_minmax(quality_raw)
    trend_n = _batch_minmax(trend_raw)

    # 同接（L1 批内相对化 + 失败熔断）：
    # - 同接是单时刻瞬时采样，时段效应大（晚间高峰/凌晨低谷）。同批视频同一时刻采样，
    #   时段效应在批内抵消 → 同接指数改为批内 min-max 归一，只看"谁在同批里更火"。
    # - None（抓取失败/未知）不参与归一；但若同批失败率 >50%（风控/接口故障）或有效样本
    #   <3（minmax 退化无区分度），判定数据不可靠，整轮中性化（全部 ×1.0）。
    #   否则"成功视频有动能加成、失败视频中性"会造成同批标准不统一。
    # - 判定基于平滑值 online_count（L2 跨轮加权，非本轮实测 raw）：熔断/单点抓取失败时，
    #   有历史观测的视频回退平滑历史继续参与归一（历史是真实观测，不应降级）；
    #   无历史的才归 None → 整轮中性化兜底。online_circuit_skipped 仅作可观测性标记
    #   （前端/日志展示"熔断跳过"），不参与评分——评分只看有没有可用的平滑值。
    online_idx_raw = [calc_online_index(v) for v in candidates
                      if v.get('online_count') is not None]
    none_ratio = 1 - len(online_idx_raw) / max(1, len(candidates))
    online_reliable = none_ratio <= 0.5 and len(online_idx_raw) >= 3
    online_n_map = {}
    if online_reliable:
        online_n = _batch_minmax(online_idx_raw)
        online_n_map = {
            v['bvid']: r
            for v, r in zip(
                [v for v in candidates if v.get('online_count') is not None],
                online_n,
            )
        }

    # 归一参考边界：extra（超上限已火视频）用候选池边界外推，不参与归一
    # （否则 295 万播放的视频会把整批 heat 归一压扁，榜单失真）
    heat_bounds = _minmax_bounds(heat_raw)
    quality_bounds = _minmax_bounds(quality_raw)
    trend_bounds = _minmax_bounds(trend_raw)
    online_bounds = _minmax_bounds(online_idx_raw) if online_reliable else None

    for v, heat, quality, trend in zip(candidates, heat_n, quality_n, trend_n):
        pub = v.get('pub_date') or now
        age_days = max(0.0, (now - pub) / 86400)
        # 新鲜度乘数：新稿 1.1，21 天线性衰减到 0.7（候选池龄期上限即 21 天）
        freshness = 1.1 - 0.4 * min(age_days / 21, 1.0)
        # 同接补正：连续乘数，按传播动能调节
        # 同接指数 0 → 动能不足（×0.8 降权）；同接指数 100 → 动能强劲（×1.2 加成）
        # A2: online_count 为 None（抓取失败/未知）时取中性 ×1.0，不奖不罚——
        #     "没抓到数据"不应被误判为"没人看"
        # L1: 指数做批内相对归一，映射 0.8~1.2；熔断（失败率>50%/样本<3）时全部中性
        if not online_reliable or v.get('online_count') is None:
            online_factor = 1.0
        else:
            online_factor = (ONLINE_FACTOR_BASE
                             + ONLINE_FACTOR_WEIGHT * online_n_map.get(v['bvid'], 0.5))

        # 热度/质量/趋势各占三分之一，合成 0~1 基底后再乘补正，避免乘数叠加上限饱和。
        # 动能补正封顶 1.0（#1）：freshness(0.7~1.1) × online_factor(0.8~1.2)
        # 乘积理论上限 1.32，直接相乘时"批内双维度归一第一 + 新稿高同接"
        # 会破 100 被 clamp，榜单头部出现并列满分、排序退化为原始发现顺序。
        momentum = min(freshness * online_factor, 1.0)
        score = (heat + quality + trend) / 3 * momentum * 100
        v['potential_score'] = round(min(100, max(0, score)), 1)

    # extra：超播放上限的"已火"视频——不进潜力榜（调用方候选过滤决定），但保留展示分数。
    # 用候选池批内边界外推（_minmax_apply 裁剪越界），同接来自调用方填入的历史观测
    # online_count（无观测/批内同接不可靠时中性 ×1.0，与候选池 A2/L1 语义一致）。
    for v in extra or []:
        views = int(v.get('views') or 0)
        shares = int(v.get('shares') or 0)
        comments = int(v.get('comments') or 0)
        danmaku = int(v.get('danmaku') or 0)
        duration = max(1, int(v.get('duration') or 0))
        # 与候选池同款热度/质量/趋势公式，仅归一改为边界外推
        spread = (math.log(shares + 1) + math.log(comments + 1)
                  + math.log(danmaku / duration + 1)) / 3
        heat = _minmax_apply(spread * math.log(views + 1), heat_bounds)
        quality = _minmax_apply(math.log(calc_engagement_quality(v) + 1), quality_bounds)
        trend = _minmax_apply(max(0.0, float(v.get('trend_score') or 0)), trend_bounds)

        pub = v.get('pub_date') or now
        age_days = max(0.0, (now - pub) / 86400)
        freshness = 1.1 - 0.4 * min(age_days / 21, 1.0)
        if online_bounds is None or v.get('online_count') is None:
            online_factor = 1.0
        else:
            online_n = _minmax_apply(calc_online_index(v), online_bounds)
            online_factor = ONLINE_FACTOR_BASE + ONLINE_FACTOR_WEIGHT * online_n
        momentum = min(freshness * online_factor, 1.0)
        score = (heat + quality + trend) / 3 * momentum * 100
        v['potential_score'] = round(min(100, max(0, score)), 1)

    return candidates


def get_potential_reason(video, now=None):
    """生成前端展示的潜力理由标签。"""
    import time
    now = now or time.time()

    views = int(video.get('views') or 0)
    pub = video.get('pub_date') or now
    hours = max(1, (now - pub) / 3600)
    engagement = calc_engagement_quality(video)
    online_index = calc_online_index(video)

    if online_index >= ONLINE_INDEX_THRESHOLD:
        return '正在热播'
    if engagement >= 60:
        return '互动爆款'
    if hours <= 48 and views < 100_000:
        return '新发高潜'
    if views < 50_000:
        return '小众宝藏'
    return '综合潜力'


def extract_keywords_from_title(title):
    keywords = []
    
    patterns = [
        r'【([^】]+)】',
        r'「([^」]+)」',
        r'『([^』]+)』',
        r'"([^"]+)"',
        r'([^\s，。、！？,.!?]{2,6}哥)',
        r'([^\s，。、！？,.!?]{2,6}姐)',
        r'([^\s，。、！？,.!?]{2,6}侠)',
        r'([^\s，。、！？,.!?]{2,6}帝)',
        r'([^\s，。、！？,.!?]{2,6}神)',
        r'([^\s，。、！？,.!?]{2,6}之王)',
        r'([^\s，。、！？,.!?]{2,6}名场面)',
        r'([^\s，。、！？,.!?]{2,6}神曲)',
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, title)
        for m in matches:
            if len(m) >= 2 and len(m) <= 15:
                keywords.append(m)

    return list(set(keywords))


# ==================== 鬼畜素材发掘（板块2） ====================
# 与"潜力视频"的区别：
#   潜力视频 = 已是鬼畜视频，预测它自身能否爆火（用同接动能、限播放上限）
#   素材发掘 = 非鬼畜视频（音乐/搞笑区），评估它能否被二创成鬼畜并火
#             → 原素材越火越好（受众大），不用同接，时效窗口更宽

def is_material_candidate(video, now=None):
    """判断视频是否适合进入"鬼畜素材发掘"候选池。

    与潜力视频候选池的差异：
    - 不设播放量上限：原素材越火，二创潜在受众越大（百万播放的素材反而是好素材）
    - 素材来自音乐/搞笑区（非鬼畜），评分只看素材自身热度与传播性，不衡量鬼畜维度
    - 时效窗口更宽：素材二创周期比爆款预测长（MATERIAL_AGE_DAYS=60 天 vs 21 天）
    - 不设互动质量门槛：原素材的互动率与二创潜力不直接挂钩
    门槛参数全部来自 config.py（MATERIAL_*），可 .env 调优。
    """
    import time
    now = now or time.time()

    views = int(video.get('views') or 0)
    pub = video.get('pub_date') or 0

    if views < MATERIAL_VIEWS_MIN:
        return False
    if pub == 0:
        return False
    if (now - pub) > MATERIAL_AGE_DAYS * 86400:
        return False
    return True


def score_material_batch(candidates, now=None):
    """批量计算"鬼畜素材潜力指数"，就地写入 material_score（0-100）。

    面向音乐区/搞笑区视频，评估作为鬼畜二创素材的潜力。
    核心差异 vs 潜力视频算法：
    - 素材热度正向加分（原素材越火，二创潜在受众越大），不做上限过滤
    - 不使用同接补正（同接预测视频自身增长动能，与素材二创潜力无关）
    - 新鲜度时效窗口更长（素材可二创周期 60 天，比爆款预测 21 天宽）
    分数是批内相对值，仅用于本期榜单排序，跨期不可比。
    """
    import time
    import math
    now = now or time.time()
    if not candidates:
        return candidates

    heat_raw = []
    spread_raw = []
    for v in candidates:
        views = int(v.get('views') or 0)
        shares = int(v.get('shares') or 0)
        comments = int(v.get('comments') or 0)
        danmaku = int(v.get('danmaku') or 0)
        duration = max(1, int(v.get('duration') or 0))

        # 素材热度 = 播放体量（ln 平滑），原素材越火二创受众越大
        heat_raw.append(math.log(views + 1))

        # 传播性 = 转发/评论/弹幕密度均值（ln 平滑），引发共鸣的内容更适合二创
        spread = (math.log(shares + 1) + math.log(comments + 1)
                  + math.log(danmaku / duration + 1)) / 3
        spread_raw.append(spread)

    heat_n = _batch_minmax(heat_raw)
    spread_n = _batch_minmax(spread_raw)

    for v, heat, spread in zip(candidates, heat_n, spread_n):
        pub = v.get('pub_date') or now
        age_days = max(0.0, (now - pub) / 86400)
        # 新鲜度乘数：新稿 1.15，60 天线性衰减到 0.75（素材二创周期比爆款预测宽）
        freshness = 1.15 - 0.4 * min(age_days / 60, 1.0)

        # 热量+传播性各占一半合成 0~1 基底，再乘新鲜度。
        # 新鲜度乘数封顶 1.0（#1 同类问题）：freshness 上限 1.15 会让
        # "双维度归一第一 + 新素材"破 100 被 clamp，产生并列满分。
        score = (0.5 * heat + 0.5 * spread) * min(freshness, 1.0) * 100
        v['material_score'] = round(min(100, max(0, score)), 1)

    return candidates


def get_material_reason(video, now=None):
    """生成素材发掘的前端展示理由标签。"""
    import time
    now = now or time.time()

    views = int(video.get('views') or 0)
    pub = video.get('pub_date') or now
    hours = max(1, (now - pub) / 3600)
    shares = int(video.get('shares') or 0)
    comments = int(video.get('comments') or 0)

    if views >= 500_000 and hours <= 168:
        return '热门原素材'
    if shares >= 500 or comments >= 1000:
        return '高传播素材'
    if hours <= 72:
        return '新发素材'
    if views >= 200_000:
        return '大众熟知'
    return '潜力素材'
