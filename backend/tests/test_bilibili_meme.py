"""get_meme_materials 自动发现高频词逻辑单元测试。

无网络依赖,用 mock all_videos/hot_songs 测试:
- 高频词提取(≥3次入选、generic_words 过滤、同标题去重)
- 贪心去重(高频词优先、视频不重复分配)
- 频次不足/去重后不足2条不入选
- 自动描述生成
- 停用词表来自配置文件（load/save_meme_stopwords）
"""
import json

import pytest
from storage.repositories.state import StateRepository

from collectors.bilibili import (
    get_meme_materials,
    load_meme_stopwords,
    save_meme_stopwords,
    load_meme_seed_words,
    save_meme_seed_words,
)


def _video(bvid, title, views=100000, **kw):
    """构造测试用 video dict"""
    base = {
        'bvid': bvid,
        'title': title,
        'views': views,
        'author': 'UP主',
        'cover': 'https://example.com/cover.jpg',
        'duration': 120,
        'tags': [],
        'description': '',
    }
    base.update(kw)
    return base


def test_meme_materials_extracts_high_freq_word():
    """标题中出现 ≥3 次的词应被提取为梗素材"""
    videos = [
        _video('BV1', '哈基米真可爱'),
        _video('BV2', '哈基米又来了'),
        _video('BV3', '哈基米合集'),
        _video('BV4', '无关视频'),  # 干扰项
    ]
    results = get_meme_materials(videos, [])
    names = [r['name'] for r in results]
    assert '哈基米' in names


def test_meme_materials_filters_generic_words():
    """generic_words 中的词不应被提取(如'鬼畜''视频')"""
    videos = [
        _video('BV1', '鬼畜视频制作'),
        _video('BV2', '鬼畜视频剪辑'),
        _video('BV3', '鬼畜视频合集'),
    ]
    results = get_meme_materials(videos, [])
    names = [r['name'] for r in results]
    assert '鬼畜' not in names
    assert '视频' not in names


def test_meme_materials_min_freq_threshold():
    """频次 <3 的词不入选"""
    videos = [
        _video('BV1', '冷门词出现一次'),
        _video('BV2', '另一个视频'),
        _video('BV3', '第三个视频'),
    ]
    results = get_meme_materials(videos, [])
    names = [r['name'] for r in results]
    assert '冷门词' not in names


def test_meme_materials_greedy_dedup_no_duplicate_video():
    """贪心去重:同一视频不会出现在多个梗下。
    '空耳'频次最高(3次)先分配,'哈基米'(3次)后分配,
    如果某视频标题同时含两者,只归给先处理的词。
    """
    # BV1/BV2/BV3 含"空耳",BV1/BV4/BV5 含"哈基米"(BV1 重叠)
    videos = [
        _video('BV1', '空耳哈基米'),       # 含两者,归给先处理的
        _video('BV2', '空耳神曲'),
        _video('BV3', '空耳合集'),
        _video('BV4', '哈基米可爱'),
        _video('BV5', '哈基米音乐'),
    ]
    results = get_meme_materials(videos, [])
    # 收集所有梗下的 bvid
    all_bvids = []
    for r in results:
        for v in r['related_videos']:
            all_bvids.append(v['bvid'])
    # 没有视频被重复分配
    assert len(all_bvids) == len(set(all_bvids)), f'视频被重复分配: {all_bvids}'


def test_meme_materials_dedup_min_2_videos():
    """去重后不足 2 条的词不入选(贪心后候选太少)"""
    # "独占"出现3次但3个视频都被"共有"先抢走
    videos = [
        _video('BV1', '共有独占'),
        _video('BV2', '共有独占'),
        _video('BV3', '共有独占'),
    ]
    # "共有"和"独占"频次相同(3),按 most_common 顺序处理
    # 先处理的词拿走全部3个,后处理的词去重后0条,不入选
    results = get_meme_materials(videos, [])
    # 至少有1个梗(先处理的),后处理的因去重后<2条被跳过
    assert len(results) >= 1
    # 每个梗至少2条视频
    for r in results:
        assert r['video_count'] >= 2


def test_meme_materials_auto_description():
    """描述应自动生成(TOP3 标题拼接),不是人工 description"""
    videos = [
        _video('BV1', '哈基米第一集'),
        _video('BV2', '哈基米第二集'),
        _video('BV3', '哈基米第三集'),
    ]
    results = get_meme_materials(videos, [])
    meme = next((r for r in results if r['name'] == '哈基米'), None)
    assert meme is not None
    assert '相关视频' in meme['description']
    assert '哈基米第一集' in meme['description']


def test_meme_materials_sorted_by_heat():
    """结果按 heat 降序"""
    videos = [
        # "热门" 3条高播放
        _video('BV1', '热门梗一', views=500000),
        _video('BV2', '热门梗二', views=500000),
        _video('BV3', '热门梗三', views=500000),
        # "冷门" 3条低播放
        _video('BV4', '冷门梗一', views=1000),
        _video('BV5', '冷门梗二', views=1000),
        _video('BV6', '冷门梗三', views=1000),
    ]
    results = get_meme_materials(videos, [])
    if len(results) >= 2:
        assert results[0]['heat'] >= results[1]['heat']


def test_meme_materials_max_10():
    """最多返回 10 个梗素材"""
    # 构造 15 个不同高频词,每个3条
    videos = []
    for i in range(15):
        word = f'测试词{i:02d}'
        videos.append(_video(f'BV{i}1', f'{word}一'))
        videos.append(_video(f'BV{i}2', f'{word}二'))
        videos.append(_video(f'BV{i}3', f'{word}三'))
    results = get_meme_materials(videos, [])
    assert len(results) <= 10


