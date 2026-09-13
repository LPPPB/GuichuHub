"""extract_keyword_cloud 单元测试：jieba 分词 + biliscope 权重 + 停用词过滤。

测试两类场景：
1. mock jieba.cut：验证权重/过滤/结构逻辑（稳定，不依赖 jieba 词典）
2. 真实 jieba：验证长标题被拆分（非整块保留）
"""
import jieba  # 确保模块加载，便于 monkeypatch
import pytest
from collectors.bilibili_user import extract_keyword_cloud


def _fake_cut(text, **kwargs):
    """假分词：按空格切（mock jieba.cut 用，可控分词结果）
    **kwargs 兼容真实调用参数（HMM=False），mock 不关心分词模式。
    """
    return text.split()


# ==================== 返回结构 ====================

def test_returns_correct_structure(monkeypatch):
    """返回 [{'text','count'}] 结构，保持前端 UpTrends.jsx 契约"""
    monkeypatch.setattr('jieba.cut', _fake_cut)
    videos = [
        {'title': '蔡徐坤 篮球', 'description': ''},
        {'title': '蔡徐坤 篮球', 'description': ''},
    ]
    result = extract_keyword_cloud(videos)
    assert isinstance(result, list)
    assert all(isinstance(item, dict) for item in result)
    assert all('text' in item and 'count' in item for item in result)
    texts = [item['text'] for item in result]
    assert '蔡徐坤' in texts
    assert '篮球' in texts


def test_empty_videos():
    """空视频列表返回空列表"""
    assert extract_keyword_cloud([]) == []


# ==================== 真实 jieba 分词 ====================

def test_jieba_real_segmentation():
    """真实 jieba 分词：长标题应被拆分，而非整块保留（原 re.split bug）"""
    title = '鬼畜大赏第三期颁奖典礼'
    videos = [{'title': title, 'description': ''}] * 2
    result = extract_keyword_cloud(videos)
    texts = [item['text'] for item in result]
    # 整块标题不应出现（原 re.split 会保留整块"鬼畜大赏第三期颁奖典礼"）
    assert title not in texts
    # jieba 应分出至少一个子词（频次≥2）
    assert len(result) >= 1


def test_jieba_segments_person_name():
    """jieba 真分词：人名标题应被拆分，而非整块保留。
    注：jieba 默认词典可能拆"蔡徐坤"→"蔡"+"徐坤"（专有名词局限），
    本测试只验证"整块不出现"，不依赖具体分词结果。
    """
    videos = [{'title': '蔡徐坤打篮球', 'description': ''}] * 2
    result = extract_keyword_cloud(videos)
    texts = [item['text'] for item in result]
    assert '蔡徐坤打篮球' not in texts  # 整块不出现
    assert len(result) >= 1  # 至少分出1个词


# ==================== 权重设计（title=3, desc=1）====================

def test_title_desc_weight(monkeypatch):
    """title 权重3, desc 权重1（借鉴 biliscope）"""
    monkeypatch.setattr('jieba.cut', _fake_cut)
    videos = [
        {'title': '词A', 'description': '词B'},
        {'title': '词A', 'description': '词B'},
    ]
    result = extract_keyword_cloud(videos)
    d = {item['text']: item['count'] for item in result}
    # key 为小写（seen.add(w.lower())）；2视频 × title权重3 = 6
    assert d.get('词a') == 6
    # 2视频 × desc权重1 = 2
    assert d.get('词b') == 2


def test_title_weight_dominates(monkeypatch):
    """同词在 title 和 desc 都出现：两文本独立加权（3+1=4 per 视频，借鉴 biliscope）"""
    monkeypatch.setattr('jieba.cut', _fake_cut)
    videos = [
        {'title': '蔡徐坤', 'description': '蔡徐坤'},
    ] * 2
    result = extract_keyword_cloud(videos)
    d = {item['text']: item['count'] for item in result}
    # title(3) + desc(1) = 4 per 视频，2视频 = 8
    assert d.get('蔡徐坤') == 8


# ==================== 停用词过滤 ====================

