import requests
import time
import os
import html
from collections import Counter
from collectors.bilibili_auth import get_cookie_str, get_headers, get_user_info, safe_get_with_wbi
from collectors.bilibili import parse_video_item, fetch_video_detail, KICHU_TIDS, _to_int_tid
from utils.scorer import calc_trend_score, get_trend_label

CONTENT_TYPES = {
    '调音': ['调音', '音准', 'autotune', 'auto-tune', '声卡', 'VOCALOID', 'vocal', '歌声合成', 'UTAU', 'SynthesizerV', 'synthv', 'SV'],
    '混剪': ['混剪', '踩点', '卡点', 'MAD', 'MAD·AMV', 'AMV', 'medley', '串烧', 'remix', '缝合'],
    'RAP': ['rap', 'RAP', 'Rap', '说唱', 'hiphop', 'freestyle', 'punchline'],
    '空耳': ['空耳', '谐音鬼畜', '字幕鬼畜', '整活字幕'],
    '鬼畜': ['鬼畜', '鬼畜调教', '鬼畜大赏', '循环洗脑', 'rap鬼畜', '鬼畜rap', '人力鬼畜', '音MAD'],
    '恶搞': ['恶搞', '恶趣味', '迫害'],
    '影视': ['电影', '电视剧', '番剧', '二创'],
    '游戏': ['实况', 'speedrun', '速通'],
    '素材': ['绿幕', '透明素材', '抠图', '素材分享'],
    '教程': ['教程', '教学', '技巧入门'],
}

# 停用词表已迁移到 utils/stopwords.py（统一管理 700+ 中文虚词 + 平台噪声词 + clean_text 预处理）

# ==================== B站分区 id → 中文名 / 分区页链接 ====================
# 来源：biliscope constants.js BILIBILI_VIDEO_TYPE_MAP / _LINK（B站分区 id 稳定）
VIDEO_TYPE_MAP = {
    '1': '动画', '24': 'MAD·AMV', '25': 'MMD·3D', '47': '短片·手书', '210': '手办·模玩',
    '86': '特摄', '253': '动漫杂谈', '27': '综合', '13': '番剧', '51': '资讯', '152': '官方延伸',
    '32': '完结动画', '33': '连载动画', '167': '国创', '153': '国产动画', '168': '国产原创相关',
    '169': '布袋戏', '170': '资讯', '195': '动态漫·广播剧', '3': '音乐', '28': '原创音乐',
    '31': '翻唱', '30': 'VOCALOID·UTAU', '59': '演奏', '193': 'MV', '29': '音乐现场',
    '130': '音乐综合', '243': '乐评盘点', '244': '音乐教学', '129': '舞蹈', '20': '宅舞',
    '154': '舞蹈综合', '156': '舞蹈教程', '198': '街舞', '199': '明星舞蹈', '200': '国风舞蹈',
    '4': '游戏', '17': '单机游戏', '171': '电子竞技', '172': '手机游戏', '65': '网络游戏',
    '173': '桌游棋牌', '121': 'GMV', '136': '音游', '19': 'Mugen', '36': '知识',
    '201': '科学科普', '124': '社科·法律·心理', '228': '人文历史', '207': '财经商业',
    '208': '校园学习', '209': '职业职场', '229': '设计·创意', '122': '野生技术协会',
    '188': '科技', '95': '数码', '230': '软件应用', '231': '计算机技术', '232': '科工机械',
    '233': '极客DIY', '234': '运动', '235': '篮球', '249': '足球', '164': '健身',
    '236': '竞技体育', '237': '运动文化', '238': '运动综合', '223': '汽车', '245': '赛车',
    '246': '改装玩车', '247': '新能源车', '248': '房车', '240': '摩托车', '227': '购车攻略',
    '176': '汽车生活', '160': '生活', '138': '搞笑', '250': '出行', '251': '三农',
    '239': '家居房产', '161': '手工', '162': '绘画', '21': '日常', '211': '美食',
    '76': '美食制作', '212': '美食侦探', '213': '美食测评', '214': '田园美食', '215': '美食记录',
    '217': '动物圈', '218': '喵星人', '219': '汪星人', '221': '野生动物', '222': '小宠异宠',
    '75': '动物综合', '119': '鬼畜', '22': '鬼畜调教', '26': '音MAD', '126': '人力VOCALOID',
    '216': '鬼畜剧场', '127': '教程演示', '155': '时尚', '157': '美妆护肤', '252': '仿妆cos',
    '158': '穿搭', '159': '时尚潮流', '202': '资讯', '203': '热点', '204': '环球', '205': '社会',
    '206': '综合', '5': '娱乐', '71': '综艺', '241': '娱乐杂谈', '242': '粉丝创作',
    '137': '明星综合', '181': '影视', '182': '影视杂谈', '183': '影视剪辑', '85': '小剧场',
    '184': '预告·资讯', '177': '纪录片', '37': '人文·历史', '178': '科学·探索·自然',
    '179': '军事', '180': '社会·美食·旅行', '23': '电影', '147': '华语电影', '145': '欧美电影',
    '146': '日本电影', '83': '其他国家', '11': '电视剧', '185': '国产剧', '187': '海外剧',
    '257': '配音', '174': '其他',
}
VIDEO_TYPE_LINK = {
    '1': 'douga', '24': 'douga/mad', '25': 'douga/mmd', '47': 'douga/voice',
    '86': 'douga/tokusatsu', '253': 'douga/acgntalks', '27': 'douga/other', '13': 'anime',
    '152': 'anime/offical', '32': 'anime/finish', '33': 'anime/serial', '167': 'guochuang',
    '153': 'guochuang/chinese', '168': 'guochuang/original', '169': 'guochuang/puppetry',
    '170': 'guochuang/information', '195': 'guochuang/motioncomic', '3': 'music',
    '28': 'music/original', '31': 'music/cover', '30': 'music/vocaloid', '59': 'music/perform',
    '193': 'music/mv', '29': 'music/live', '130': 'music/other', '129': 'dance',
    '20': 'dance/otaku', '154': 'dance/three_d', '156': 'dance/demo', '198': 'dance/hiphop',
    '199': 'dance/star', '200': 'dance/china', '4': 'game', '17': 'game/stand_alone',
    '171': 'game/esports', '172': 'game/mobile', '65': 'game/online', '173': 'game/board',
    '121': 'game/gmv', '136': 'game/music', '19': 'game/mugen', '36': 'knowledge',
    '201': 'knowledge/science', '124': 'knowledge/social_science', '228': 'knowledge/humanity_history',
    '207': 'knowledge/business', '208': 'knowledge/campus', '209': 'knowledge/career',
    '229': 'knowledge/design', '122': 'knowledge/skill', '188': 'tech', '95': 'tech/digital',
    '230': 'tech/application', '231': 'tech/computer_tech', '232': 'tech/industry',
    '233': 'tech/diy', '234': 'sports', '235': 'sports/basketball', '249': 'sports/football',
    '164': 'sports/aerobics', '236': 'sports/athletic', '237': 'sports/culture',
    '238': 'sports/comprehensive', '223': 'car', '245': 'car/racing', '246': 'car/modifiedvehicle',
    '247': 'car/newenergyvehicle', '248': 'car/touringcar', '240': 'car/motorcycle',
    '227': 'car/strategy', '176': 'car/life', '160': 'life', '138': 'life/funny',
    '250': 'life/travel', '251': 'life/rurallife', '239': 'life/home', '161': 'life/handmake',
    '162': 'life/painting', '21': 'life/daily', '211': 'food', '76': 'food/make',
    '212': 'food/detective', '213': 'food/measurement', '214': 'food/rural', '215': 'food/record',
    '217': 'animal', '218': 'animal/cat', '219': 'animal/dog', '221': 'animal/wild_animal',
    '222': 'animal/reptiles', '75': 'animal/animal_composite', '119': 'kichiku',
    '22': 'kichiku/guide', '26': 'kichiku/mad', '126': 'kichiku/manual_vocaloid',
    '216': 'kichiku/theatre', '127': 'kichiku/course', '155': 'fashion', '157': 'fashion/makeup',
    '252': 'fashion/cos', '158': 'fashion/clothing', '159': 'fashion/trend', '202': 'information',
    '203': 'information/hotspot', '204': 'information/global', '205': 'information/social',
    '206': 'information/multiple', '5': 'ent', '71': 'ent/variety', '241': 'ent/talker',
    '242': 'ent/fans', '137': 'ent/celebrity', '181': 'cinephile', '182': 'cinephile/cinecism',
    '183': 'cinephile/montage', '85': 'cinephile/shortfilm', '184': 'cinephile/trailer_info',
    '177': 'documentary', '37': 'documentary/history', '178': 'documentary/science',
    '179': 'documentary/military', '180': 'documentary/travel', '23': 'movie',
    '147': 'movie/chinese', '145': 'movie/west', '146': 'movie/japan', '83': 'movie/movie',
    '11': 'tv', '185': 'tv/mainland', '187': 'tv/overseas', '257': 'douga/voice', '174': 'life/other',
}


