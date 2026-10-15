import importlib
import importlib.util
import pytest
from contextlib import contextmanager
from storage.postgres import create_engine


@contextmanager
def lock_pair(request):
    assert importlib.util.find_spec('jobs.collection_lock'), 'shared collection lock missing'
    module=importlib.import_module('jobs.collection_lock')
    url=request.getfixturevalue('postgres_server_url')
    engines=[create_engine(url),create_engine(url)]
    try:
        yield module, [module.CollectionLock(e) for e in engines]
    finally:
        for engine in engines:
            engine.dispose()


def test_two_sessions_exclude_each_other(request):
    with lock_pair(request) as (module,(first,second)):
        guard=first.try_acquire(trigger='official')
        assert guard is not None
        try:
            assert not guard.connection.in_transaction()
            assert second.try_acquire(trigger='manual') is None
        finally:
            guard.release()
        with second.try_acquire(trigger='manual') as next_guard:
            assert next_guard is not None


def test_disconnected_guard_cannot_publish_on_reconnected_pool(request):
    with lock_pair(request) as (module,(first,second)):
        guard=first.try_acquire(trigger='official')
        guard.connection.invalidate()
        with pytest.raises(module.CollectionLockLost):
            with guard.publication_connection():
                pytest.fail('lost session was allowed to publish')
        guard.release()
        guard.release()
        with second.try_acquire(trigger='next') as replacement:
            assert replacement is not None


def test_exception_returns_unlocked_connection(request):
    with lock_pair(request) as (module,(first,second)):
        with pytest.raises(ValueError):
            with first.try_acquire(trigger='official') as guard:
                with guard.publication_connection():
                    raise ValueError('rollback')
        with first.try_acquire(trigger='reuse-pool') as guard:
            assert guard is not None


def test_publication_uses_same_session(request):
    with lock_pair(request) as (_,(first,_)):
        with first.try_acquire(trigger='official') as guard:
            with guard.publication_connection() as connection:
                assert connection is guard.connection
                assert connection.in_transaction()
