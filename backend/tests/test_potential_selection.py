import importlib
import importlib.util
from dataclasses import replace
import pytest
from collectors.collection_context import RoundContext,SourceResult
from services.collection_contracts import CollectionPolicy,DiscoveryResult,video_from_api
from tests.collection_samples import NOW,raw_video,BVIDS


def run(rows,detail=None,policy=None,outcome='success',online=None,partial=False):
    assert importlib.util.find_spec('services.potential_selection'), 'strict selector missing'
    module=importlib.import_module('services.potential_selection')
    calls=[]
    def get_detail(bvid):
        calls.append(bvid)
        return detail if detail is not None else SourceResult(outcome='error')
    context=RoundContext(policy or CollectionPolicy(),now=NOW,loaders={
        'detail':get_detail,'online':lambda b,c:online or (None,None,None)})
    discovery=DiscoveryResult({'latest':rows},{},[],dict(outcome=outcome,partial=partial,
        failed_sources=[],started_at=NOW,started_at_ns=1,finished_at=NOW,attempt_id='test'))
    result=module.generate_potential(discovery,context=context,now=NOW,history=lambda b,v:v)
    return result,calls


def video(**overrides):
    return video_from_api(raw_video(**overrides),endpoint='popular',observed_at=NOW)


@pytest.mark.parametrize('views',[1500,1000000])
def test_closed_view_boundaries(views):
    stats={k:0 for k in raw_video()['stat']}
    stats.update(view=views,like=views//10)
    result,_=run([video(stat=stats,pubdate=NOW-21*86400)])
    assert len(result.snapshot['items'])==1


def test_detail_over_cap_or_low_quality_or_changed_category_is_rejected():
    row=video(stat={})
    for detail in [raw_video(stat={**raw_video()['stat'],'view':1000001}),
                   raw_video(stat={k:(10000 if k=='view' else 0) for k in raw_video()['stat']}),
                   raw_video(pid_v2=1009)]:
        result,calls=run([row],detail=detail)
        assert result.snapshot['items']==[]
        assert calls==[row['bvid']]


def test_estimated_interactions_cannot_qualify():
    row={**video(),'metrics_source':'estimated','likes':999999,'shares':999999}
    result,_=run([row])
    assert result.snapshot['items']==[]
    assert result.pending[0]['bvid']==row['bvid']


@pytest.mark.parametrize('pub',[0,NOW+1,NOW-21*86400-1])
def test_missing_future_or_expired_publication_not_ranked(pub):
    result,_=run([video(pubdate=pub)])
    assert result.snapshot['items']==[]


def test_short_list_never_relaxes_thresholds():
    rows=[video(bvid=b) for b in BVIDS]
    bad=video(bvid='BV0000000001',stat={k:(10000 if k=='view' else 0) for k in raw_video()['stat']})
    result,_=run(rows+[bad])
    assert len(result.snapshot['items'])==3
    assert result.snapshot['meta']['thresholds']['engagement_min']==10
    assert result.snapshot['meta']['rules_version']=='strict-real-stats-v1'


def test_stale_complete_sample_must_be_refetched():
    row={**video(),'observed_at':NOW-1801}
    result,calls=run([row],detail=raw_video())
    assert calls==[row['bvid']]
    assert result.snapshot['items'][0]['observed_at']==NOW
    failed,_=run([row])
    assert not failed.snapshot['items'] and failed.pending


def test_failure_is_not_successful_empty_snapshot():
    failed,_=run([],outcome='error')
    assert failed.snapshot is None
    success,_=run([])
    assert success.snapshot['items']==[]
    assert success.attempt['outcome']=='success'


def test_real_zero_online_and_missing_online_differ():
    result,_=run([video()],online=(0,'exact','0'))
    assert result.snapshot['items'][0]['online_count_raw']==0
    missing,_=run([video()])
    assert missing.snapshot['items'][0]['online_count_raw'] is None


def test_budget_failure_keeps_pending_and_partial_source_is_marked():
    rows=[video(stat={})]
    result,calls=run(rows,policy=replace(CollectionPolicy(),detail_limit=0),partial=True)
    assert calls==[] and not result.snapshot['items']
    assert result.pending and result.snapshot['meta']['partial'] is True


def test_detail_sample_time_is_receipt_time_not_round_start():
    module=importlib.import_module('services.potential_selection')
    context=RoundContext(CollectionPolicy(),now=NOW,loaders={'detail':lambda _:raw_video(),
        'online':lambda b,c:(None,None,None)})
    context.clock=lambda:NOW+10
    row=video(stat={})
    discovery=DiscoveryResult({'latest':[row]},{},[],{'outcome':'success','started_at':NOW})
    result=module.generate_potential(discovery,context=context,now=NOW,history=lambda b,v:v)
    assert result.snapshot['items'][0]['observed_at']==NOW+10
    assert result.attempt['finished_at']==NOW+10