# 热门视频只取最近 N 天内的投稿，避免老视频靠累计播放量霸榜。
# 与近期发布趋势/活跃度排行保持 30 天口径一致（此前 180 天窗口仍会让
# 数个月前的高播放老视频进入 TOP10）。
HOT_VIDEO_RECENT_DAYS = 30

# 播放量/平均播放统计窗口：近 N 天发布视频的总播放（2026-08-03 由 30 天改为 7 天，
# 30 天窗口太长对"当前热度"参考价值低；up_obs 列名 views_30d 保留，语义=近7天）
VIEW_RECENT_DAYS = 7


def _filter_and_dedup_videos(all_videos, recent_days=HOT_VIDEO_RECENT_DAYS):
    """
    处理 UP主动态 收集到的全部视频：
      1. 过滤掉超过 recent_days 天的老视频
      2. 按 bvid 去重（联合投稿视频会在多个 UP 主空间出现）
      3. 合并同一视频在不同 UP 主空间出现时的作者信息
    返回去重后的视频列表。
    """
    now = int(time.time())
    cutoff = now - recent_days * 86400

    grouped = {}
    for v in all_videos:
        bvid = v.get('bvid')
        if not bvid:
            continue
        pub_date = v.get('pub_date', 0) or 0
        if pub_date < cutoff:
            continue
        if bvid not in grouped:
            grouped[bvid] = []
        grouped[bvid].append(v)

    results = []
    for bvid, copies in grouped.items():
        # 保留播放量最高的副本作为主记录
        best = max(copies, key=lambda x: x.get('views', 0))
        # 收集所有出现过的 (mid, name)：按 mid 成对去重（联合投稿显示全部作者）。
        # 修复前独立收集 up_names/up_mids 再 zip 配对，长度不一致时会静默截断
        # 丢作者甚至错位（同副本缺 name/mid 时两列表长度不同）。
        coauthors = {}
        name_set = []
        for c in copies:
            name = c.get('up_name')
            mid = c.get('up_mid')
            if name and name not in name_set:
                name_set.append(name)
            if mid and mid not in coauthors:
                coauthors[mid] = name or ''
        merged = dict(best)
        merged['up_name'] = ' / '.join(name_set) if name_set else best.get('up_name', '')
        merged['up_mid'] = next(iter(coauthors), None) or best.get('up_mid')
        # 有 mid 的作者按 mid 配对；防御无 mid 的 name 追加到末尾（正常不会出现）
        author_pairs = [{'mid': m, 'name': n} for m, n in coauthors.items()]
        known_names = set(coauthors.values())
        for n in name_set:
            if n not in known_names:
                author_pairs.append({'mid': None, 'name': n})
        merged['_coauthors'] = author_pairs
        results.append(merged)
    return results


