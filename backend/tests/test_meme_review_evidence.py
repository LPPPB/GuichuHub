"""Full review evidence must survive the public ranking's truncation."""
from collectors.bilibili import get_hot_memes, get_meme_materials


def video(bvid, tags):
    return dict(bvid=bvid, title='演示作品', tags=tags, tid=22, views=500000,
                likes=100, coins=10, favorites=5, shares=1, trend_score=60,
                author='作者', observed_at=123)


def test_hot_evidence_retains_all_bvs_before_display_limit():
    evidence = []
    rows = [video(f'BV{i}', ['哈基米']) for i in range(8)]
    cards = get_hot_memes(rows, [], [], [], evidence=evidence)
    assert len(cards[0]['related_videos']) == 5
    hits = [e for e in evidence if e['raw_term'] == '哈基米']
    assert {e['bvid'] for e in hits} == {f'BV{i}' for i in range(8)}
    assert all(e['source'] == 'tag' and e['video']['observed_at'] == 123 for e in hits)


def test_hot_evidence_merges_tags_from_duplicate_source_bvs():
    evidence = []
    rows = [video('BV1', []), video('BV1', ['华强买瓜']), video('BV2', ['华强买瓜'])]
    cards = get_hot_memes(rows, [], [], [], evidence=evidence)
    assert cards[0]['video_count'] == 2
    assert len([e for e in evidence if e['raw_term'] == '华强买瓜']) == 2


def test_material_evidence_includes_candidates_lost_to_greedy_assignment():
    evidence = []
    rows = [video('BV1', ['哈基米', '华强买瓜']), video('BV2', ['哈基米', '华强买瓜'])]
    cards = get_meme_materials(rows, [], evidence=evidence)
    assert len(cards) == 1
    assert {e['raw_term'] for e in evidence} >= {'哈基米', '华强买瓜'}
    assert len([e for e in evidence if e['source'] == 'tag']) == 4


def test_material_evidence_keeps_single_video_candidates_for_manual_addition():
    evidence = []
    assert get_meme_materials([video('BV1', ['华强买瓜'])], [], evidence=evidence) == []
    assert evidence[0]['raw_term'] == '华强买瓜'


def test_recalculation_preserves_tag_first_greedy_selection_without_alias_edits():
    from services.meme_review import rank_evidence
    evidence = []
    rows = [video('BV1', ['哈基米','华强买瓜']),video('BV2',['哈基米','华强买瓜']),
            video('BV3',['哈基米']),video('BV4',['面筋哥']),video('BV5',['面筋哥'])]
    cards = get_meme_materials(rows, [], evidence=evidence)
    rebuilt = rank_evidence('meme_materials', evidence, [], [])
    assert [(r['name'],r['total_views']) for r in rebuilt] == [(r['name'],r['total_views']) for r in cards]

