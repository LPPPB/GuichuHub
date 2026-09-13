"""统一停用词表 + clean_text 预处理单元测试。

验证：
- STOPWORDS 是 Set、非空、含典型虚词（覆盖 biliscope 700 虚词 + 项目补充词）
- clean_text 去除 URL/bvid/av号/日期/IGNORE_WORDS/标点
- WORD_PATTERN 匹配中文/字母数字（≥2字）
"""
from utils.stopwords import STOPWORDS, IGNORE_WORDS, WORD_PATTERN, clean_text


# ==================== STOPWORDS 集合 ====================

def test_stopwords_is_set_and_nonempty():
    """STOPWORDS 是 Set，且足够大（biliscope 700+ 虚词）"""
    assert isinstance(STOPWORDS, set)
    assert len(STOPWORDS) > 500


def test_stopwords_contains_typical_function_words():
    """覆盖典型中文虚词（代词/介词/连词/助词）"""
    for w in ['的', '了', '是', '在', '我', '你', '他', '这', '那', '和', '与', '或',
              '因为', '所以', '如果', '虽然', '但是', '而且']:
        assert w in STOPWORDS, f'缺失典型虚词: {w}'


def test_stopwords_contains_danmaku_extras():
    """包含 _DANMAKU_STOPWORDS 的补充词"""
    for w in ['哈哈', '哈哈哈', '哔哩', 'bilibili', '时候', '知道', '觉得']:
        assert w in STOPWORDS, f'缺失弹幕补充词: {w}'


def test_stopwords_contains_generic_danmaku_reactions():
    for w in ['其实', '可能', '好听', '确实', '后面', '直接', '小时']:
        assert w in STOPWORDS, f'缺失通用弹幕噪声词: {w}'


def test_stopwords_contains_biliscope_pronouns():
    """包含 biliscope 的代词/语气词"""
    for w in ['我们', '你们', '他们', '什么', '怎么', '为什么', '哪里', '谁']:
        assert w in STOPWORDS


# ==================== clean_text 预处理 ====================

def test_clean_text_removes_url():
    s = '看这个 https://www.bilibili.com/video/BV1xx 视频'
    cleaned = clean_text(s)
    assert 'https' not in cleaned
    assert 'bilibili.com' not in cleaned


def test_clean_text_removes_bvid():
    """bvid（BV1xxxxxxxxx）应被去除"""
    s = '推荐 BV1GJ411x7h7 这个'
    cleaned = clean_text(s)
    assert 'BV1GJ411x7h7' not in cleaned


def test_clean_text_removes_avid():
    """av号应被去除"""
    s = '老视频 av12345 经典 AV67890'
    cleaned = clean_text(s)
    assert 'av12345' not in cleaned
    assert 'AV67890' not in cleaned


def test_clean_text_removes_date():
    """日期格式应被去除"""
    s = '发布于 2024-01-15 和 2024/3/1'
    cleaned = clean_text(s)
    assert '2024-01-15' not in cleaned
    assert '2024/3/1' not in cleaned


def test_clean_text_removes_ignore_words():
    """IGNORE_WORDS（平台噪声 + 制作噪声）整词剔除"""
    s = '鬼畜调教视频制作原创剪辑'
    cleaned = clean_text(s)
    for w in ['鬼畜', '调教', '视频', '制作', '原创', '剪辑']:
        assert w not in cleaned, f'IGNORE_WORDS 未剔除: {w}'


def test_clean_text_removes_punctuation():
    """常见标点替换为空格"""
    s = '【标题】《引用》〖注〗'
    cleaned = clean_text(s)
    for p in ['【', '】', '《', '》', '〖', '〗']:
        assert p not in cleaned


def test_clean_text_empty():
    """空输入返回空字符串"""
    assert clean_text('') == ''
    assert clean_text(None) == ''


def test_clean_text_preserves_content_words():
    """正常内容词不应被误删"""
    s = '蔡徐坤打篮球'
    cleaned = clean_text(s)
    assert '蔡徐坤' in cleaned or '蔡' in cleaned  # 至少保留内容字


# ==================== WORD_PATTERN ====================

def test_word_pattern_matches_chinese():
    assert WORD_PATTERN.match('蔡徐坤')
    assert WORD_PATTERN.match('鬼畜')
    assert WORD_PATTERN.match('篮球')


def test_word_pattern_matches_alnum():
    assert WORD_PATTERN.match('AI')
    assert WORD_PATTERN.match('VOCALOID')
    assert WORD_PATTERN.match('abc123')


def test_word_pattern_rejects_single_char():
    assert not WORD_PATTERN.match('的')
    assert not WORD_PATTERN.match('A')
    assert not WORD_PATTERN.match('1')


def test_word_pattern_rejects_punctuation():
    assert not WORD_PATTERN.match('！！')
    assert not WORD_PATTERN.match('a!')


def test_word_pattern_rejects_empty():
    assert not WORD_PATTERN.match('')


# ==================== IGNORE_WORDS ====================

def test_ignore_words_contains_platform_terms():
    """平台交互词（biliscope）"""
    for w in ['视频', '关注', '点赞', '投币', '收藏', '三连', '转发']:
        assert w in IGNORE_WORDS


def test_ignore_words_contains_kichu_production_terms():
    """鬼畜区制作噪声词"""
    for w in ['鬼畜', '制作', '原创', '剪辑', '合集', '教程']:
        assert w in IGNORE_WORDS


if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v'])