def _enrich_hot_video_staff(hot_videos):
    """
    对热门视频 TOP N 调用视频详情接口，获取联合投稿 staff 信息。
    如果存在 staff，用 staff 列表覆盖作者显示；否则保留原有 up_name。
    """
    enriched = []
    for v in hot_videos:
        bvid = v.get('bvid')
        if not bvid:
            enriched.append(v)
            continue
        try:
            detail = fetch_video_detail(bvid)
            if detail and detail.get('staff'):
                staff = detail['staff']
                names = [s.get('name', '') for s in staff if s.get('name')]
                mids = [s.get('mid') for s in staff if s.get('mid')]
                if names:
                    v = dict(v)
                    v['up_name'] = ' / '.join(names)
                    v['up_mid'] = mids[0] if mids else v.get('up_mid')
                    v['_coauthors'] = [{'mid': m, 'name': n} for m, n in zip(mids, names)]
        except Exception as e:
            print(f'  获取联合投稿信息失败 {bvid}: {e}')
        enriched.append(v)
    return enriched


def _recompute_active_scores_by_staff(filtered_videos, up_trends, recent_days=VIEW_RECENT_DAYS):
    """
    根据第一作者（owner）归属重新计算每个 UP 主的近期活跃度分数。

    归属口径（2026-08-03 由"联合投稿按合作者平分"改为 owner 全额归属）：
      - 每条视频播放量全额记给视频 owner（view 接口 owner.mid，权威第一作者）
      - 联合投稿不再平分：合作者非 owner 的 UP 不拿这份播放/计数
      - 理由：① 视频池求和语义下每条视频只计一次，总播放与"近7天去重视频播放量直接相加"一致；
              ② 消除平分口径下"合作者不全在追踪名单 → 份额丢失"导致的低估。

    filtered_videos: _filter_and_dedup_videos 返回的去重视频列表
    up_trends: UP 主列表，会原地更新 total_recent_views 字段
    recent_days: 只算近 N 天的视频
    """
    now = int(time.time())
    cutoff = now - recent_days * 86400
    recent_videos = [v for v in filtered_videos if (v.get('pub_date') or 0) >= cutoff]

    if not recent_videos:
        for u in up_trends:
            u['total_recent_views'] = 0
            u['recent_video_count'] = 0
            u['avg_views'] = 0
        return

    print(f'  活跃度计算：{len(recent_videos)} 个近期视频，正在获取 owner 信息...')

    # 按第一作者（owner）归属，聚合到每个 UP 主
    up_scores = {}  # mid -> {'views': int, 'count': int}
    _recent_kichu = {}  # mid -> 近7天鬼畜视频数（与 recent_video_count 同数据源，保证占比 ≤100%）
    detail_fail_count = 0
    for v in recent_videos:
        bvid = v.get('bvid')
        views = v.get('views', 0)

        # 获取视频详情确定第一作者 owner。space API 的 mid 是"空间主人"，
        # 联合投稿视频可能出现在多个合作者空间，只有 view 接口的 owner 是权威第一作者
        owner_mid = None
        try:
            detail = fetch_video_detail(bvid)
            if detail:
                owner_mid = (detail.get('owner') or {}).get('mid')
        except Exception as e:
            print(f'  获取详情失败 {bvid}: {e}')
        if not owner_mid:
            detail_fail_count += 1
            # 详情获取失败回退：单人投稿时空间 mid 即 owner（联合投稿无法精确归属，按空间来源记）
            owner_mid = v.get('up_mid')
        if not owner_mid:
            continue

        up_scores.setdefault(owner_mid, {'views': 0, 'count': 0})
        up_scores[owner_mid]['views'] += views
        up_scores[owner_mid]['count'] += 1
        if v.get('tid', 0) in KICHU_TIDS:
            _recent_kichu[owner_mid] = _recent_kichu.get(owner_mid, 0) + 1

        time.sleep(0.3)  # 控制 API 调用频率

    # 写回 up_trends
    for u in up_trends:
        score = up_scores.get(u['mid'], {'views': 0, 'count': 0})
        u['total_recent_views'] = score['views']
        u['recent_video_count'] = score['count']
        # 平均播放 = 近7天发布视频的总播放 ÷ 近7天发布视频数（近7天维度，与 views_30d 同源）
        u['avg_views'] = int(score['views'] / score['count']) if score['count'] else 0
        u['recent_kichu_count'] = _recent_kichu.get(u['mid'], 0)

    print(f'  活跃度计算完成：{detail_fail_count} 个视频详情获取失败（回退空间归属），{len(up_scores)} 个 UP 主有近期活跃数据')


