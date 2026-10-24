"""Canonical identity is resolved before independent-video admission."""

import pytest
from copy import deepcopy

import collectors.bilibili as bili
from analytics.filters import explain_word


def video(bvid, title='演示', tags=(), views=500000):
    return dict(bvid=bvid, title=title, tags=list(tags), views=views,
                likes=1000, coins=100, favorites=50, shares=20,
                trend_score=60, author='测试作者')


@pytest.mark.parametrize('alias', ['哈 基 米', '哈　基　米', 'Hachimi', 'HACHIMI', 'Ｈａｃｈｉｍｉ'])
def test_aliases_combine_before_two_video_gate(alias):
    rows = [video('BV1', tags=['哈基米']), video('BV2', tags=[alias])]
    result = bili.get_hot_memes(rows, [], [], [])
    assert len(result) == 1
    assert result[0]['keyword'] == '哈基米'
    assert result[0]['meme_id'] == 'meme_hajimi'
    assert result[0]['video_count'] == 2
    assert result[0]['total_views'] == 1000000
    assert result[0]['total_engagement'] == 2340
    assert result[0]['trend_score'] == 60
    assert result[0]['related_videos'][1]['title'] == '演示'
    assert alias in result[0]['related_videos'][1]['matched_keywords']


def test_one_video_with_all_aliases_cannot_supply_two_video_evidence():
    row = video('BV1', '哈 基 米 HACHIMI', ['哈基米', 'Hachimi', '哈 基 米'])
    assert bili.get_hot_memes([row], [row], [], []) == []


def test_known_aliases_in_plain_titles_are_discovered_without_tags():
    rows = [video('BV1', '今天的哈 基 米'), video('BV2', 'HACHIMI remix')]
    result = bili.get_hot_memes(rows, [], [], [])
    assert [m['keyword'] for m in result] == ['哈基米']
    assert result[0]['video_count'] == 2
    assert [v['title'] for v in result[0]['related_videos']] == ['今天的哈 基 米', 'HACHIMI remix']


def test_matching_multiple_aliases_never_inflates_video_statistics():
    rows = [video('BV1', '哈基米 Hachimi', ['哈 基 米', 'HACHIMI']),
            video('BV2', 'HACHIMI', ['哈基米'])]
    result = bili.get_hot_memes(rows, rows, [], [])
    assert len(result) == 1
    assert result[0]['video_count'] == 2
    assert result[0]['total_views'] == 1000000
    assert len({v['bvid'] for v in result[0]['related_videos']}) == 2


@pytest.mark.parametrize('forms', [('Banana', 'banana'), ('Ｂａｎａｎａ', 'Banana'),
                                  ('神秘新梗', '神 秘 新 梗')])
def test_unlisted_format_variants_still_discover_new_memes(forms):
    rows = [video('BV1', tags=[forms[0]]), video('BV2', tags=[forms[1]])]
    forward = bili.get_hot_memes(rows, [], [], [])
    reverse = bili.get_hot_memes(rows[::-1], [], [], [])
    assert len(forward) == 1
    assert forward[0]['meme_id'] == reverse[0]['meme_id']
    assert forward[0]['keyword'] == reverse[0]['keyword']
    assert forward[0]['video_count'] == 2


def test_similar_containing_names_are_not_merged_without_confirmed_aliases():
    rows = [video('BV1', tags=['哈基米']), video('BV2', tags=['哈基米']),
            video('BV3', tags=['哈基米南北绿豆']), video('BV4', tags=['哈基米南北绿豆'])]
    result = bili.get_hot_memes(rows, [], [], [])
    assert {m['keyword'] for m in result} == {'哈基米', '哈基米南北绿豆'}
    assert {m['video_count'] for m in result} == {2}


def test_cosmetic_changes_do_not_bypass_noise_filtering():
    rows = [video('BV1', tags=['音 乐 推 荐']), video('BV2', tags=['音乐推荐'])]
    assert bili.get_hot_memes(rows, [], [], []) == []


