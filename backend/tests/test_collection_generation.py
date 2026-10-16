from dataclasses import replace
import pytest
from collectors.collection_context import RoundContext
from services.collection_contracts import CollectionPolicy
from tests.collection_samples import raw_video,NOW


def context(rows=(),mode='shadow'):
    return RoundContext(replace(CollectionPolicy(),mode=mode),now=NOW,loaders={
        'popular_page':lambda page:list(rows) if page==1 else [],
        'search_page':lambda *args:[],'all_ranking':lambda:[],'newest':lambda:[],
        'seed_words':lambda:[],'tags':lambda _:[],'detail':lambda _:None,
        'online':lambda b,c:(None,None,None),
    })


@pytest.fixture
def derived_io(monkeypatch):
    import collectors.bilibili as bili
    samples={}
    monkeypatch.setattr(bili,'_smooth_online',lambda b,v:v)
    monkeypatch.setattr(bili,'get_hot_memes',lambda *a:[])
    monkeypatch.setattr(bili,'get_hot_songs',lambda *a:[])
    monkeypatch.setattr(bili,'get_meme_materials',lambda *a,**k:[])
    def capture(name,rows):
        samples[name]=[v['bvid'] for v in rows]
        return []
    monkeypatch.setattr(bili,'get_real_danmaku_words',lambda rows:capture('danmaku',rows))
    monkeypatch.setattr(bili,'get_golden_comments',lambda rows:capture('comments',rows))
    return samples


def test_shadow_keeps_legacy_results_separate_from_strict(derived_io):
    import collectors.bilibili as bili
    rows=[raw_video(f'BV{i:010d}',tid=22,stat={**raw_video()['stat'],'view':3000000}) for i in range(70)]
    rows[-1]['stat']['view']=2000
    result=bili.run_all_crawlers(context=context(rows),mode='shadow')
    assert result['hot_videos']==[]
    assert [v['bvid'] for v in result['potential_v2_snapshot']['items']]==[rows[-1]['bvid']]
    assert 'potential_score' not in next(v for v in result['_all_videos'] if v['bvid']==rows[-1]['bvid'])


def test_official_history_uses_strict_score_without_expanding_derived_samples(derived_io):
    import collectors.bilibili as bili
    from services.collection_contracts import video_from_api
    rows=[raw_video(f'BV{i:010d}',tid=22) for i in range(100)]
    snapshot={'items':[video_from_api(v,endpoint='ranking_v2',observed_at=NOW) for v in rows]}
    result=bili.run_all_crawlers(context=context(rows[:3],mode='official'),official_snapshot=snapshot,mode='official')
    assert len(result['kichu_rank'])==3
    assert len(result['potential_v2_snapshot']['items'])==30
    assert len(derived_io['comments'])<=10
    assert len(derived_io['danmaku'])==len(set(derived_io['danmaku']))<=70
    assert len(result['_all_videos'])==100
    assert all(v.get('potential_score') is not None for v in result['_all_videos'])
    assert result['_collection_summary']['requests']['logical'].get('tags',0)<=64


def test_hot_meme_duplicate_cannot_cross_threshold(monkeypatch):
    import collectors.bilibili as bili
    monkeypatch.setattr(bili,'load_meme_stopwords',lambda:{})
    monkeypatch.setattr(bili,'load_meme_seed_words',lambda:[])
    monkeypatch.setattr(bili,'is_useless_tag',lambda _:False)
    row=dict(bvid='BVtest',title='测试热梗',tags=['测试热梗'],views=200000,
             likes=1000,coins=10,favorites=10,shares=10,trend_score=20,author='测试')
    assert bili.get_hot_memes([row],[],[],[row])==[]


def test_round_online_respects_existing_circuit_breaker(monkeypatch):
    import collectors.bilibili as bili
    monkeypatch.setattr(bili,'_online_breaker_open',lambda:True)
    def forbidden(*args):
        pytest.fail('open circuit still made an online request')
    monkeypatch.setattr(bili,'fetch_online_count',forbidden)
    ctx=bili.make_collection_context(CollectionPolicy(),NOW)
    assert ctx.call('online','BVtest',123,kind='online').outcome=='skipped'