def extract_keyword_cloud(videos):
    """从视频列表提取关键词云（jieba 分词 + biliscope 权重设计）。

    重写说明（原 extract_keywords 用 re.split 切短语块，分词质量极差）：
    - jieba.cut 真分词（项目已装，梗素材库/弹幕词云在用）
    - 权重：title=3, desc=1（借鉴 biliscope biliapi.js updateWordMap）
    - clean_text 预处理：去 URL/bvid/av号/日期/平台噪声词
    - STOPWORDS 800+ 虚词过滤（utils/stopwords.py 统一管理）
    - 同一文本内同词只计一次（避免"哈哈哈"重复拉高，借鉴梗素材库 seen_in_title）
    - 不再把 content_type 标签混入词云（类型分类由 classify_content 独立负责）

    返回 [{'text': kw, 'count': cnt}, ...]，保持前端 UpTrends.jsx 契约。
    """
    import jieba
    from utils.stopwords import STOPWORDS, WORD_PATTERN, clean_text, ensure_kichu_dict

    ensure_kichu_dict()  # 加载鬼畜梗自定义词典（哈基米等整词，幂等）

    word_counter = Counter()
    for v in videos:
        title = v.get('title', '') or ''
        desc = v.get('description', '') or ''
        # 权重设计：title=3, desc=1（借鉴 biliscope）
        for text, weight in [(title, 3), (desc, 1)]:
            if not text:
                continue
            cleaned = clean_text(text)
            seen = set()  # 同一文本内同词只计一次（避免"哈哈哈"重复拉高）
            for w in jieba.cut(cleaned, HMM=False):  # 精确模式：避免 HMM 新词发现产生"基米/哈基"类碎片
                w = w.strip()
                if len(w) < 2:
                    continue
                if not WORD_PATTERN.match(w):
                    continue
                if w.lower() in STOPWORDS:
                    continue
                seen.add(w.lower())
            for w in seen:
                word_counter[w] += weight

    # 频次≥2 过滤，取 TOP 80
    return [{'text': w, 'count': c} for w, c in word_counter.most_common(80) if c >= 2]

# B站 tid → 内容类型名称映射
# B站 tid → 内容类型名称映射（tid v2.0，基于B站官方opus + bilibili-API-collect交叉验证）
# 注：B站2024-2025重编号了大量分区。旧号保留用于兼容历史数据。
TID_CATEGORY_MAP = {
    # ── 鬼畜区（主119/177, 子22/26/126/127/216）──
    22: '鬼畜调教',       # 新版鬼畜调教（原119）
    26: '音MAD',          # 新版音MAD（原217）
    119: '鬼畜',          # 鬼畜主分区（原鬼畜调教）
    126: '人力VOCALOID',  # 新版人力VOCALOID（原218）
    127: '教程演示',       # 鬼畜教程演示
    216: '鬼畜剧场',       # 鬼畜剧场
    218: '人力VOCALOID',  # 旧版人力VOCALOID（兼容）
    221: '野生动物',       # 旧鬼畜剧场，现已重新分配给动物圈

    # ── 音乐区（主3, 子28/29/30/31/59/130/193/243/244）──
    3: '音乐',
    28: '原创音乐',
    29: '音乐现场',
    30: 'VOCALOID·UTAU',
    31: '翻唱',
    59: '演奏',
    130: '音乐综合',
    193: 'MV',
    243: '乐评盘点',
    244: '音乐教学',

    # ── 游戏区（主4, 子17/19/65/121/136/171/172/173）──
    4: '游戏',
    17: '单机游戏',
    19: 'Mugen',
    65: '网络游戏',
    121: 'GMV',
    136: '音游',
    171: '电子竞技',
    172: '手机游戏',
    173: '桌游棋牌',

    # ── 动画区（主1, 子24/25/27/47/86/210/253）──
    1: '动画',
    24: 'MAD·AMV',
    25: 'MMD·3D',
    27: '综合',
    47: '短片·手书·配音',
    86: '特摄',
    210: '手办·模玩',
    253: '动漫杂谈',

    # ── 生活区（主160, 子21/75/76/138/161/162/239）──
    21: '日常',
    75: '动物圈',
    76: '美食制作',
    138: '搞笑',
    160: '生活',
    161: '手工',
    162: '绘画',
    239: '家居房产',

    # ── 知识区（主36, 子122/124/201/207/208/209/228/229）──
    36: '知识',
    122: '野生技能',
    124: '社科·法律·心理',
    201: '科学科普',
    207: '财经商业',
    208: '校园学习',
    209: '职业职场',
    228: '人文历史',
    229: '设计·创意',

    # ── 影视区（主181, 子85/182/183/184）──
    85: '短片',
    181: '影视',
    182: '影视杂谈',
    183: '影视剪辑',
    184: '预告·资讯',

    # ── 娱乐区（主5, 子71/137）──
    5: '娱乐',
    71: '综艺',
    137: '明星',

    # ── 舞蹈区（主129, 子20/154/156/198/199/200）──
    20: '宅舞',
    129: '舞蹈',
    154: '舞蹈综合',
    156: '舞蹈教程',
    198: '街舞',
    199: '明星舞蹈',
    200: '中国舞',

    # ── 科技区（主188, 子95/230/231/232/233）──
    95: '数码',
    188: '科技',
    230: '软件应用',
    231: '计算机技术',
    232: '科工机械',
    233: '极客DIY',

    # ── 其他大区 ──
    155: '时尚',
    167: '国创',
    211: '美食',
    223: '汽车',
    234: '运动',
    177: '纪录片',
    217: '动物圈',
    13: '番剧',
    11: '电视剧',
    23: '电影',

    # ── 时尚区细节 ──
    157: '美妆护肤',
    158: '穿搭',
    159: '时尚潮流',

    # ── 美食区细节 ──
    212: '美食侦探',
    213: '美食测评',
    214: '田园美食',
    215: '美食记录',

    # ── 运动区细节 ──
    164: '健身',
    235: '篮球·足球',
    236: '竞技体育',
    237: '运动文化',
    238: '运动综合',

    # ── 汽车区细节 ──
    176: '汽车生活',
    224: '汽车文化',
    225: '汽车极客',
    226: '智能出行',
    227: '购车攻略',
    240: '摩托车',

    # ── 动物圈细节 ──
    218: '喵星人',
    219: '汪星人',
    220: '大熊猫',
    222: '爬宠',

    # ── 国创区细节 ──
    153: '国产动画',
    168: '国产原创',
    169: '布袋戏',
    170: '国创资讯',
    195: '动态漫·广播剧',

    # ── 番剧区细节 ──
    32: '完结动画',
    33: '连载动画',
    51: '番剧资讯',
    152: '官方延伸',

    # ── 纪录片区细节 ──
    37: '人文·历史',
    178: '科学·探索·自然',
    179: '军事',
    180: '社会·美食·旅行',

    # ── 电影区细节 ──
    83: '其他国家',
    145: '欧美电影',
    146: '日本电影',
    147: '国产电影',

    # ── 电视剧区细节 ──
    185: '国产剧',
    187: '海外剧',
}


