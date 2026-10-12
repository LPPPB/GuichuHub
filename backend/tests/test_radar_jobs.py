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
