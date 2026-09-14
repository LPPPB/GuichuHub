import json
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta

from runtime_paths import RuntimePaths

# 中国时区：显式 UTC+8，不依赖系统本地时区
CN_TZ = timezone(timedelta(hours=8))

RUNTIME_PATHS = RuntimePaths.from_environment(os.environ)
DATA_DIR = str(RUNTIME_PATHS.current_state.parent)
STATE_FILENAME = RUNTIME_PATHS.current_state.name


def get_db_path():
    return os.path.join(DATA_DIR, STATE_FILENAME)


def _initial_data():
    return {
        'hot_memes': [],
        'hot_songs': [],
        'hot_videos': [],
        'danmaku_words': [],
        'comments_gold': [],
        'favorites': [],
        'last_updated': None,
    }


def _lock_path():
    return f'{get_db_path()}.lock'


@contextmanager
def _state_lock():
    """Serialize state mutations across Gunicorn processes and the Worker."""
    lock_path = _lock_path()
    os.makedirs(os.path.dirname(lock_path) or '.', exist_ok=True)
    with open(lock_path, 'a+b') as lock_file:
        if os.name == 'nt':
            import msvcrt

            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b'0')
                lock_file.flush()
            lock_file.seek(0)
            while True:
                try:
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.05)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            lock_file.seek(0)
            if os.name == 'nt':
                import msvcrt

                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _read_data_unlocked(db_path):
    if not os.path.exists(db_path):
        data = _initial_data()
        _write_data_unlocked(db_path, data)
        return data
    with open(db_path, 'r', encoding='utf-8') as file:
        return json.load(file)


def _write_data_unlocked(db_path, data):
    data['last_updated'] = datetime.now(CN_TZ).strftime('%Y-%m-%d %H:%M:%S')
    directory = os.path.dirname(db_path) or '.'
    os.makedirs(directory, exist_ok=True)
    temporary_path = os.path.join(
        directory, f'.{os.path.basename(db_path)}.{os.getpid()}.{uuid.uuid4().hex}.tmp'
    )
    try:
        with open(temporary_path, 'w', encoding='utf-8') as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, db_path)
    finally:
        if os.path.exists(temporary_path):
            os.remove(temporary_path)


def init_db():
    """Create the state file once, without racing other API/Worker processes."""
    with _state_lock():
        _read_data_unlocked(get_db_path())


def load_data():
    """Read a complete JSON snapshot while writers hold the shared lock."""
    with _state_lock():
        return _read_data_unlocked(get_db_path())


def save_data(data):
    """Atomically replace a complete snapshot.

    Callers deriving a mutation from current state must use ``update_data`` so
    their read-modify-write sequence holds one shared lock.
    """
    with _state_lock():
        _write_data_unlocked(get_db_path(), data)


def update_data(mutator):
    """Run a state mutation under one cross-process lock and atomically persist it."""
    with _state_lock():
        data = _read_data_unlocked(get_db_path())
        mutator(data)
        _write_data_unlocked(get_db_path(), data)
        return data


def add_favorite(item_type, item, owner=None):
    item['id'] = f"{item_type}_{int(datetime.now(CN_TZ).timestamp())}"
    item['type'] = item_type
    item['saved_at'] = datetime.now(CN_TZ).strftime('%Y-%m-%d %H:%M:%S')
    item['tags'] = item.get('tags', [])
    item['notes'] = item.get('notes', '')
    item['owner'] = owner

    def add(data):
        data.setdefault('favorites', []).append(item)

    update_data(add)
    return item


def remove_favorite(item_id, owner=None):
    """删除收藏（带归属校验）。返回是否真正删除（False = 不存在或不属于该 owner）。"""
    result = {'removed': False}

    def remove(data):
        favorites = data.setdefault('favorites', [])
        remaining = [
            favorite for favorite in favorites
            if not (favorite['id'] == item_id and favorite.get('owner') == owner)
        ]
        result['removed'] = len(favorites) > len(remaining)
        data['favorites'] = remaining

    update_data(remove)
    return result['removed']


def update_favorite(item_id, tags=None, notes=None, owner=None):
    result = {'favorite': None}

    def update(data):
        for favorite in data.setdefault('favorites', []):
            if favorite['id'] == item_id and favorite.get('owner') == owner:
                if tags is not None:
                    favorite['tags'] = tags
                if notes is not None:
                    favorite['notes'] = notes
                result['favorite'] = favorite
                return

    update_data(update)
    return result['favorite']


def get_favorites(item_type=None, tag=None, owner=None):
    data = load_data()
    favorites = data.setdefault('favorites', [])
    # 归属过滤：无 owner 时不返回任何收藏（fail-closed，防止跨用户泄露）
    favorites = [favorite for favorite in favorites if favorite.get('owner') == owner]
    if item_type:
        favorites = [favorite for favorite in favorites if favorite['type'] == item_type]
    if tag:
        favorites = [favorite for favorite in favorites if tag in favorite.get('tags', [])]
    return favorites


def migrate_legacy_favorites(mid):
    """认领无主/旧口令归属的收藏，返回认领条数。"""
    target = str(mid)
    result = {'claimed': 0}

    def migrate(data):
        for favorite in data.setdefault('favorites', []):
            if favorite.get('owner') is None or favorite.get('owner') == 'admin':
                favorite['owner'] = target
                result['claimed'] += 1

    update_data(migrate)
    return result['claimed']