def classify_content(videos):
    """根据视频 tid 优先分类，tid 未知时回退到标题关键词"""
    type_counter = Counter()
    for v in videos:
        tid = v.get('tid', 0)
        # 优先用 tid 映射
        if tid in TID_CATEGORY_MAP:
            type_counter[TID_CATEGORY_MAP[tid]] += 1
            continue
        # 回退到标题关键词
        title = v.get('title', '')
        matched = False
        for content_type, keywords in CONTENT_TYPES.items():
            for kw in keywords:
                if kw.lower() in title.lower():
                    type_counter[content_type] += 1
                    matched = True
                    break
            if matched:
                break
        if not matched:
            type_counter['其他'] += 1
    return type_counter.most_common()

def build_timeline(videos):
    timeline = {}
    now = int(time.time())
    for v in videos:
        pub = v.get('pub_date', 0)
        if not pub:
            continue
        days_ago = (now - pub) // 86400
        if days_ago > 30:
            continue
        date_str = time.strftime('%m-%d', time.gmtime(pub + 8 * 3600))
        if date_str not in timeline:
            timeline[date_str] = {'count': 0, 'views': 0, 'videos': []}
        timeline[date_str]['count'] += 1
        timeline[date_str]['views'] += v.get('views', 0)
        timeline[date_str]['videos'].append(v)

    sorted_timeline = sorted(timeline.items())
    return [{'date': d, 'count': v['count'], 'views': v['views']} for d, v in sorted_timeline[-14:]]


def _select_active_ups(up_trends, now=None):
    """进榜门槛筛选：近 VIEW_RECENT_DAYS 天有发布且近7天播放>0 的 UP。

    门槛窗口与排序字段（total_recent_views 近7天）同源——
    total_recent_views > 0 已隐含"近7天有发布"，latest_pub_date 门槛保留作防御
    （防 total_recent_views 计算异常时误入），但窗口与排序字段同源，
    避免"门槛30天/排序7天"语义分裂（原 ACTIVE_RECENT_DAYS=30 已废弃，2026-08-07 统一为7天）。
    """
    now = now or int(time.time())
    active_cutoff = now - VIEW_RECENT_DAYS * 86400
    return [u for u in up_trends
            if u['latest_pub_date'] >= active_cutoff and u['total_recent_views'] > 0]


