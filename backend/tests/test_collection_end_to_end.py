import json
import pytest
from copy import deepcopy
from sqlalchemy import select
from tests.collection_samples import NOW,raw_video,rank_response
from tests.test_official_ranking import Response
from tests.test_collection_generation import derived_io,context


def test_shadow_cutover_failure_and_legacy_rollback_preserve_history(client,postgres_runtime,monkeypatch,derived_io):
    import app as app_module
    from jobs import official_ranking_jobs as jobs,crawl_jobs
    from collectors import bilibili
    from storage.models import video_observations,crawl_runs
    monkeypatch.setenv('COLLECTION_RULES_MODE','shadow')
    monkeypatch.setattr(jobs,'get_headers',lambda:{})
    monkeypatch.setattr(jobs.requests,'get',lambda *a,**k:Response(rank_response([raw_video()])))
    monkeypatch.setattr(app_module.time,'time',lambda:NOW)
    monkeypatch.setattr(bilibili,'make_collection_context',lambda policy,now,**k:context([raw_video(tid=22)],mode=policy.mode))
    assert jobs.run_official_ranking_job()['status']=='success'
    initial=postgres_runtime.state.load_dashboard()['official_kichu_snapshot']
    def full(trigger):
        crawl_jobs.mark_crawling()
        guard=postgres_runtime.collection_lock.try_acquire(trigger=trigger)
        crawl_jobs._crawl_job_locked(trigger,guard=guard)
    full('startup')
    with postgres_runtime.sessions() as session:
        assert session.execute(select(video_observations)).all()==[]
    assert raw_video()['bvid'] in postgres_runtime.business.observation_targets(NOW,200)
    full('scheduled')
    saved=postgres_runtime.state.load_dashboard()
    assert saved['official_kichu_snapshot']==initial
    shadow=client.get('/api/dashboard').json['data']
    assert shadow['kichu_rank_meta']['source']=='legacy_custom'
    monkeypatch.setenv('COLLECTION_RULES_MODE','official')
    public=client.get('/api/dashboard').json['data']
    assert public['kichu_rank_meta']['snapshot_id']==initial['snapshot_id']
    assert public['hot_videos'][0]['metrics_source']=='bilibili_stat'
    with postgres_runtime.sessions() as session:
        before=[dict(row) for row in session.execute(select(video_observations)).mappings()]
        stats=session.execute(select(crawl_runs.c.stats).order_by(crawl_runs.c.started_at.desc())).scalars().all()
    summary=next(s for s in stats if s.get('rules_version'))
    assert {'coverage','rejected','duration_seconds','requests'}<=summary.keys()
    monkeypatch.setattr(jobs.requests,'get',lambda *a,**k:Response({},status=429))
    assert jobs.run_official_ranking_job()['status']=='error'
    failed=client.get('/api/kichu-rank').json
    assert failed['meta']['snapshot_id']==initial['snapshot_id']
    assert failed['meta']['last_attempt']['outcome']=='error'
    monkeypatch.setenv('COLLECTION_RULES_MODE','legacy')
    rollback=client.get('/api/dashboard').json['data']
    assert rollback['kichu_rank_meta']['source']=='legacy_custom'
    assert [v['bvid'] for v in rollback['kichu_rank']]==[v['bvid'] for v in saved['kichu_rank']]
    with postgres_runtime.sessions() as session:
        assert [dict(row) for row in session.execute(select(video_observations)).mappings()]==before


def test_source_probe_has_no_cookie_and_compares_same_response(tmp_path,monkeypatch):
    from scripts import verify_collection_source as probe
    calls=[]
    payload=rank_response([raw_video()])
    def get(url,**kwargs):
        calls.append(kwargs)
        assert not any(k.lower()=='cookie' for k in kwargs['headers'])
        return Response(payload)
    monkeypatch.setattr(probe.requests,'get',get)
    output=tmp_path/'probe.json'
    assert probe.main(['--output',str(output)])==0
    report=json.loads(output.read_text(encoding='utf-8'))
    assert report['source_order']==report['accepted_order']==[raw_video()['bvid']]
    assert report['order_matches'] is True and len(calls)==1
    monkeypatch.setattr(probe.requests,'get',lambda *a,**k:Response({},status=412))
    assert probe.main(['--output',str(output)])!=0


@pytest.mark.parametrize('payload',[{'code':0,'data':123},{'code':-412,'data':None}])
def test_probe_writes_failure_report_for_malformed_or_business_error(tmp_path,monkeypatch,payload):
    from scripts import verify_collection_source as probe
    monkeypatch.setattr(probe.requests,'get',lambda *a,**k:Response(payload))
    path=tmp_path/'error.json'
    assert probe.main(['--output',str(path)])==1
    report=json.loads(path.read_text(encoding='utf-8'))
    assert report['upstream_code']==payload['code']
    assert report['snapshot'] is None
