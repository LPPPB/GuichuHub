"""Regression cases from public meme/material payloads sampled 2026-10-24."""

import pytest

import collectors.bilibili as bili
from analytics.filters import explain_word
from utils.scorer import extract_keywords_from_title


def video(bvid, title, tags=()):
    return dict(bvid=bvid, title=title, tags=list(tags), views=800000,
                likes=10000, coins=100, favorites=100, shares=100,
                trend_score=60, author='测试作者')


@pytest.mark.parametrize('word', [
    '计划', '自己', 'AI', 'DJ', '经典', '神曲', '魔性', '一首',
    '音乐推荐', '音乐电台', '无损音质', '循环歌曲', '音乐资讯',
])
def test_materials_reject_obvious_noise_before_assignment(word):
    rows = [video(f'BV{i}', word) for i in range(3)]
    assert bili.get_meme_materials(rows, []) == []


@pytest.mark.parametrize('word', [
    '音乐推荐', '音乐电台', '音乐资讯', '无损音质', '循环歌曲',
])
def test_hot_memes_reject_generic_music_tags(word):
    assert bili.get_hot_memes([video('BV1', '演示', [word])], [], [], []) == []


@pytest.mark.parametrize('word', ['哈基米', '叮咚鸡', '面筋哥', '生命线の小曲', '音乐之王'])
def test_complete_meme_names_remain_eligible(word):
    rows = [video(f'BV{i}', f'【{word}】', [word]) for i in range(3)]
    assert word in {m['name'] for m in bili.get_meme_materials(rows, [], seed_words=[word])}
    assert word in {m['keyword'] for m in bili.get_hot_memes(rows, [], [], [])}


def test_seed_exemption_from_material_rules_is_preserved(monkeypatch):
    monkeypatch.setattr(bili, 'load_meme_stopwords', lambda: {'测试': ['电棍']})
    rows = [video('BV1', '电棍')]
    assert [m['name'] for m in bili.get_meme_materials(rows, [], seed_words=['电棍'])] == ['电棍']


def test_runtime_override_does_not_disable_common_noise_filter(monkeypatch):
    monkeypatch.setattr(bili, 'load_meme_stopwords', lambda: {'自定义': ['自定义噪声']})
    rows = [video(f'BV{i}', '自己 音乐推荐') for i in range(3)]
    assert bili.get_meme_materials(rows, []) == []
    assert bili.get_hot_memes([video('BV4', '演示', ['音乐推荐'])], [], [], []) == []


def test_title_suffix_does_not_capture_across_book_title_boundary():
    title = '《代号：神不言》UFSH2026参会实机技术演示&实机特别影像'
    assert extract_keywords_from_title(title) == []


@pytest.mark.parametrize('fragment', [
    '《代号：神', '【面筋哥', '面筋哥》',
    '[面筋哥', '面筋哥]', '{面筋哥', '面筋哥}',
])
def test_unbalanced_title_fragments_are_not_hot_memes(fragment):
    assert bili.get_hot_memes([video('BV1', '演示', [fragment])], [], [], []) == []


def test_intact_bracketed_and_suffix_names_still_extract():
    assert '面筋哥' in extract_keywords_from_title('翻唱：面筋哥！')
    assert '生命线の小曲' in extract_keywords_from_title('【生命线の小曲】')


@pytest.mark.parametrize('word', ['音乐推荐', '音乐电台', '《代号：神'])
def test_rule_preview_explains_same_noise_as_aggregators(word):
    assert not explain_word(word, 'meme')['accepted']


def test_explicit_two_char_seed_remains_eligible_in_hot_memes(monkeypatch):
    monkeypatch.setattr(bili, 'load_meme_seed_words', lambda: ['电棍'])
    assert [m['keyword'] for m in bili.get_hot_memes(
        [video('BV1', '【电棍】', ['电棍'])], [], [], [],
    )] == ['电棍']


@pytest.mark.parametrize('word', ['丁真', '电棍', '小苹果'])
def test_material_names_do_not_require_seed_or_tag_allowlist(word):
    rows = [video(f'BV{i}', word) for i in range(3)]
    assert [m['name'] for m in bili.get_meme_materials(rows, [])] == [word]
