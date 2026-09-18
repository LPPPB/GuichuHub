"""is_useless_tag / KICHU_TIDS / typeid 比较陷阱 单元测试。"""
import collectors.bilibili as bilibili
from storage.repositories.state import StateRepository
from collectors.bilibili import (
    is_useless_tag,
    KICHU_TIDS,
    KICHU_TID,
    load_tag_filters,
    DANMAKU_FALLBACK_WORDS,
)


# ────────────── KICHU_TIDS 常量 ──────────────

def test_kichu_tids_contains_four_subcategories():
    """鬼畜区 4 个子分区:22=鬼畜调教, 26=音MAD, 126=人力VOCALOID, 216=鬼畜剧场"""
    assert KICHU_TIDS == {22, 26, 126, 216}


def test_kichu_tids_excludes_retired():
    """已废弃/错配的分区不在集合:119(主分区)/127(教程)/218(动物)/221(野生动物)"""
    assert 119 not in KICHU_TIDS
    assert 127 not in KICHU_TIDS
    assert 218 not in KICHU_TIDS
    assert 221 not in KICHU_TIDS


def test_kichu_tid_legacy_constant():
    """KICHU_TID(旧版单分区常量)仍为 22(鬼畜调教),向后兼容"""
    assert KICHU_TID == 22


# ────────────── typeid 字符串/整数比较陷阱 ──────────────

def test_typeid_string_not_in_int_set():
    """搜索 API 返回的 typeid 是字符串,直接 in 整数集合会误判。
    这正是之前导致搜索结果全部被误杀的 bug 根源。
    """
    assert '22' not in KICHU_TIDS  # 字符串 '22' 不在整数集合里
    assert 22 in KICHU_TIDS        # 整数 22 在集合里
    # 正确做法:int() 转换后再比较
    assert int('22') in KICHU_TIDS
    assert int('126') in KICHU_TIDS


# ────────────── is_useless_tag ──────────────

def test_is_useless_tag_too_short():
    """长度 < 2 的标签无用"""
    assert is_useless_tag('')
    assert is_useless_tag('鬼')


def test_is_useless_tag_too_long():
    """长度 > 10 的标签无用"""
    assert is_useless_tag('这是一个超长的标签字符串超过十个字')


def test_is_useless_tag_stopwords_exact():
    """停用词表精确匹配"""
    assert is_useless_tag('鬼畜')
    assert is_useless_tag('视频')
    assert is_useless_tag('音乐')
    assert is_useless_tag('鬼畜调教')


def test_is_useless_tag_ad_brand_substring():
    """广告品牌子串匹配"""
    assert is_useless_tag('美团外卖')
    assert is_useless_tag('瑞幸咖啡')
    assert is_useless_tag('华为手机')


def test_is_useless_tag_activity_substring():
    """活动关键词子串匹配"""
    assert is_useless_tag('鬼畜星探企划')
    assert is_useless_tag('创作激励计划')
    assert is_useless_tag('新星大赛')


def test_is_useless_tag_year():
    """包含四位年份的标签无用"""
    assert is_useless_tag('2025鬼畜')
    assert is_useless_tag('年度2026')


def test_is_useless_tag_episode_format():
    """第X期格式无用"""
    assert is_useless_tag('第一期')
    assert is_useless_tag('第三季')


def test_is_useless_tag_pure_short_alnum():
    """纯英文/数字 ≤5 无用(AI/2024/speed)"""
    assert is_useless_tag('AI')
    assert is_useless_tag('speed')
    assert is_useless_tag('2024')


def test_is_useless_tag_two_char_not_in_whitelist():
    """二字词不在白名单内无用"""
    assert is_useless_tag('你好')  # 非梗
    assert is_useless_tag('今天')


def test_is_useless_tag_two_char_in_whitelist():
    """二字白名单内的梗词放行"""
    assert not is_useless_tag('叮咚')
    assert not is_useless_tag('哈基')
    assert not is_useless_tag('甲亢')
    assert not is_useless_tag('大狗')


def test_is_useless_tag_person_pattern():
    """大/小/老/新…哥/姐 模式泛称无用"""
    assert is_useless_tag('大哥哥')
    assert is_useless_tag('老姐姐')
    assert is_useless_tag('小弟弟')


def test_is_useless_tag_ad_explicit():
    """明确含广告/赞助字样无用"""
    assert is_useless_tag('某广告合集')
    assert is_useless_tag('恰饭视频')


def test_is_useless_tag_valid_meme_passes():
    """正常梗词应放行(长度3-10,非停用词/广告/活动)"""
    assert not is_useless_tag('哈基米')
    assert not is_useless_tag('阳光彩虹')
    assert not is_useless_tag('叮咚鸡')


def test_is_useless_tag_none_input():
    """None/空输入无用"""
    assert is_useless_tag(None)
    assert is_useless_tag('')