def analyze_tracked_ups_with_progress(tracked_ups, progress_callback=None):
    """分析指定名单中的 UP主（支持进度回调）"""
    user_info = get_user_info()
    if not user_info:
        return {'error': 'not_logged_in', 'message': '请先登录B站账号'}

    if not tracked_ups:
        return {
            'success': True, 'user': user_info, 'mutual_count': 0,
            'up_trends': [], 'analysis': {}, 'message': '名单中没有UP主',
        }

    print(f'正在分析 {len(tracked_ups)} 个选中UP主...')
    up_trends = []
    all_videos = []

    for idx, up in enumerate(tracked_ups):
        print(f'  正在分析: {up["name"]} (UID: {up["mid"]})')
        if progress_callback:
            progress_callback(idx, up['name'])

        videos = get_user_latest_videos(up['mid'], count=5)
        rel_stat = get_up_relation_stat(up['mid'])
        # 刷新 UP 主最新信息（tracked_ups.json 无 sign 字段，且 name/face 可能过时）
        up_info = get_up_info_by_mid(up['mid'])
        if up_info:
            up['name'] = up_info.get('name') or up.get('name', '')
            up['face'] = up_info.get('face') or up.get('face', '')
            up['sign'] = up_info.get('sign') or up.get('sign', '')

        kichu_videos = [v for v in videos if v.get('tid', 0) in KICHU_TIDS]

        for v in videos:
            v['up_name'] = up['name']
            v['up_mid'] = up['mid']
            v['up_face'] = up.get('face', '')
            all_videos.append(v)

        latest_pub = max([v['pub_date'] for v in videos if v['pub_date']], default=0)
        # total_recent_views 在循环外由 _recompute_active_scores_by_staff 统一计算（按合作者平分）
        total_recent_views = 0

        up_trends.append({
            'mid': up['mid'], 'name': up['name'], 'face': up.get('face', ''),
            'sign': up.get('sign', ''), 'follower_count': rel_stat['follower'],
            'following_count': rel_stat['following'], 'latest_videos': videos[:5],
            'kichu_video_count': len(kichu_videos), 'total_recent_views': total_recent_views,
            'latest_pub_date': latest_pub,
            # 平均播放占位 0：真实值由 _recompute_active_scores_by_staff 按"近30天总播放 ÷ 近30天视频数"统一计算
            'avg_views': 0,
            'video_count': len(videos),
        })
        time.sleep(0.5)

    up_trends.sort(key=lambda x: x['latest_pub_date'], reverse=True)

    # 过滤老视频 + 联合投稿去重合并作者
    filtered_videos = _filter_and_dedup_videos(all_videos)
    # 联合投稿按合作者数平分播放量，重新计算每个 UP 主的活跃度
    _recompute_active_scores_by_staff(filtered_videos, up_trends)

    keyword_cloud = extract_keyword_cloud(all_videos)
    content_types = classify_content(filtered_videos)
    timeline = build_timeline(filtered_videos)
    sorted_videos = sorted(filtered_videos, key=lambda x: x.get('views', 0), reverse=True)
    hot_videos = sorted_videos[:10]
    # 对 TOP10 补全联合投稿 staff 信息（解决 space API 只返回 owner 的问题）
    hot_videos = _enrich_hot_video_staff(hot_videos)

    # 进榜门槛筛选见 _select_active_ups（门槛窗口与排序字段同源，均为近7天）
    active_ups = _select_active_ups(up_trends)
    play_ranking = sorted(active_ups, key=lambda x: x['total_recent_views'], reverse=True)
    # 创作活跃度排行：发布数量为主，新鲜度（最近发布时间）为辅
    creator_ranking = sorted(active_ups, key=lambda x: (
        x.get('recent_video_count', 0),
        x.get('latest_pub_date', 0)
    ), reverse=True)
    now = int(time.time())
    # 近7天视频池（总播放口径）：filtered_videos 是近30天池（hot_videos/高增速榜用），
    # summary 的总量字段单独按 VIEW_RECENT_DAYS=7 再过滤一次，保证"总播放=近7天视频池求和"
    pool_cutoff = now - VIEW_RECENT_DAYS * 86400
    pool_videos = [v for v in filtered_videos if (v.get('pub_date') or 0) >= pool_cutoff]
    pool_total_views = sum(v.get('views', 0) for v in pool_videos)
    pool_total_videos = len(pool_videos)

    analysis = {
        'keyword_cloud': keyword_cloud,
        'content_types': [{'type': t, 'count': c} for t, c in content_types],
        'timeline': timeline, 'hot_videos': hot_videos,
        # 全量去重视频（含 up_name/_coauthors/cover/views 等）——供高增速视频榜单跨批次对比播放量，
        # hot_videos 只存每批播放量 TOP10，新发布但播放量不高的高增速视频会被漏掉
        'all_videos': filtered_videos,
        'play_ranking': [{
            'mid': u['mid'], 'name': u['name'], 'face': u['face'],
            'total_recent_views': u['total_recent_views'], 'avg_views': u['avg_views'],
            'video_count': u['video_count'], 'follower_count': u['follower_count'],
            'kichu_video_count': u['kichu_video_count'], 'latest_pub_date': u['latest_pub_date'],
        } for u in play_ranking[:10]],
        'creator_ranking': [{
            'mid': u['mid'], 'name': u['name'], 'face': u['face'],
            'recent_video_count': u.get('recent_video_count', 0),
            'total_recent_views': u['total_recent_views'], 'avg_views': u['avg_views'],
            'follower_count': u['follower_count'],
            'kichu_video_count': u['kichu_video_count'], 'latest_pub_date': u['latest_pub_date'],
        } for u in creator_ranking[:10]],
        'summary': {
            'total_ups': len(up_trends), 'total_videos': pool_total_videos,
            'total_views': pool_total_views,
            'avg_views_per_video': int(pool_total_views / pool_total_videos) if pool_total_videos else 0,
            'kichu_up_count': sum(1 for u in up_trends if u['kichu_video_count'] > 0),
            'kichu_video_count': sum(1 for v in pool_videos if v.get('tid', 0) in KICHU_TIDS),
            'active_up_count': sum(1 for u in up_trends if u['latest_pub_date'] > now - 7 * 86400),
        }
    }

    print(f'分析完成，共 {len(up_trends)} 个UP主，近7天视频池 {pool_total_videos} 个去重视频')
    return {
        'success': True, 'user': user_info, 'mutual_count': len(tracked_ups),
        'up_trends': up_trends, 'analysis': analysis,
    }

def safe_get_with_cookie(url, params=None, max_retries=2):
    cookie_str = get_cookie_str()
    if not cookie_str:
        return None
    for i in range(max_retries + 1):
        try:
            resp = requests.get(url, headers=get_headers(cookie_str), params=params, timeout=15)
            data = resp.json()
            if data.get('code') == 0:
                return data
            elif data.get('code') == -101:
                return {'error': 'cookie_expired', 'message': 'Cookie已过期，请重新登录'}
            time.sleep(0.5)
        except Exception as e:
            if i < max_retries:
                time.sleep(1)
            else:
                print(f'请求失败 {url}: {e}')
    return None

