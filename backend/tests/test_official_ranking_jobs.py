from copy import deepcopy
import pytest
from tests.collection_samples import NOW, raw_video


def test_visible_targets_are_prioritized_inside_total_budget():
    from jobs.official_ranking_jobs import select_observation_targets
    visible=[f'BV{i}' for i in range(50)]
    targets=select_observation_targets(visible,visible+[f'T{i}' for i in range(250)],limit=200)
    assert targets[:50]==visible
    assert len(targets)==len(set(targets))==200


def test_official_job_publishes_metadata_without_observations(postgres_runtime,monkeypatch):
    from jobs import official_ranking_jobs as jobs
    from collectors.official_ranking import fetch_official_ranking
    from tests.test_official_ranking import Response
    from tests.collection_samples import rank_response
    result=fetch_official_ranking(request_get=lambda *a,**k:Response(rank_response([raw_video()])),headers={},now=lambda:NOW,pause=lambda _:None,attempt_id='test')
    monkeypatch.setattr(jobs,'fetch_official_ranking',lambda **_:result)
    monkeypatch.setenv('COLLECTION_RULES_MODE','shadow')
    monkeypatch.setattr(jobs,'get_headers',lambda:{})
    assert jobs.run_official_ranking_job()['status']=='success'
    data=postgres_runtime.state.load_dashboard()
    assert data['official_kichu_snapshot']['items'][0]['bvid']==raw_video()['bvid']
    assert observation_count(postgres_runtime)==0


def test_startup_fetches_only_missing_or_expired_snapshot(monkeypatch):
    from jobs import official_ranking_jobs as jobs
    monkeypatch.setenv('COLLECTION_RULES_MODE','shadow')
    calls=[]
    monkeypatch.setattr(jobs,'run_official_ranking_job',lambda trigger: calls.append(trigger) or {'status':'success'})
    for age,expected in [(1799,False),(1800,False),(1801,True)]:
        monkeypatch.setattr(jobs,'get_data',lambda:{'official_kichu_snapshot':{'fetched_at':NOW-age}})
        calls.clear(); jobs.refresh_official_if_due(now=NOW)
        assert bool(calls)==expected
    monkeypatch.setattr(jobs,'get_data',lambda:{})
    calls.clear(); jobs.refresh_official_if_due(now=NOW)
    assert calls==['startup']
    monkeypatch.setenv('COLLECTION_RULES_MODE','legacy')
    calls.clear(); jobs.refresh_official_if_due(now=NOW)
    assert not calls


def test_busy_official_job_schedules_only_one_delayed_retry(postgres_runtime,monkeypatch):
    from jobs import official_ranking_jobs as jobs
    monkeypatch.setenv('COLLECTION_RULES_MODE','official')
    added=[]
    class Scheduler:
        from zoneinfo import ZoneInfo
        timezone=ZoneInfo('Asia/Shanghai')
        def add_job(self,*args,**kwargs): added.append((args,kwargs))
    jobs.configure_scheduler(Scheduler())
    try:
        with postgres_runtime.collection_lock.try_acquire(trigger='full'):
            assert jobs.run_official_ranking_job()['status']=='skipped_busy'
            assert jobs.run_official_ranking_job('retry')['status']=='skipped_busy'
        assert len(added)==1
        assert added[0][1]['id']=='official_kichu_rank_retry'
        assert added[0][1]['replace_existing'] is True
    finally:
        jobs.configure_scheduler(None)


def test_startup_registers_unknown_stats_without_history(postgres_runtime,monkeypatch):
    from jobs import crawl_jobs
    from services.collection_contracts import PotentialResult
    row={'bvid':'BVstartup','title':'startup','first_seen':NOW,'views':1234,'metrics_source':'estimated'}
    result=PotentialResult(None,[],{'started_at':NOW,'finished_at':NOW,'outcome':'error'})
    monkeypatch.setattr(crawl_jobs,'_collect_round',lambda:{'_all_videos':[row],'_potential_result':result})
    guard=postgres_runtime.collection_lock.try_acquire(trigger='startup')
    crawl_jobs._crawl_job_locked('startup',guard=guard)
    assert 'BVstartup' in postgres_runtime.business.observation_targets(NOW,200)
    assert observation_count(postgres_runtime)==0
    assert guard._released


def test_live_handoff_keeps_empty_snapshot_but_removes_private_data(postgres_runtime,monkeypatch):
    from jobs import crawl_jobs
    from storage.cache import get_live_cache,invalidate_live_cache
    snapshot={'items':[],'meta':{'fetched_at':NOW}}
    monkeypatch.setattr(crawl_jobs,'_collect_round',lambda:{'potential_v2_snapshot':snapshot,'_potential_result':object(),'_all_videos':[]})
    guard=postgres_runtime.collection_lock.try_acquire(trigger='manual')
    try:
        crawl_jobs._crawl_job_live(guard=guard)
        data=get_live_cache()['data']
        assert data=={'potential_v2_snapshot':snapshot}
        assert guard._released
    finally: invalidate_live_cache()


def observation_count(runtime):
    from sqlalchemy import select,func
    from storage.models import video_observations
    with runtime.sessions() as session:
        return session.scalar(select(func.count()).select_from(video_observations))


def test_full_lock_timeout_returns_no_guard(monkeypatch):
    from jobs import crawl_jobs
    monkeypatch.setattr(crawl_jobs,'try_acquire_lock',lambda *_:None)
    monkeypatch.setattr(crawl_jobs,'_CRAWL_LOCK_WAIT_TIMEOUT',0)
    assert crawl_jobs._acquire_crawl_lock_with_wait() is None


def test_lost_guard_stops_live_publication(postgres_runtime,monkeypatch):
    from jobs import crawl_jobs
    from jobs.collection_lock import CollectionLockLost
    from storage.cache import get_live_cache
    guard=postgres_runtime.collection_lock.try_acquire(trigger='manual')
    def collect():
        guard.connection.invalidate()
        return {'hot_videos':[{'bvid':'never'}]}
    monkeypatch.setattr(crawl_jobs,'_collect_round',collect)
    with pytest.raises(CollectionLockLost):
        crawl_jobs._crawl_job_live(guard=guard)
    assert get_live_cache() is None


def test_metadata_failure_leaves_previous_official_snapshot(postgres_runtime,monkeypatch):
    from jobs import official_ranking_jobs as jobs
    from tests.test_collection_state import result
    monkeypatch.setenv('COLLECTION_RULES_MODE','official')
    initial=result()
    with postgres_runtime.collection_lock.try_acquire(trigger='setup') as guard:
        postgres_runtime.collection_state.publish_official(initial,guard=guard)
    monkeypatch.setattr(jobs,'fetch_official_ranking',lambda **_:result(NOW+1,2))
    monkeypatch.setattr(jobs,'get_headers',lambda:{})
    def fail(*a,**k): raise RuntimeError('test metadata failure')
    monkeypatch.setattr(postgres_runtime.business,'register_video_metadata',fail)
    assert jobs.run_official_ranking_job()['status']=='error'
    data=postgres_runtime.state.load_dashboard()
    assert data['official_kichu_snapshot']==initial.snapshot
    assert data['official_kichu_attempt']['outcome']=='error'
