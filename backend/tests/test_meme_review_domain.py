"""Review overlays follow current evidence without extending their lifetime."""
import pytest
from services import meme_review


def hit(word, bv, views=500000):
    return {'raw_term': word, 'bvid': bv, 'source': 'tag', 'video': {
        'bvid': bv, 'title': word, 'views': views, 'likes': 10, 'coins': 1,
        'favorites': 1, 'shares': 1, 'trend_score': 60}}


def test_merge_uses_bv_union_and_keeps_original_evidence():
    records = [{'id': 'meme_test', 'name': '华强买瓜', 'aliases': ['买瓜']}]
    evidence = [hit('华强买瓜', 'BV1'), hit('买瓜', 'BV1'), hit('买瓜', 'BV2')]
    result = meme_review.rank_evidence('hot_memes', evidence, records, [])
    assert result[0]['video_count'] == 2
    assert result[0]['total_views'] == 1000000
    assert result[0]['aliases'] == ['买瓜']
    assert evidence[1]['raw_term'] == '买瓜'


def test_adjustment_expires_at_boundary_and_does_not_mutate_input():
    rows = [{'meme_id': 'a', 'keyword': '甲'}, {'meme_id': 'b', 'keyword': '乙'}]
    changes = [{'board': 'hot_memes', 'meme_id': 'a', 'action': 'hide', 'expires_at': 200}]
    assert len(meme_review.apply_adjustments('hot_memes', rows, [], changes, [], 199)) == 1
    assert len(meme_review.apply_adjustments('hot_memes', rows, [], changes, [], 200)) == 2
    assert len(rows) == 2


def test_manual_add_without_evidence_has_null_metrics_and_blacklist_wins():
    records = [{'id': 'meme_test', 'name': '华强买瓜', 'aliases': []}]
    changes = [{'board': 'hot_memes', 'meme_id': 'meme_test', 'action': 'add', 'position': 1, 'expires_at': 200}]
    result = meme_review.apply_adjustments('hot_memes', [], records, changes, [], 100)
    assert result[0]['heat'] is None and result[0]['total_views'] is None
    assert result[0]['manual'] is True
    assert meme_review.apply_adjustments('hot_memes', [], records, changes, ['华强买瓜'], 100) == []


def test_conflicting_positions_are_rejected():
    rows = [{'meme_id': 'a'}, {'meme_id': 'b'}]
    changes = [{'board': 'hot_memes', 'meme_id': id, 'action': 'position', 'position': 1, 'expires_at': 200} for id in ['a', 'b']]
    with pytest.raises(ValueError, match='position'):
        meme_review.apply_adjustments('hot_memes', rows, [], changes, [], 100)


def test_dictionary_alias_conflicts_are_rejected():
    with pytest.raises(ValueError, match='alias'):
        meme_review.validate_dictionary([{'id': 'a', 'name': 'ABC', 'aliases': []},
                                         {'id': 'b', 'name': 'abc', 'aliases': []}])


def test_manual_add_is_visible_even_when_automatic_board_is_full():
    rows = [dict(meme_id=str(i), keyword=str(i)) for i in range(30)]
    records = [dict(id='manual', name='人工梗', aliases=[])]
    adjustments = [dict(board='hot_memes', meme_id='manual', action='add', expires_at=200)]
    result = meme_review.apply_adjustments('hot_memes', rows, records, adjustments, [], 100)
    assert len(result) == 30
    assert any(row['meme_id'] == 'manual' for row in result)


@pytest.mark.parametrize('ids', [('a','b'),('b','a')])
def test_inactive_pin_cannot_reserve_a_conflicting_future_position(ids):
    changes = [dict(board='hot_memes', meme_id=id, action='position', position=1, expires_at=200) for id in ids]
    with pytest.raises(ValueError, match='position'):
        meme_review.apply_adjustments('hot_memes', [{'meme_id':'a'}], [], changes, [], 100)
