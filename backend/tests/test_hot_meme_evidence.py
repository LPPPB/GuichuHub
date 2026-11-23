"""A hot meme needs independent video evidence, not repeated hits in one BV."""

import pytest

from collectors.bilibili import get_hot_memes


def video(bvid, title='演示', tags=(), views=500000):
    return dict(bvid=bvid, title=title, tags=list(tags), views=views,
                likes=1000, coins=100, favorites=50, shares=20,
                trend_score=60, author='同一作者')


def test_single_high_view_seed_meme_does_not_qualify():
    assert get_hot_memes([video('BV1', '【哈基米】', ['哈基米'], 10000000)], [], [], []) == []


def test_repeated_bv_and_keyword_hits_are_only_one_video():
    row = video('BV1', '【哈基米】哈基米', ['哈基米', '哈基米', ' 哈基米 '])
    assert get_hot_memes([row, row], [row], [row], [row]) == []


def test_two_distinct_videos_qualify_without_distinct_author_requirement():
    rows = [video('BV1', '【哈基米】', ['哈基米', '哈基米']),
            video('BV2', '【哈基米】', ['哈基米'])]
    result = get_hot_memes(rows, [], [], [])
    assert [m['keyword'] for m in result] == ['哈基米']
    assert result[0]['video_count'] == 2
    assert result[0]['total_views'] == 1000000
    assert result[0]['total_engagement'] == 2340
    assert {v['bvid'] for v in result[0]['related_videos']} == {'BV1', 'BV2'}


def test_seed_mentions_in_plain_titles_count_as_independent_evidence():
    result = get_hot_memes([video('BV1', '哈基米真可爱'), video('BV2', '今天的哈基米')], [], [], [])
    assert [m['keyword'] for m in result] == ['哈基米']
    assert result[0]['video_count'] == 2


@pytest.mark.parametrize('tagged_first', [True, False])
def test_tag_candidate_is_confirmed_by_plain_title_on_another_video(tagged_first):
    tagged = video('BV1', '演示', ['生命线の小曲'])
    mentioned = video('BV2', '再听一遍生命线の小曲')
    rows = [tagged, mentioned] if tagged_first else [mentioned, tagged]
    result = get_hot_memes(rows, [], [], [])
    assert [m['keyword'] for m in result] == ['生命线の小曲']
    assert result[0]['video_count'] == 2


def test_multiple_unrelated_keywords_in_one_video_are_not_multiple_evidence():
    assert get_hot_memes([video('BV1', tags=['面筋哥', '生命线の小曲'])], [], [], []) == []


def test_ascii_keyword_must_be_a_complete_title_word():
    rows = [video('BV1', tags=['Banana']), video('BV2', 'Bananas everywhere')]
    assert get_hot_memes(rows, [], [], []) == []


def test_ascii_title_mentions_are_case_insensitive():
    result = get_hot_memes([video('BV1', tags=['Banana']), video('BV2', 'BANANA remix')], [], [], [])
    assert [m['keyword'] for m in result] == ['Banana']
