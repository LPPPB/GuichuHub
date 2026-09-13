"""分析层 — 弹幕热词二次过滤

只过滤广告/品牌/活动等明确干扰词，不误杀"鬼畜""神""离谱"等弹幕用语。
词表真源：utils/danmaku_filters.json（开发者后台可编辑，下次抓取生效）。
结构：bad_exact=精确匹配、bad_substr=子串匹配。
内置兜底：文件缺失/损坏时降级，保证过滤行为不退化（与 tag_filters.json 同哲学）。
"""

import json
import os

_DANMAKU_FILTERS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'utils', 'danmaku_filters.json',
)

_FALLBACK_DANMAKU_FILTERS = {
    'allowed_exact': ['233', '2333', '666', '114514'],
    'bad_exact': [
        # 广告品牌
        '美团', '美团外卖', '饿了么', '饿了吗', '爱回收', '爱回收严选',
        '转转', '闲鱼', '严选', '网易严选', '京东', '淘宝', '拼多多', '天猫',
        '支付宝', '微信', '抖音', '快手', '小红书', '微博',
        '广告', '赞助', '恰饭', '推广', '商单', '代言', '品牌', '合作',
        '外卖', '快递', '购物', '电商', '二手', '骑手', '外卖员', '快递员',
        '瑞幸', '星巴克', '麦当劳', '肯德基', '必胜客',
        '奈雪', '喜茶', '茶百道', '蜜雪冰城', '古茗',
        '可口可乐', '百事可乐', '农夫山泉', '元气森林',
        '华为', '小米', 'OPPO', 'vivo', '一加', '荣耀', '三星', '苹果',
        '索尼', '联想', '戴尔', '华硕', '惠普', '微星', '英特尔', 'AMD', 'NVIDIA', '英伟达',
        '比亚迪', '特斯拉', '蔚来', '小鹏', '理想汽车', '滴滴', '哈啰', '曹操出行',
        '得物', '毒', '识货', 'Keep', 'keep', '咕咚',
        '携程', '去哪儿', '飞猪', '同程', '链家', '贝壳', '自如',
        'Boss直聘', '猎聘', '智联招聘', '前程无忧',
        '新东方', '好未来', '作业帮', '猿辅导',
        '丁香医生', '好大夫', '微医', '途虎', '途虎养车', '天猫养车',
        '货拉拉', '快狗打车', '运满满', '什么值得买', '慢慢买',
        # B站活动
        '鬼畜星探企划', '鬼畜星探计划', '鬼畜星探',
        'bilibili新星计划', '新星计划', '创作激励',
        'AI全民制作人', '致予新世界', 'updream',
        '星火计划', '星火企划', '星探企划', '星探计划',
        '充电', '发电', '电池', '充能',
        '必剪', '必剪创作',
        # 平台/竞品
        'ChiliChili', 'chilichili', '油管', 'YouTube', 'youtube',
        'TikTok', 'tiktok',
        # 年份数字
        '2022', '2023', '2024', '2025', '2026',
        # B站通用词
        '哔哩哔哩', 'bilibili', 'B站', 'b站',
        'UP主', 'up主', '投稿', '自制', '转载',
        '点赞', '投币', '收藏', '转发', '关注', '三连',
        '直播', '直播间', '首播', '首秀',
        # 过于泛化的分区/类别词
        '视频', '高清', '完整版', '合集', '制作', '教程',
        '音乐', '翻唱', '演奏', 'MV', '舞蹈',
        '知识', '科技', '数码', '生活', '美食',
        '娱乐', '综艺', '明星', '时尚', '资讯',
        '电影', '电视剧', '动画', '番剧', '国创', '影视', '纪录片',
        '游戏', '手游', '网游', '电竞',
        '科幻', '微电影', '脑洞', 'AIGC', 'AI剧情大片',
        '原神', '王者荣耀', '英雄联盟', 'LOL',
        '崩坏星穹铁道', '星穹铁道', '崩铁',
        '景元', '爻光', '饮月', '黄泉', '花火',
        '和平精英', '吃鸡', '鸣潮', '战双', '明日方舟',
        # 其他泛化词
        '英语', '数学', '物理', '化学', '语文', '原创',
        '童年', '90后', '80后', '00后', '70后',
        '剧终', '结局', '开场', '开头', '结尾',
        '艺术创想', '盗梦空间', '拼好歌', '诗歌剧',
        '世界杯终局之战', '复仇者', '马林巴', '少女A',
    ],
    'bad_substr': [
        # 广告品牌子串
        '外卖', '爱回收', '严选', '转转', '闲鱼',
        '美团', '饿了么', '京东', '淘宝', '拼多多', '天猫',
        '瑞幸', '麦当劳', '肯德基', '蜜雪冰城',
        '华为', '小米', '索尼', '比亚迪', '特斯拉',
        '携程', '飞猪', '货拉拉', '途虎',
        '广告', '赞助', '恰饭', '推广', '商单', '代言',
        # 活动子串
        '星探', '星火', '新星计划', '创作激励',
    ],
}


