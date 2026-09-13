"""热门BGM / 热梗榜 过滤规则单元测试。

锁定 2026-08-01 过滤规则优化：
- get_hot_songs 白名单式按 MUSIC_TIDS 过滤（非音乐分区一律剔除）
- get_hot_memes 使用 config.HOT_MEME_VIEWS_MIN 阈值（不再硬编码 300000）

2026-08-02 追加：
- get_hot_memes 复用梗素材库停用词表（utils/meme_stopwords.json，开发者后台可编辑），
  种子热梗词豁免（与 get_meme_materials 语义一致）。
"""
import pytest

import collectors.bilibili as bilibili
from config import HOT_MEME_VIEWS_MIN
from collectors.bilibili import get_hot_songs, get_hot_memes, is_useless_tag


def _video(bvid, title, tid, views=100000, likes=1000, coins=100,
           favorites=50, shares=20, danmaku=200, trend=60, tags=None):
    """构造带 tid 的标准化 video dict（与 parse_video_item 输出同构）"""
    return {
        'bvid': bvid,
        'title': title,
        'tid': tid,
        'tname': '',
        'views': views,
        'likes': likes,
        'coins': coins,
        'favorites': favorites,
        'shares': shares,
        'danmaku': danmaku,
        'trend_score': trend,
        'trend_label': '上升期',
        'tags': tags or [],
        'cover': 'https://example.com/cover.jpg',
        'duration': 120,
        'author': 'UP主',
        'url': f'https://www.bilibili.com/video/{bvid}',
        'pub_date': 1700000000,
    }


# ────────────── get_hot_songs 白名单分区过滤 ──────────────

def test_hot_songs_only_music_tids():
    """BGM 榜只收 MUSIC_TIDS 音乐分区视频，非音乐分区（动物圈/生活/搞笑）一律剔除"""
    music = _video('BVM1', '原创音乐', 28)      # 音乐子分区 ✓
    kichu = _video('BVK1', '鬼畜调教', 22)       # 鬼畜 ✗
    animal = _video('BVA1', '喵喵喵', 218)       # 喵星人 ✗
    funny = _video('BVF1', '搞笑合集', 138)      # 搞笑 ✗
    results = get_hot_songs([music, kichu, animal, funny], [])
    bvids = [r['bvid'] for r in results]
    assert 'BVM1' in bvids
    assert 'BVK1' not in bvids
    assert 'BVA1' not in bvids
    assert 'BVF1' not in bvids


# ────────────── get_hot_memes 阈值配置化 ──────────────

def test_hot_memes_uses_config_threshold():
    """热梗聚合总播放量必须 > config.HOT_MEME_VIEWS_MIN 才入选（不再硬编码）"""
    assert HOT_MEME_VIEWS_MIN == 300000  # 默认值与历史硬编码一致

    # 恰好等于阈值 → 不入选（语义是严格大于）
    videos = [_video('BV1', '【哈基米】真可爱', 22, views=HOT_MEME_VIEWS_MIN)]
    results = get_hot_memes(videos, [], [], [])
    assert results == [], '总播放量等于阈值不应入选'

    # 超过阈值 → 入选
    videos = [_video('BV2', '【哈基米】真可爱', 22, views=HOT_MEME_VIEWS_MIN + 1)]
    results = get_hot_memes(videos, [], [], [])
    assert any(r['keyword'] == '哈基米' for r in results)


def test_hot_memes_removes_useless_keywords():
    """热梗提取应通过 is_useless_tag 剔除广告/活动/平台词"""
    videos = [
        _video('BV1', '【瑞幸咖啡】广告合集', 22, views=500000),
        _video('BV2', '【美团外卖】洗脑神曲', 22, views=500000),
        _video('BV3', '【哈基米】真可爱', 22, views=500000),
    ]
    results = get_hot_memes(videos, [], [], [])
    keywords = [r['keyword'] for r in results]
    assert '瑞幸咖啡' not in keywords
    assert '美团外卖' not in keywords
    assert '哈基米' in keywords


# ────────────── get_hot_memes 复用梗素材库停用词表 ──────────────

def test_hot_memes_uses_meme_stopwords(monkeypatch):
    """热梗库应复用梗素材库停用词表（开发者后台配置，下次抓取生效）"""
    monkeypatch.setattr(bilibili, 'load_meme_stopwords', lambda: {'泛标签': ['原创曲', '本家投稿']})
    videos = [
        _video('BV1', '【原创曲】热曲', 22, views=500000, tags=['原创曲']),
        _video('BV2', '【本家投稿】串烧', 22, views=500000, tags=['本家投稿']),
        _video('BV3', '【哈基米】真可爱', 22, views=500000, tags=['哈基米']),
    ]
    results = get_hot_memes(videos, [], [], [])
    keywords = [r['keyword'] for r in results]
    assert '原创曲' not in keywords
    assert '本家投稿' not in keywords
    assert '哈基米' in keywords


def test_hot_memes_seed_words_exempt_from_stopwords(monkeypatch):
    """种子热梗词即使被停用词表误伤也保留（与 get_meme_materials 语义一致）"""
    monkeypatch.setattr(bilibili, 'load_meme_stopwords', lambda: {'测试分类': ['哈基米']})
    monkeypatch.setattr(bilibili, 'load_meme_seed_words', lambda: ['哈基米'])
    videos = [
        _video('BV1', '【哈基米】真可爱', 22, views=500000, tags=['哈基米']),
        _video('BV2', '【无关词】内容', 22, views=500000, tags=['无关词']),
    ]
    results = get_hot_memes(videos, [], [], [])
    keywords = [r['keyword'] for r in results]
    assert '哈基米' in keywords, '种子热梗词应豁免停用词表'


def test_hot_memes_ad_brand_substring_filtered():
    """广告品牌子串匹配：品牌变体 tag 应被剔除（如 友望 系列吸尘器）"""
    videos = [
        _video('BV1', '【广告】演示', 22, views=500000, tags=['友望自动集尘吸尘器']),
        _video('BV2', '【哈基米】真可爱', 22, views=500000),
    ]
    results = get_hot_memes(videos, [], [], [])
    keywords = [r['keyword'] for r in results]
    assert '友望自动集尘吸尘器' not in keywords
    assert '哈基米' in keywords


if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v'])
