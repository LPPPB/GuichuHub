import importlib
import importlib.util
from dataclasses import replace
import requests
from services.collection_contracts import CollectionPolicy, video_from_api
from tests.collection_samples import raw_video, NOW


def modules():
    assert importlib.util.find_spec('collectors.collection_context'), 'round context missing'
    assert importlib.util.find_spec('collectors.discovery'), 'independent discovery missing'
    return importlib.import_module('collectors.collection_context'),importlib.import_module('collectors.discovery')


def setup(rows=(),search=(),policy=None,seeds=()):
    context_module,discovery=modules()
    calls=[]
    def popular(page):
        calls.append(('popular',page))
        return list(rows) if page==1 else []
    def search_page(kw,tid,order,page):
        calls.append(('search',kw,tid,order,page))
        return list(search) if tid==22 and page==1 else []
    context=context_module.RoundContext(policy or CollectionPolicy(),loaders={
        'popular_page':popular,'search_page':search_page,'all_ranking':lambda:[],
        'region_ranking':lambda _:[],'newest':lambda:[],'seed_words':lambda:list(seeds),
    },now=NOW)
    return context,discovery,calls


def test_candidate_beyond_legacy_top30_survives():
    rows=[raw_video(f'BV{i:010d}',tid=22,stat={**raw_video()['stat'],'view':3000000-i}) for i in range(40)]
    rows[-1]['stat']['view']=2000
    context,discovery,calls=setup(rows)
    result=discovery.discover_candidates(context=context,official_snapshot=None,pending=[],now=NOW)
    candidates=[v for lane in result.lanes.values() for v in lane]
    assert rows[-1]['bvid'] in {v['bvid'] for v in candidates}
    assert len({v['bvid'] for v in candidates})==40
    assert len([c for c in calls if c[0]=='popular'])==15
    assert context.summary()['logical']['discovery']<=60


def test_sources_merge_without_duplicate_candidates():
    row=raw_video(tid=22)
    context,discovery,calls=setup([row],[row])
    official={'items':[video_from_api(row,endpoint='ranking_v2',observed_at=NOW)]}
    result=discovery.discover_candidates(context=context,official_snapshot=official,pending=[],now=NOW)
    candidates=[v for lane in result.lanes.values() for v in lane]
    assert len(candidates)==1
    assert {'official','popular','latest','search'}<=set(candidates[0]['sources'])
    assert {c[3] for c in calls if c[0]=='search'}>={'pubdate','totalrank'}


def test_partial_stats_from_two_sources_do_not_form_real_sample():
    first=raw_video(tid=22,stat={'view':10000,'like':500})
    second=raw_video(tid=22,stat={'coin':50,'favorite':50,'share':50,'reply':10,'danmaku':10})
    context,discovery,_=setup([first],[second])
    result=discovery.discover_candidates(context=context,official_snapshot=None,pending=[],now=NOW)
    rows=[v for lane in result.lanes.values() for v in lane]
    assert rows[0]['metrics_source']=='legacy_unknown'
    assert rows[0]['likes'] is None


def test_failed_request_is_not_repeated_in_same_round():
    context,_,_=setup()
    calls=[]
    def fail():
        calls.append(1)
        context.record_http_attempt('detail')
        raise requests.Timeout()
    first=context.fetch_once('detail',('detail','BVtest'),fail)
    second=context.fetch_once('detail',('detail','BVtest'),fail)
    assert first.outcome=='error' and second is first
    assert calls==[1]
    assert context.summary()['http_attempts']['detail']==1


def test_seed_budget_and_pending_boundaries():
    context,discovery,calls=setup(seeds=[f'种子{i}' for i in range(15)])
    pending=[video_from_api(raw_video(f'BV{i:010d}',stat={},pubdate=NOW-22*86400),
                            endpoint='view',observed_at=NOW) for i in range(600)]
    result=discovery.discover_candidates(context=context,official_snapshot=None,pending=pending,now=NOW)
    assert not result.pending
    assert len([c for c in calls if c[0]=='search' and c[1].startswith('种子')])<=8


def test_lower_budget_cannot_be_exceeded():
    context,discovery,_=setup(policy=replace(CollectionPolicy(),discovery_limit=3))
    discovery.discover_candidates(context=context,official_snapshot=None,pending=[],now=NOW)
    assert context.summary()['logical']['discovery']==3
    assert context.summary()['skipped']['discovery']>0


def test_production_source_adapter_preserves_empty_vs_failure(monkeypatch):
    import collectors.bilibili as bilibili
    assert hasattr(bilibili,'make_collection_context'), 'production context adapter missing'
    monkeypatch.setattr(bilibili,'safe_get',lambda *a,**k:{'code':0,'data':{'list':[]}})
    context=bilibili.make_collection_context(CollectionPolicy(),NOW)
    assert context.call('popular_page',1).outcome=='success'
    monkeypatch.setattr(bilibili,'safe_get',lambda *a,**k:None)
    assert context.call('popular_page',2).outcome=='error'


def test_newest_placeholder_needs_real_detail():
    row=raw_video(stat={k:0 for k in raw_video()['stat']})
    normalized=video_from_api(row,endpoint='newest',observed_at=NOW)
    assert normalized['metrics_source']=='legacy_unknown'
    assert normalized['views'] is None


def test_limits_cannot_exceed_hard_budget():
    import pytest
    for override in (dict(candidate_limit=401),dict(detail_limit=161),dict(tag_limit=65),dict(discovery_limit=61)):
        with pytest.raises(ValueError):
            CollectionPolicy(**override)


def test_production_adapter_keeps_request_pacing(monkeypatch):
    import collectors.bilibili as bilibili
    pauses=[]
    monkeypatch.setattr(bilibili,'safe_get',lambda *a,**k:{'code':0,'data':{'list':[]}})
    monkeypatch.setattr(bilibili,'_online_pacing',lambda:pauses.append(1))
    context=bilibili.make_collection_context(CollectionPolicy(),NOW)
    context.call('popular_page',1)
    context.call('popular_page',1)
    context.call('popular_page',2)
    assert pauses==[1,1]
