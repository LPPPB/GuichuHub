from concurrent.futures import ThreadPoolExecutor
from jobs.radar_jobs import run_radar_baseline_job
from storage.repositories.radar import RadarRepository
from utils.radar_v2 import build_baseline
from tests.test_radar_v2 import context, NOW


def test_immutable_publication_and_revision(postgres_runtime):
    repo = RadarRepository(postgres_runtime.sessions)
    baseline = build_baseline([context(i) for i in range(240)], NOW, NOW+86400)
    assert repo.publish_baseline(baseline, NOW)
    before = repo.revision()
    baseline['sample_count'] = 9999
    assert not repo.publish_baseline(baseline, NOW)
    assert repo.load_active_baseline(NOW)['sample_count'] == 240
    repo.touch_observations(NOW)
    assert repo.revision()[0] == before[0]+1
    assert repo.load_active_baseline(NOW+86400) is None


def test_concurrent_publication_has_one_winner(postgres_runtime):
    repo = RadarRepository(postgres_runtime.sessions)
    b = build_baseline([context(i) for i in range(240)], NOW, NOW+86400)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: repo.publish_baseline(b, NOW), range(2)))
    assert sorted(results) == [False, True]


def test_worker_bootstrap_is_frozen_and_missing_samples_not_published(postgres_runtime, monkeypatch):
    repo = RadarRepository(postgres_runtime.sessions)
    monkeypatch.setattr('jobs.radar_jobs.get_radar_repository', lambda: repo)
    samples = [context(i) for i in range(240)]
    monkeypatch.setattr(repo, 'reference_contexts', lambda cutoff_ts: samples)
    result = run_radar_baseline_job(NOW)
    assert result['status'] == 'published'
    assert repo.load_active_baseline(NOW)['cutoff_ts'] == NOW
    monkeypatch.setattr(repo, 'reference_contexts', lambda _: (_ for _ in ()).throw(AssertionError('rebuilt frozen baseline')))
    assert run_radar_baseline_job(NOW+100)['status'] == 'unchanged'


def test_worker_refuses_a_tiny_reference_pool(postgres_runtime, monkeypatch):
    repo = RadarRepository(postgres_runtime.sessions)
    monkeypatch.setattr('jobs.radar_jobs.get_radar_repository', lambda: repo)
    monkeypatch.setattr(repo, 'reference_contexts', lambda _: [context()])
    assert run_radar_baseline_job(NOW)['status'] == 'insufficient'
    assert repo.load_active_baseline(NOW) is None


def test_bootstrap_waits_for_real_growth_window(postgres_runtime, monkeypatch):
    repo = RadarRepository(postgres_runtime.sessions)
    monkeypatch.setattr('jobs.radar_jobs.get_radar_repository', lambda: repo)
    samples = [context(i) for i in range(240)]
    for sample in samples:
        sample['history'] = [sample['latest']]
    monkeypatch.setattr(repo, 'reference_contexts', lambda _: samples)
    result = run_radar_baseline_job(NOW)
    assert result['status'] == 'warming_up'
    assert repo.load_active_baseline(NOW) is None
    monkeypatch.setattr(repo, 'reference_contexts', lambda _: [context(i) for i in range(240)])
    assert run_radar_baseline_job(NOW)['status'] == 'published'


def test_weekly_rollover_replaces_bootstrap_without_mutating_it(postgres_runtime, monkeypatch):
    repo = RadarRepository(postgres_runtime.sessions)
    monkeypatch.setattr('jobs.radar_jobs.get_radar_repository', lambda: repo)
    monkeypatch.setattr(repo, 'reference_contexts', lambda _: [context(i) for i in range(240)])
    assert run_radar_baseline_job(NOW)['status'] == 'published'
    initial = repo.load_active_baseline(NOW)
    boundary = initial['valid_until']
    assert run_radar_baseline_job(boundary)['status'] == 'published'
    weekly = repo.load_active_baseline(boundary)
    assert weekly['cutoff_ts'] == boundary
    assert weekly['valid_until'] == boundary+7*86400
    assert weekly['version'] != initial['version']
    assert repo.load_active_baseline(NOW) == initial