# ────────────── DANMAKU_FALLBACK_WORDS 与标签停用词 去重 ──────────────

def test_danmaku_words_no_stop_tags_overlap():
    """弹幕回退词库不应包含任何标签停用词（运行时加载配置）。

    标签停用词（tag_filters.json 的 categories 展开）被判定为"太通用、无区分度"
    (如 名场面/魔性/洗脑/666/yyds/三连),若同时出现在弹幕热词回退词库中会造成
    自相矛盾:同一词既被过滤又被推荐。重构(Step 5)已剔除 17 个重叠词,此测试锁定该不变量。
    """
    stop_lower = {w.lower() for ws in load_tag_filters()['categories'].values() for w in ws}
    overlap = [w for w in DANMAKU_FALLBACK_WORDS if w.lower() in stop_lower]
    assert overlap == [], f'弹幕回退词库与标签停用词重叠: {overlap}'


def test_danmaku_words_nonempty():
    """去重后词库仍应有足够词量作为回退"""
    assert len(DANMAKU_FALLBACK_WORDS) >= 100, \
        f'回退词库词量过少: {len(DANMAKU_FALLBACK_WORDS)}'


# ────────────── 标签过滤词表配置化（tag_filters.json） ──────────────

def test_tag_filters_load_structure():
    """真实配置结构完整：四段字段都存在且非空（categories 有 10+ 分类）"""
    filters = load_tag_filters()
    assert isinstance(filters['categories'], dict) and len(filters['categories']) >= 10
    assert filters['ad_keywords'], '广告品牌词表不应为空'
    assert filters['activity_keywords'], '活动词表不应为空'
    assert filters['allowed_two_char'], '二字白名单不应为空'
    # 分类展开后应覆盖代表性停用词
    stop = {w for ws in filters['categories'].values() for w in ws}
    assert '鬼畜' in stop and '视频' in stop and '瑞幸' in stop


def test_tag_filters_save_roundtrip(postgres_runtime):
    """save 后 load 应从 PostgreSQL 一致返回。"""
    filters = {
        'categories': {'测试分类': ['甲', '乙']},
        'ad_keywords': ['测试品牌'],
        'activity_keywords': ['测试活动'],
        'allowed_two_char': ['测试梗'],
    }
    bilibili.save_tag_filters(filters)
    assert bilibili.load_tag_filters() == filters


def test_tag_filters_cache_invalidated_on_save(postgres_runtime):
    """save 后缓存失效：is_useless_tag 立即用新配置，无需重启后端"""
    # 初始配置：不挡"新品牌"
    bilibili.save_tag_filters({
        'categories': {'分类': ['原词']},
        'ad_keywords': [], 'activity_keywords': [], 'allowed_two_char': [],
    })
    assert not is_useless_tag('新品牌')
    # 保存新广告词 → 立即生效
    bilibili.save_tag_filters({
        'categories': {'分类': ['原词']},
        'ad_keywords': ['新品牌'], 'activity_keywords': [], 'allowed_two_char': [],
    })
    assert is_useless_tag('新品牌手机')


def test_tag_filter_cache_refreshes_after_other_process_updates(
        postgres_runtime, postgres_url, monkeypatch):
    """A tag reader observes another process's update after the bounded cache window."""
    reader = postgres_runtime.state
    writer = StateRepository.from_url(postgres_url)
    clock = [100.0]
    monkeypatch.setattr(bilibili, '_monotonic', lambda: clock[0], raising=False)
    bilibili._invalidate_tag_filters()
    initial = {
        'categories': {'分类': ['原词']},
        'ad_keywords': [], 'activity_keywords': [], 'allowed_two_char': [],
    }
    updated = {**initial, 'ad_keywords': ['新品牌']}
    try:
        reader.save_setting('tag_filters', initial, 100)
        assert not is_useless_tag('新品牌手机')

        writer.save_setting('tag_filters', updated, 101)
        clock[0] = 3700.0

        assert is_useless_tag('新品牌手机')
    finally:
        bilibili._invalidate_tag_filters()
        writer._sessions.kw['bind'].dispose()


def test_tag_filters_fallback_without_database_override():
    """没有 PostgreSQL 覆盖值时使用内置兜底。"""
    bilibili._invalidate_tag_filters()
    filters = bilibili.load_tag_filters()
    stop = {w for ws in filters['categories'].values() for w in ws}
    assert '鬼畜' in stop
    assert '友望' in filters['ad_keywords']
    assert '企划' in filters['activity_keywords']
    assert '叮咚' in filters['allowed_two_char']


def test_tag_filters_fallback_is_complete():
    """内置兜底包含代表性规则。"""
    bilibili._invalidate_tag_filters()
    filters = bilibili.load_tag_filters()
    stop = {w for ws in filters['categories'].values() for w in ws}
    assert '鬼畜调教' in stop and '美团' in stop


if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v'])