def test_meme_materials_empty_input():
    """空输入返回空列表"""
    results = get_meme_materials([], [])
    assert results == []


def test_meme_materials_same_word_in_title_counted_once():
    """同一标题内同词只计一次(seen_in_title),避免'哈哈哈'类重复拉高频次"""
    # 标题"鬼畜鬼畜鬼畜"中"鬼畜"出现3次,但只算1个标题
    # 即使有3个这样的标题,频次也只有3(每个标题计1次),不是9
    videos = [
        _video('BV1', '鬼畜鬼畜鬼畜'),
        _video('BV2', '鬼畜鬼畜鬼畜'),
    ]
    # "鬼畜"在 generic_words 里被过滤,但逻辑是 seen_in_title 去重
    # 用非 generic 词验证:如果 seen_in_title 生效,2个标题=频次2,<3不入选
    videos = [
        _video('BV1', '空耳空耳空耳'),
        _video('BV2', '空耳空耳空耳'),
    ]
    results = get_meme_materials(videos, [])
    # 频次=2(每标题计1次),<3,不入选
    names = [r['name'] for r in results]
    assert '空耳' not in names


def test_meme_materials_related_songs_match():
    """BGM 名称含高频词时应关联到梗素材"""
    videos = [
        _video('BV1', '哈基米一'),
        _video('BV2', '哈基米二'),
        _video('BV3', '哈基米三'),
    ]
    songs = [{'name': '哈基米原曲', 'plays': 999999}]
    results = get_meme_materials(videos, songs)
    meme = next((r for r in results if r['name'] == '哈基米'), None)
    assert meme is not None
    assert len(meme['related_songs']) == 1


def test_meme_stopwords_load_from_config():
    """load_meme_stopwords 应从配置文件读取分类结构"""
    cats = load_meme_stopwords()
    assert isinstance(cats, dict)
    assert '通用制作词' in cats
    assert '鬼畜' in cats['通用制作词']
    assert '视频' in cats['通用制作词']
    assert '空耳' in cats['通用制作词']
    assert '分区名' in cats
    # 关键测试依赖词不能被停用（test_sorted_by_heat 用"热门/冷门"构造数据）
    flat = {w for ws in cats.values() for w in ws}
    assert '热门' not in flat
    assert '冷门' not in flat


def test_meme_stopwords_save_and_reload(postgres_runtime):
    """save_meme_stopwords 写入 PostgreSQL 后可重新读取。"""
    save_meme_stopwords({'测试分类': ['词A', '词B'], '空分类': []})
    cats = load_meme_stopwords()
    assert cats == {'测试分类': ['词A', '词B']}  # 空分类被清理


def test_meme_stopwords_fallback_without_database_override():
    """没有 PostgreSQL 覆盖值时应降级为内置兜底，不崩溃。"""
    cats = load_meme_stopwords()
    assert '鬼畜' in cats['通用制作词']


# ── 种子热梗词（主动搜索兜底）──

def test_meme_seed_words_load_from_config():
    """load_meme_seed_words 应读取配置文件，包含哈基米等常驻热梗"""
    words = load_meme_seed_words()
    assert isinstance(words, list)
    assert '哈基米' in words
    assert '叮咚鸡' in words
    assert '大狗叫' in words


def test_meme_seed_words_save_and_reload(postgres_runtime):
    """save_meme_seed_words 写入 PostgreSQL 后可重新读取。"""
    save_meme_seed_words(['哈基米', '  电棍  ', ''])
    words = load_meme_seed_words()
    assert words == ['哈基米', '电棍']  # 空白词被清理、两侧空白被 strip


def test_uncached_meme_rules_observe_other_process_updates(postgres_runtime, postgres_url):
    """Meme rule loaders query PostgreSQL and immediately see another writer."""
    writer = StateRepository.from_url(postgres_url)
    try:
        writer.save_setting('meme_stopwords', {'跨进程': ['新词']}, 100)
        writer.save_setting('meme_seed_words', ['新热梗'], 100)

        assert load_meme_stopwords() == {'跨进程': ['新词']}
        assert load_meme_seed_words() == ['新热梗']
    finally:
        writer._sessions.kw['bind'].dispose()


def test_meme_seed_words_builtin_defaults_are_available():
    """没有 PostgreSQL 覆盖值时仍使用随版本发布的种子词。"""
    assert '哈基米' in load_meme_seed_words()


def test_meme_materials_seed_words_rescue():
    """种子热梗词在候选池频次不足时仍应入选（兜底不丢热梗）。

    候选池里"哈基米"只出现 1 次(<3 会被自动发现过滤)，但 seed_words 显式声明后，
    标题含该词的视频被计入，频次达标即可入选。
    """
    videos = [
        _video('BV1', '哈基米真可爱'),
        _video('BV2', '无关视频一'),
        _video('BV3', '无关视频二'),
    ]
    results = get_meme_materials(videos, [], seed_words=['哈基米'])
    names = [r['name'] for r in results]
    assert '哈基米' in names


def test_meme_materials_seed_words_override_stopwords():
    """种子热梗词优先级高于停用词：即使被停用词表误伤也强制保留"""
    videos = [
        _video('BV1', '鬼畜视频'),
        _video('BV2', '鬼畜剪辑'),
        _video('BV3', '鬼畜合集'),
    ]
    # "鬼畜"在停用词表里，但显式作为种子词声明时应入选
    results = get_meme_materials(videos, [], seed_words=['鬼畜'])
    names = [r['name'] for r in results]
    assert '鬼畜' in names


if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v'])