def load_danmaku_filters():
    """读取弹幕热词过滤词表。

    ``allowed_exact`` 是弹幕场景白名单，优先于公共停用词和人工黑名单；
    老版本配置没有该字段时自动使用数字梗白名单，保持向后兼容。
    文件缺失/损坏时降级为内置兜底。
    """
    try:
        with open(_DANMAKU_FILTERS_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        bad_exact = data.get('bad_exact')
        bad_substr = data.get('bad_substr')
        if isinstance(bad_exact, list) and isinstance(bad_substr, list):
            return {
                'allowed_exact': [str(w) for w in data.get('allowed_exact', _FALLBACK_DANMAKU_FILTERS['allowed_exact'])
                                  if isinstance(w, str) and str(w).strip()],
                'bad_exact': [str(w) for w in bad_exact if isinstance(w, str) and str(w).strip()],
                'bad_substr': [str(w) for w in bad_substr if isinstance(w, str) and str(w).strip()],
            }
    except Exception as e:
        print(f'[弹幕热词过滤] 读取配置文件失败，使用内置兜底: {e}')
    return {
        'allowed_exact': list(_FALLBACK_DANMAKU_FILTERS['allowed_exact']),
        'bad_exact': list(_FALLBACK_DANMAKU_FILTERS['bad_exact']),
        'bad_substr': list(_FALLBACK_DANMAKU_FILTERS['bad_substr']),
    }


def save_danmaku_filters(filters):
    """保存弹幕热词过滤词表到配置文件。filters 结构同 load_danmaku_filters 返回值。"""
    with open(_DANMAKU_FILTERS_PATH, 'w', encoding='utf-8') as f:
        json.dump({
            'version': 1,
            'description': "弹幕热词场景规则：公共停用词之后应用，保存后立即影响词云和升温榜。",
            'allowed_exact': list(filters.get('allowed_exact', _FALLBACK_DANMAKU_FILTERS['allowed_exact'])),
            'bad_exact': list(filters['bad_exact']),
            'bad_substr': list(filters['bad_substr']),
        }, f, ensure_ascii=False, indent=2)
    _invalidate_danmaku_filters()


# filter_danmaku_words 高频调用（dashboard 组装），词表带模块级缓存（保存后失效，无需重启后端）
_DANMAKU_FILTERS_CACHE = None


def _get_danmaku_filters():
    """读取预处理后的过滤词表（带模块级缓存）。"""
    global _DANMAKU_FILTERS_CACHE
    if _DANMAKU_FILTERS_CACHE is None:
        raw = load_danmaku_filters()
        _DANMAKU_FILTERS_CACHE = {
            'allowed_exact': {w.lower() for w in raw.get('allowed_exact', [])},
            'bad_exact': {w.lower() for w in raw['bad_exact']},
            'bad_substr': [s.lower() for s in raw['bad_substr']],
        }
    return _DANMAKU_FILTERS_CACHE


def _invalidate_danmaku_filters():
    """配置保存后失效缓存，下次 filter_danmaku_words 调用重新加载。"""
    global _DANMAKU_FILTERS_CACHE
    _DANMAKU_FILTERS_CACHE = None


def explain_danmaku_word(word):
    """返回弹幕词的规则判定，供过滤器和开发者后台共同使用。"""
    from utils.stopwords import STOPWORDS, DANMAKU_NUMERIC_ALLOWLIST

    raw = str(word or '').strip()
    word_lower = raw.lower()
    if not raw:
        return {'accepted': False, 'layer': 'format', 'category': '空文本', 'match': 'format'}

    filters = _get_danmaku_filters()
    allowed = filters.get('allowed_exact', set()) | {w.lower() for w in DANMAKU_NUMERIC_ALLOWLIST}
    if word_lower in allowed:
        return {'accepted': True, 'layer': 'danmaku_allow', 'category': '弹幕白名单', 'match': 'exact'}
    if raw.isdigit():
        return {'accepted': False, 'layer': 'format', 'category': '纯数字', 'match': 'format'}
    if word_lower in {w.lower() for w in STOPWORDS}:
        return {'accepted': False, 'layer': 'common', 'category': '公共停用词', 'match': 'exact'}
    if word_lower in filters['bad_exact']:
        return {'accepted': False, 'layer': 'danmaku', 'category': '弹幕精确屏蔽', 'match': 'exact'}
    for sub in filters['bad_substr']:
        if sub in word_lower:
            return {'accepted': False, 'layer': 'danmaku', 'category': '弹幕子串屏蔽',
                    'match': 'substring', 'matched': sub}
    return {'accepted': True, 'layer': 'none', 'category': '未命中过滤规则', 'match': None}


def filter_danmaku_words(words):
    """统一清理弹幕热词：公共停用词 → 弹幕白名单/黑名单。"""
    result = []
    for item in words:
        if explain_danmaku_word(item.get('word', ''))['accepted']:
            result.append(item)
    return result


def explain_word(word, scope):
    """跨榜单统一规则解释入口（开发者后台测试台使用）。"""
    scope = str(scope or '').lower()
    if scope == 'danmaku':
        return explain_danmaku_word(word)

    from collectors.bilibili import explain_tag_rule, load_meme_stopwords, load_meme_seed_words
    if scope == 'tag':
        return explain_tag_rule(word)
    if scope == 'meme':
        raw = str(word or '').strip()
        if raw in set(load_meme_seed_words()):
            return {'accepted': True, 'layer': 'meme_allow', 'category': '种子热梗词', 'match': 'exact'}
        tag_result = explain_tag_rule(raw)
        if not tag_result['accepted']:
            return tag_result
        for category, words in load_meme_stopwords().items():
            if raw in words:
                return {'accepted': False, 'layer': 'meme', 'category': category, 'match': 'exact'}
        return {'accepted': True, 'layer': 'none', 'category': '未命中过滤规则', 'match': None}
    raise ValueError('scope must be danmaku, tag or meme')