def test_partial_full_crawl_commit_advances_revision_when_later_write_fails(postgres_runtime, monkeypatch):
    _assert_failed_crawl_still_revises(postgres_runtime, monkeypatch, failure='record')


def test_committed_crawl_revises_even_when_dashboard_persistence_fails(postgres_runtime, monkeypatch):
    _assert_failed_crawl_still_revises(postgres_runtime, monkeypatch, failure='dashboard')


def _assert_failed_crawl_still_revises(runtime, monkeypatch, failure):
    import threading
    import pytest
    from jobs import crawl_jobs
    repo = RadarRepository(runtime.sessions)
    c = context()
    row = dict(**c['latest'], bvid=c['bvid'], first_seen=NOW-86400, pub_date=c['pub_date'], tid=216)
    rows = [row, {**row, 'bvid': 'BVsecond'}] if failure == 'record' else [row]
    monkeypatch.setattr(crawl_jobs, 'run_all_crawlers', lambda: {'_all_videos': rows, 'hot_videos': [], 'material_candidates': []})
    monkeypatch.setattr(crawl_jobs, '_crawl_lock', threading.Lock())
    monkeypatch.setattr(crawl_jobs, '_crawl_status', {**crawl_jobs._crawl_status, 'started_at': NOW})
    original = crawl_jobs.tsdb.record_video
    def record(v, ts, source):
        if v['bvid'] == 'BVsecond':
            raise RuntimeError('test write failure')
        return original(v, ts, source)
    monkeypatch.setattr(crawl_jobs.tsdb, 'record_video', record)
    def fail_dashboard(_):
        raise RuntimeError('test dashboard failure')
    if failure == 'dashboard':
        monkeypatch.setattr(crawl_jobs, 'persist_data', fail_dashboard)
    crawl_jobs._crawl_lock.acquire()
    with pytest.raises(RuntimeError, match='test .* failure'):
        crawl_jobs._crawl_job_locked('scheduled')
    assert repo.video_contexts(['BV0'], NOW)['BV0']['latest']['views'] == 10000
    assert repo.revision()[0] == 1


def test_observation_adds_reference_quota_without_extra_online_requests(postgres_runtime, monkeypatch):
    import threading
    from jobs import crawl_jobs
    from collectors import bilibili
    repo=RadarRepository(postgres_runtime.sessions)
    for bvid in ('BVrank','BVmusic','BVref'):
        row=context()['latest'].copy(); row.update(bvid=bvid,first_seen=NOW-86400,pub_date=NOW-86400,tid=216)
        postgres_runtime.business.record_video(row,ts=NOW-3600)
    monkeypatch.setattr(crawl_jobs,'_crawl_lock',threading.Lock())
    monkeypatch.setattr(crawl_jobs.tsdb,'get_observation_targets',lambda **_: ['BVmusic','BVrank'])
    monkeypatch.setattr(crawl_jobs,'_get_rank_bvids',lambda: ['BVrank'])
    monkeypatch.setattr('storage.repositories.radar.get_radar_repository',lambda: repo)
    monkeypatch.setattr(repo,'reference_observation_targets',lambda now,limit=240: ['BVref','BVrank'],raising=False)
    details=[]; online=[]
    def detail(bvid):
        details.append(bvid)
        return {'cid':1,'stat':dict(view=10000,like=200,coin=20,favorite=50,share=30,reply=5,danmaku=10)}
    monkeypatch.setattr(bilibili,'fetch_video_detail',detail)
    monkeypatch.setattr(bilibili,'fetch_online_count',lambda bvid,cid: (online.append(bvid) or (1,'exact','1')))
    monkeypatch.setattr(bilibili,'_online_breaker_open',lambda: False)
    monkeypatch.setattr(bilibili,'_online_pacing',lambda: None)
    monkeypatch.setattr(crawl_jobs,'_radar_observations_changed',lambda: None)
    crawl_jobs.run_observe_job()
    assert details==['BVrank','BVmusic','BVref']
    assert online==['BVrank','BVmusic']