def test_stopwords_filtered(monkeypatch):
    """中文虚词被过滤"""
    monkeypatch.setattr('jieba.cut', _fake_cut)
    videos = [
        {'title': '的 了 蔡徐坤', 'description': ''},
    ] * 2
    result = extract_keyword_cloud(videos)
    texts = [item['text'] for item in result]
    assert '的' not in texts
    assert '了' not in texts
    assert '蔡徐坤' in texts


def test_ignore_words_removed_by_clean_text(monkeypatch):
    """IGNORE_WORDS（鬼畜/视频等）被 clean_text 整词去除"""
    monkeypatch.setattr('jieba.cut', _fake_cut)
    videos = [
        {'title': '鬼畜 蔡徐坤', 'description': ''},
    ] * 2
    result = extract_keyword_cloud(videos)
    texts = [item['text'] for item in result]
    assert '鬼畜' not in texts  # IGNORE_WORDS
    assert '蔡徐坤' in texts


# ==================== 预处理 ====================

def test_bvid_removed_by_clean_text(monkeypatch):
    """bvid 被 clean_text 预处理去除，不进词云"""
    monkeypatch.setattr('jieba.cut', _fake_cut)
    videos = [
        {'title': 'BV1GJ411x7h7 蔡徐坤', 'description': ''},
    ] * 2
    result = extract_keyword_cloud(videos)
    texts = [item['text'] for item in result]
    assert 'BV1GJ411x7h7' not in texts
    assert '蔡徐坤' in texts


def test_url_removed_by_clean_text(monkeypatch):
    """URL 被 clean_text 预处理去除"""
    monkeypatch.setattr('jieba.cut', _fake_cut)
    videos = [
        {'title': 'https://bilibili.com 蔡徐坤', 'description': ''},
    ] * 2
    result = extract_keyword_cloud(videos)
    texts = [item['text'] for item in result]
    assert not any('bilibili' in t for t in texts)
    assert '蔡徐坤' in texts


# ==================== 频次过滤 ====================

def test_min_count_filter(monkeypatch):
    """频次<2 的词被过滤"""
    monkeypatch.setattr('jieba.cut', _fake_cut)
    # 单视频 desc-only 词：权重1，count=1<2 被过滤
    # 单视频 title 词：权重3，count=3≥2 保留
    videos = [
        {'title': '蔡徐坤', 'description': '罕见词'},
    ]
    result = extract_keyword_cloud(videos)
    texts = [item['text'] for item in result]
    assert '罕见词' not in texts  # count=1 被过滤
    assert '蔡徐坤' in texts  # count=3 保留


# ==================== content_type 不污染 ====================

def test_content_type_not_injected(monkeypatch):
    """content_type 标签不混入词云（原 extract_keywords 的 bug）"""
    monkeypatch.setattr('jieba.cut', _fake_cut)
    # 标题含 VOCALOID（CONTENT_TYPES['调音']关键词），但标题不含"调音"
    videos = [
        {'title': 'VOCALOID 作品', 'description': ''},
    ] * 2
    result = extract_keyword_cloud(videos)
    texts = [item['text'] for item in result]
    assert '调音' not in texts  # content_type 名字不应被注入


# ==================== 大小写归并 ====================

def test_lowercase_normalization(monkeypatch):
    """大小写归并（AI=ai，借鉴弹幕词云 display_forms 策略）"""
    monkeypatch.setattr('jieba.cut', _fake_cut)
    videos = [
        {'title': 'AI 技术', 'description': ''},
        {'title': 'ai 智能', 'description': ''},
    ]
    result = extract_keyword_cloud(videos)
    d = {item['text']: item['count'] for item in result}
    # AI 和 ai 归并为一项（key 为小写 'ai'），count = 3 + 3 = 6
    assert 'ai' in d
    assert d['ai'] == 6


# ==================== 同文本去重 ====================

def test_same_word_in_one_text_counted_once(monkeypatch):
    """同一标题内重复词只计一次（避免'哈哈哈'重复拉高）"""
    monkeypatch.setattr('jieba.cut', _fake_cut)
    videos = [
        {'title': '蔡徐坤 蔡徐坤 蔡徐坤', 'description': ''},
    ]
    result = extract_keyword_cloud(videos)
    d = {item['text']: item['count'] for item in result}
    # 1视频 × title权重3 = 3（不是 9）
    assert d.get('蔡徐坤') == 3


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
