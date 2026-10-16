import importlib
import importlib.util
from copy import deepcopy
import pytest
from services.collection_contracts import OfficialFetchResult, PotentialResult, video_from_api
from tests.collection_samples import raw_video, NOW


def module():
    assert importlib.util.find_spec('storage.repositories.collection_state'), 'snapshot publication missing'
    return importlib.import_module('storage.repositories.collection_state')


def result(at=NOW, ns=1, outcome='success'):
    attempt=dict(attempt_id=str(ns),started_at=at,started_at_ns=ns,finished_at=at,outcome=outcome)
    snapshot=dict(snapshot_id=str(ns), source='bilibili_official_ranking_v2',rid=1007,type='all',
                  started_at=at,started_at_ns=ns,attempt_id=str(ns),fetched_at=at,
                  items=[video_from_api(raw_video(),endpoint='ranking_v2',observed_at=at)])
    return OfficialFetchResult(snapshot if outcome=='success' else None,attempt)


@pytest.mark.parametrize('outcome',['error','empty','invalid'])
def test_failure_preserves_success_and_content_time(outcome):
    data={'last_updated':'old','kichu_rank':[{'bvid':'legacy'}]}
    module().merge_official(data,result())
    before=deepcopy(data)
    module().merge_official(data,result(NOW+1,2,outcome))
    assert data['official_kichu_snapshot']==before['official_kichu_snapshot']
    assert data['last_updated']==before['last_updated']
    assert data['official_kichu_attempt']['outcome']==outcome


def test_same_second_late_result_cannot_overwrite_new_success():
    data={}
    module().merge_official(data,result(ns=2))
    module().merge_official(data,result(ns=1))
    assert data['official_kichu_snapshot']['snapshot_id']=='2'
    assert data['official_kichu_attempt']['attempt_id']=='2'


def test_legacy_cannot_become_official_fallback():
    data={'kichu_rank':[{'bvid':'legacy'}]}
    module().merge_official(data,result(outcome='error'))
    assert 'official_kichu_snapshot' not in data


def test_successful_empty_potential_replaces_but_failure_preserves():
    data={'potential_v2_snapshot':{'items':[{'bvid':'old'}],'meta':{'started_at':0}}}
    success=PotentialResult({'items':[],'meta':{'started_at':NOW}},[],{'outcome':'success','started_at':NOW})
    module().merge_generation(data,{'hot_videos':[{'bvid':'legacy'}]},success)
    assert data['potential_v2_snapshot']['items']==[]
    assert data['hot_videos']==[{'bvid':'legacy'}]
    failed=PotentialResult(None,[],{'outcome':'error','started_at':NOW+1})
    module().merge_generation(data,{},failed)
    assert data['potential_v2_snapshot']['items']==[]


def test_ordinary_merge_rejects_official_fields():
    module()
    from storage.cache import persist_data
    with pytest.raises(ValueError,match='snapshot'):
        persist_data({'official_kichu_snapshot':{'items':[]}})


def test_real_publication_registers_without_observation(request):
    mod=module()
    runtime=request.getfixturevalue('postgres_runtime')
    from sqlalchemy import select,func
    from storage.models import videos,video_observations
    r=result()
    row=r.snapshot['items'][0]
    row['first_seen']=100
    runtime.business.record_video({**row,'observe_tier':'cold'},ts=None)
    with runtime.collection_lock.try_acquire(trigger='test') as guard:
        repo=mod.CollectionStateRepository(runtime.state,runtime.business)
        repo.publish_official(r,guard=guard)
    with runtime.sessions() as session:
        stored=session.execute(select(videos).where(videos.c.bvid==row['bvid'])).mappings().one()
        assert stored['first_seen']==100 and stored['observe_tier']=='cold'
        assert session.scalar(select(func.count()).select_from(video_observations))==0
    assert runtime.state.load_dashboard()['official_kichu_snapshot']['snapshot_id']=='1'


def test_failure_state_bumps_version_not_content_time(postgres_runtime):
    runtime=postgres_runtime
    with runtime.collection_lock.try_acquire(trigger='test') as guard:
        runtime.collection_state.publish_official(result(),guard=guard)
        before,version=runtime.state.load_dashboard_snapshot()
        runtime.collection_state.publish_official(result(NOW+1,2,'error'),guard=guard)
        after,new_version=runtime.state.load_dashboard_snapshot()
    assert after['last_updated']==before['last_updated']
    assert after['official_kichu_snapshot']==before['official_kichu_snapshot']
    assert new_version>version


def test_lost_guard_leaves_snapshot_unchanged(postgres_runtime):
    from jobs.collection_lock import CollectionLockLost
    runtime=postgres_runtime
    runtime.state.save_dashboard({'last_updated':'old'},NOW)
    guard=runtime.collection_lock.try_acquire(trigger='test')
    guard.connection.invalidate()
    try:
        with pytest.raises(CollectionLockLost):
            runtime.collection_state.publish_official(result(),guard=guard)
    finally:
        guard.release()
    assert runtime.state.load_dashboard()=={'last_updated':'old'}


def test_metadata_registration_failure_does_not_publish(postgres_runtime,monkeypatch):
    runtime=postgres_runtime
    runtime.state.save_dashboard({'last_updated':'old'},NOW)
    def fail(*args,**kwargs):
        raise RuntimeError('metadata failure')
    monkeypatch.setattr(runtime.business,'register_video_metadata',fail)
    with runtime.collection_lock.try_acquire(trigger='test') as guard:
        with pytest.raises(RuntimeError,match='metadata'):
            runtime.collection_state.publish_official(result(),guard=guard)
    assert runtime.state.load_dashboard()=={'last_updated':'old'}