def get_followings(mid, pn=1, ps=50):
    url = 'https://api.bilibili.com/x/relation/followings'
    params = {'vmid': mid, 'pn': pn, 'ps': ps, 'order': 'desc', 'order_type': 'attention'}
    data = safe_get_with_wbi(url, params)
    if not data or data.get('error'):
        return [], 0

    total = data.get('data', {}).get('total', 0)
    following_list = data.get('data', {}).get('list', [])

    results = []
    for item in following_list:
        results.append({
            'mid': item.get('mid', 0),
            'name': item.get('uname', ''),
            'face': item.get('face', ''),
            'sign': item.get('sign', ''),
            'attribute': item.get('attribute', 0),
            'is_mutual': item.get('attribute', 0) == 6,
            'mtime': item.get('mtime', 0),
            'tag': item.get('tag', None),
            'special': item.get('special', 0),
        })

    return results, total

def get_all_mutual_followings(mid):
    print(f'正在获取用户 {mid} 的互粉列表...')
    all_mutuals = []
    pn = 1
    ps = 50
    total = 0

    while True:
        followings, total_count = get_followings(mid, pn=pn, ps=ps)
        if not followings:
            break

        mutuals = [f for f in followings if f['is_mutual']]
        all_mutuals.extend(mutuals)

        if pn * ps >= total_count or len(followings) < ps:
            break
        pn += 1
        time.sleep(0.3)

    print(f'共获取 {total_count} 个关注，其中互粉 {len(all_mutuals)} 个')
    return all_mutuals

def get_user_latest_videos(mid, count=5):
    url = 'https://api.bilibili.com/x/space/wbi/arc/search'
    params = {
        'mid': mid,
        'pn': 1,
        'ps': count,
        'order': 'pubdate',
        'tid': 0,
    }
    data = safe_get_with_wbi(url, params)
    if not data or data.get('error'):
        return []

    vlist = data.get('data', {}).get('list', {}).get('vlist', [])
    if not vlist:
        return []

    results = []
    for v in vlist:
        # UP空间API标题/简介含 HTML 实体（&amp; → &、&quot; → " 等），必须反转义
        title = html.unescape(v.get('title', ''))
        bvid = v.get('bvid', '')
        play = v.get('play', 0)
        review = v.get('review', 0)
        video_review = v.get('video_review', 0)
        favorites = v.get('favorites', 0)
        created = v.get('created', 0)
        description = html.unescape(v.get('description', '') or '')
        pic = v.get('pic', '')
        length_str = v.get('length', '0:00')
        duration = 0
        if ':' in str(length_str):
            parts = str(length_str).split(':')
            if len(parts) == 2:
                duration = int(parts[0]) * 60 + int(parts[1])

        # UP空间API不返回赞/币/转，只能按播放量比例估算。
        # 比例取全站典型下限（1%/0.5%/0.2%），固定互动率贡献约 2.6%：
        # 之前用 5%/2%/1%（贡献 12%）导致任何播放量>0 的新视频互动率虚高、virality 封顶，
        # 低播放视频也被误判"爆发期"（trend_score 与播放量脱钩）。
        likes_est = int(play * 0.01) if play > 0 else 0
        coins_est = int(play * 0.005) if play > 0 else 0
        shares_est = int(play * 0.002) if play > 0 else 0

        tags = []
        trend_score = calc_trend_score(play, likes_est, coins_est, favorites, shares_est, review, video_review, created)

        results.append({
            'bvid': bvid,
            'aid': v.get('aid', ''),
            'title': title,
            'description': description[:200],
            'cover': pic,
            'author': v.get('author', ''),
            'mid': mid,
            'tid': _to_int_tid(v.get('typeid', 0)),
            'tname': '',
            'views': play,
            'danmaku': video_review,
            'comments': review,
            'likes': likes_est,
            'coins': coins_est,
            'favorites': favorites,
            'shares': shares_est,
            'url': f'https://www.bilibili.com/video/{bvid}',
            'tags': tags,
            'trend_score': round(trend_score, 1),
            'trend_label': get_trend_label(trend_score),
            'pub_date': created,
            'duration': duration,
        })

    return results

def get_up_relation_stat(mid):
    url = 'https://api.bilibili.com/x/relation/stat'
    params = {'vmid': mid}
    data = safe_get_with_wbi(url, params, max_retries=1)
    if not data or data.get('error'):
        return {'following': 0, 'follower': 0}
    return {
        'following': data.get('data', {}).get('following', 0),
        'follower': data.get('data', {}).get('follower', 0),
    }


def get_up_info_by_mid(mid):
    """通过 /x/space/wbi/acc/info 获取 UP 主最新详情（name/face/sign 等）。

    用于分析流程中刷新 tracked_ups.json 里可能过时的 sign/face/name。
    失败返回 None，调用方应降级使用旧值。

    字段参考 biliscope ui.js：name/face/sign/level/sex/official.title/official.type
    face 强制 https（与 biliscope 一致，避免混合内容告警）。
    """
    url = 'https://api.bilibili.com/x/space/wbi/acc/info'
    data = safe_get_with_wbi(url, {'mid': mid}, max_retries=1)
    if not data or data.get('error'):
        return None
    d = data.get('data', {})
    if not d:
        return None
    official = d.get('official', {}) or {}
    return {
        'mid': d.get('mid', mid),
        'name': d.get('name', ''),
        'face': (d.get('face', '') or '').replace('http://', 'https://'),
        'sign': d.get('sign', '') or '',
        'level': d.get('level', 0),
        'sex': d.get('sex', ''),
        'official_title': official.get('title', ''),
        'official_type': official.get('type', -1),
        'jointime': d.get('jointime', 0),
    }


