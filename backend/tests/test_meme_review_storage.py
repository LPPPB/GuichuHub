from sqlalchemy import inspect
from storage.models import Base


def test_review_migration_has_owned_tables_and_no_shared_video_cascade(postgres_runtime):
    engine = postgres_runtime.sessions.kw['bind']
    inspector = inspect(engine)
    names = {'meme_review_state', 'meme_review_runs', 'meme_review_drafts',
             'meme_review_publications', 'meme_review_operations'}
    assert names <= set(inspector.get_table_names(schema='app'))
    for name in names:
        assert all(fk['referred_table'].startswith('meme_review_')
                   for fk in inspector.get_foreign_keys(name, schema='app'))


def test_review_runs_preserve_empty_complete_vs_failed(postgres_runtime):
    from storage.repositories.meme_review import MemeReviewRepository
    repo = MemeReviewRepository(postgres_runtime.sessions)
    repo.record_run('one', {'hot_memes': {'complete': True, 'cards': [], 'evidence': []},
                            'meme_materials': {'complete': False, 'cards': [], 'evidence': []}}, now=100)
    run = repo.get_run('one')
    assert run['boards']['hot_memes']['complete'] is True
    assert run['boards']['meme_materials']['complete'] is False
    repo.record_run('one', run['boards'], now=200)
    assert repo.get_run('one')['finished_at'] == 100