def test_alias_stopwords_apply_to_the_canonical_identity(monkeypatch):
    monkeypatch.setattr(bili, 'load_meme_seed_words', lambda: [])
    monkeypatch.setattr(bili, 'load_meme_stopwords', lambda: {'已屏蔽': ['Hachimi']})
    rows = [video('BV1', tags=['哈基米']), video('BV2', tags=['哈基米'])]
    assert bili.get_hot_memes(rows, [], [], []) == []


def test_normalization_preserves_english_word_separators_and_punctuation():
    from utils.meme_aliases import normalize_meme_key
    assert normalize_meme_key('Rock Roll') != normalize_meme_key('RockRoll')
    assert normalize_meme_key('Rock & Roll') != normalize_meme_key('Rock Roll')
    assert normalize_meme_key('【面筋哥') == '【面筋哥'


def test_alias_config_rejects_conflicting_normalized_names():
    from utils.meme_aliases import MemeAliasIndex
    with pytest.raises(ValueError, match='conflict'):
        MemeAliasIndex([
            {'id': 'meme_one', 'name': '第一梗名', 'aliases': ['Banana']},
            {'id': 'meme_two', 'name': '第二梗名', 'aliases': ['ＢＡＮＡＮＡ']},
        ])


@pytest.mark.parametrize('records', [
    [{'id': 'meme_one', 'name': '', 'aliases': []}],
    [{'id': 'meme_one', 'name': '第一梗名', 'aliases': ['']}],
    [{'id': 'meme_one', 'name': '第一梗名', 'aliases': []},
     {'id': 'meme_one', 'name': '第二梗名', 'aliases': []}],
])
def test_invalid_alias_configuration_fails_explicitly(records):
    from utils.meme_aliases import MemeAliasIndex
    with pytest.raises(ValueError):
        MemeAliasIndex(records)


@pytest.mark.parametrize('seeds, expected', [([], False), (['哈基米'], True)])
def test_exact_tag_blacklist_follows_alias_identity_and_seed_precedence(monkeypatch, seeds, expected):
    filters = deepcopy(bili._get_tag_filters())
    filters['stop_set'].add('hachimi')
    monkeypatch.setattr(bili, '_get_tag_filters', lambda: filters)
    monkeypatch.setattr(bili, 'load_meme_seed_words', lambda: seeds)
    rows = [video('BV1', tags=['哈基米']), video('BV2', tags=['哈基米'])]
    assert bool(bili.get_hot_memes(rows, [], [], [])) is expected


def test_operator_preview_normalizes_the_same_noise_as_collection():
    assert not explain_word('音 乐 推 荐', 'meme')['accepted']


@pytest.mark.parametrize('title', ['İBanana', 'ıBanana', '\u0301Banana'])
def test_unicode_word_neighbors_cannot_create_independent_ascii_evidence(title):
    rows = [video('BV1', tags=['Banana']), video('BV2', title)]
    assert bili.get_hot_memes(rows, [], [], []) == []


@pytest.mark.parametrize('title', ['ＨＡＣＨＩＭＩ remix', '哈 基 米'])
def test_title_evidence_preserves_the_observed_spelling(title):
    rows = [video('BV1', tags=['哈基米']), video('BV2', title)]
    result = bili.get_hot_memes(rows, [], [], [])
    observed = 'ＨＡＣＨＩＭＩ' if 'remix' in title else title
    assert observed in result[0]['related_videos'][1]['matched_keywords']


def test_normalized_title_spans_cover_composition_and_casefold_expansion():
    from utils.meme_aliases import normalize_meme_text_with_spans
    key, spans = normalize_meme_text_with_spans('Ａße\u0301')
    assert key == 'assé'
    assert spans == [(0, 1), (1, 2), (1, 2), (2, 4)]