def search_up_users(keyword, page=1, page_size=10):
    """按昵称搜索B站用户（/x/web-interface/wbi/search/type?search_type=bili_user）。

    用于访客"申请追踪UP"的昵称搜索入口（后端代理，防前端直连被风控）。
    返回标准化列表 [{mid, name, fans, sign, face}]；
    失败/无结果返回 None —— 调用方降级提示"粘贴UP主页链接"。
    face 强制 https（与 get_up_info_by_mid 一致）。
    """
    url = 'https://api.bilibili.com/x/web-interface/wbi/search/type'
    params = {
        'search_type': 'bili_user',
        'keyword': keyword,
        'page': page,
        'page_size': page_size,
    }
    data = safe_get_with_wbi(url, params, max_retries=1)
    if not data or data.get('error'):
        return None
    d = data.get('data', {}) or {}
    results = d.get('result')
    if results is None:
        return None
    out = []
    for item in results:
        mid = item.get('mid')
        if not mid:
            continue
        out.append({
            'mid': mid,
            'name': item.get('uname', ''),
            'fans': item.get('fans', 0) or 0,
            'sign': (item.get('sign') or '').strip(),
            'face': (item.get('upic', '') or '').replace('http://', 'https://'),
        })
    return out


def fetch_up_full_videos(mid, max_pages=10, ps=30):
    """翻页拉取 UP 全量投稿（/x/space/wbi/arc/search，biliscope 同款）。

    - 串行翻页 + sleep(0.3) 控制频率（与 get_all_mutual_followings 一致，防 B站 限流）
    - 空页 / count 到底提前退出
    - 返回 (vlist 原始条目, 接口真实投稿总数 page.count)；
      总数用于 get_up_card 的 video_count，避免 max_pages 截断导致总投稿数偏小
    """
    url = 'https://api.bilibili.com/x/space/wbi/arc/search'
    all_videos = []
    total_count = 0
    for pn in range(1, max_pages + 1):
        params = {'mid': mid, 'pn': pn, 'ps': ps, 'order': 'pubdate', 'tid': 0}
        data = safe_get_with_wbi(url, params)
        if not data or data.get('error'):
            break
        d = data.get('data', {}) or {}
        vlist = d.get('list', {}).get('vlist', [])
        if not vlist:
            break
        all_videos.extend(vlist)
        count = d.get('page', {}).get('count', 0)
        if count:
            total_count = max(total_count, count)
        if count and pn * ps >= count:
            break
        time.sleep(0.3)
    return all_videos, total_count


def _calc_video_types(videos, top_n=3):
    """按投稿 typeid 计数，映射中文名，取 top_n（biliscope convertVideoData 同款）。

    返回 [{'tid', 'name', 'count', 'link'}]，未知分区 id 跳过。
    """
    counter = Counter(v.get('typeid', 0) for v in videos if v.get('typeid'))
    result = []
    for tid, count in counter.most_common(top_n):
        name = VIDEO_TYPE_MAP.get(str(tid), '')
        if not name:
            continue
        result.append({
            'tid': tid,
            'name': name,
            'count': count,
            'link': VIDEO_TYPE_LINK.get(str(tid), ''),
        })
    return result


def get_up_card(mid, max_pages=10):
    """生成 UP 卡片数据（词云 + 分区 top3 + 统计），带 1 天缓存。

    数据源：arc/search 翻页拉全量投稿，一次请求多份产物：
    - 词云：extract_keyword_cloud（title×3 + desc×1，jieba 分词 + 停用词过滤）
    - 分区标签：_calc_video_types（投稿量 top3 分区，映射中文名）
    - 统计：投稿总数 / 近30天投稿数 / 最近投稿时间
    缓存策略：up_card_cache 表 TTL 1 天（biliscope cacheValid 的持久化版本），
    列表渲染 / 悬停复用同一数据，避免反复翻页。
    """
    from storage.up_card_store import read_up_card_cache, write_up_card_cache

    cached = read_up_card_cache(mid)
    if cached is not None:
        return cached

    videos, total_count = fetch_up_full_videos(mid, max_pages=max_pages)
    if not videos:
        return None

    now = int(time.time())
    # 近7天发布的视频（口径与前端"近7天发布数"一致：created 时间戳）
    week_videos = [v for v in videos if (v.get('created') or 0) > now - 7 * 86400]
    card = {
        'mid': mid,
        # 接口真实投稿总数优先（翻页可能因 max_pages 截断，len(videos) 会偏小）
        'video_count': max(total_count, len(videos)),
        'word_cloud': extract_keyword_cloud(videos)[:20],
        'video_types': _calc_video_types(videos),
        # 近7天发布数 / 近7天总播放：基于翻页全量真实统计，
        # 消除分析任务"每 UP 只采样最新 5 条 + 联合投稿按合作者平分播放量"的口径失真
        # （字段名带 7d 标记：旧 last_month_* 缓存字段名不匹配 → 读缓存时自动失效重抓）
        'last_7d_count': len(week_videos),
        'last_7d_views': sum(v.get('play') or 0 for v in week_videos),
        'latest_pub_ts': max((v.get('created') or 0) for v in videos),
    }
    write_up_card_cache(mid, card)
    return card

