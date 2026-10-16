"""A PostgreSQL session lock shared by API refreshes and Worker collection."""
from contextlib import contextmanager
from sqlalchemy import text

LOCK_KEY = 0x4748434F4C4C0001
_collection_lock = None


class CollectionLockLost(RuntimeError):
    pass


class CollectionGuard:
    def __init__(self, connection, trigger):
        self.connection = connection
        self.trigger = trigger
        self._identity = connection.connection.driver_connection
        self._released = False
        self._lost = False

    def _check_connection(self):
        connection = self.connection
        if self._released or self._lost or connection.closed or connection.invalidated:
            self._lost = True
            raise CollectionLockLost('Collection session is no longer valid')
        if connection.connection.driver_connection is not self._identity:
            self._lost = True
            raise CollectionLockLost('Collection session was replaced')

    def assert_held(self):
        self._check_connection()
        in_transaction = self.connection.in_transaction()
        try:
            self.connection.execute(text('SELECT 1'))
            if not in_transaction:
                self.connection.rollback()
        except Exception as error:
            self._lost = True
            self.connection.invalidate()
            raise CollectionLockLost('Collection session disconnected') from error

    @contextmanager
    def publication_connection(self):
        self._check_connection()
        with self.connection.begin():
            self.assert_held()
            yield self.connection

    def release(self):
        if self._released:
            return
        try:
            if not self._lost and not self.connection.closed and not self.connection.invalidated:
                if self.connection.in_transaction():
                    self.connection.rollback()
                self.connection.execute(text('SELECT pg_advisory_unlock(:key)'), {'key':LOCK_KEY})
                self.connection.commit()
            elif not self.connection.closed:
                self.connection.invalidate()
        except Exception:
            self.connection.invalidate()
        finally:
            self._released = True
            self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *exception):
        self.release()


class CollectionLock:
    def __init__(self, engine):
        self.engine = engine

    def try_acquire(self, *, trigger):
        connection = self.engine.connect()
        try:
            acquired = connection.execute(text('SELECT pg_try_advisory_lock(:key)'), {'key':LOCK_KEY}).scalar_one()
            connection.commit()
            if not acquired:
                connection.close()
                return None
            return CollectionGuard(connection, trigger)
        except Exception:
            connection.invalidate()
            connection.close()
            raise


def configure_collection_lock(lock):
    global _collection_lock
    _collection_lock = lock


def get_collection_lock():
    if _collection_lock is None:
        raise RuntimeError('PostgreSQL collection lock is not configured')
    return _collection_lock
