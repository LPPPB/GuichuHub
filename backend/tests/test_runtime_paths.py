import json
import os
import subprocess
import sys
from pathlib import Path

from runtime_paths import RuntimePaths


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_runtime_paths_use_explicit_environment_values(tmp_path):
    paths = RuntimePaths.from_environment(
        {
            "KICHU_DB_PATH": str(tmp_path / "db" / "business.db"),
            "KICHU_AUTH_DB_PATH": str(tmp_path / "auth" / "auth.db"),
            "KICHU_STATE_PATH": str(tmp_path / "state" / "inspiration_db.json"),
            "KICHU_COOKIE_PATH": str(tmp_path / "private" / "cookie.json"),
            "KICHU_LOG_DIR": str(tmp_path / "logs"),
            "KICHU_BACKUP_DIR": str(tmp_path / "backups"),
        }
    )

    assert paths.business_db == (tmp_path / "db" / "business.db").resolve()
    assert paths.auth_db == (tmp_path / "auth" / "auth.db").resolve()
    assert paths.current_state == (tmp_path / "state" / "inspiration_db.json").resolve()
    assert paths.cookie_file == (tmp_path / "private" / "cookie.json").resolve()
    assert paths.log_dir == (tmp_path / "logs").resolve()
    assert paths.backup_dir == (tmp_path / "backups").resolve()


def test_runtime_paths_create_only_required_parent_directories(tmp_path):
    cookie_file = tmp_path / "private" / "cookie.json"
    paths = RuntimePaths.from_environment(
        {
            "KICHU_DB_PATH": str(tmp_path / "db" / "business.db"),
            "KICHU_AUTH_DB_PATH": str(tmp_path / "auth" / "auth.db"),
            "KICHU_STATE_PATH": str(tmp_path / "state" / "inspiration_db.json"),
            "KICHU_COOKIE_PATH": str(cookie_file),
            "KICHU_LOG_DIR": str(tmp_path / "logs"),
            "KICHU_BACKUP_DIR": str(tmp_path / "backups"),
        }
    )

    paths.create_required_directories()

    assert paths.business_db.parent.is_dir()
    assert paths.auth_db.parent.is_dir()
    assert paths.current_state.parent.is_dir()
    assert paths.cookie_file.parent.is_dir()
    assert paths.log_dir.is_dir()
    assert paths.backup_dir.is_dir()
    assert not paths.cookie_file.exists()
    assert not paths.business_db.exists()
    assert not paths.auth_db.exists()
    assert not paths.current_state.exists()


def test_backup_db_uses_independently_configured_backup_directory(tmp_path, monkeypatch):
    from storage import db

    business_db = tmp_path / "business" / "business.db"
    backup_dir = tmp_path / "backups"
    monkeypatch.setattr(db, "DATA_DIR", str(tmp_path / "legacy-data"))
    monkeypatch.setattr(db, "DB_PATH", str(business_db))
    monkeypatch.setattr(db, "BACKUP_DIR", str(backup_dir))
    db._thread_local.conn = None

    try:
        db.get_conn()
        backup_path = Path(db.backup_db(keep=1))
    finally:
        connection = getattr(db._thread_local, "conn", None)
        if connection is not None:
            connection.close()
        db._thread_local.conn = None

    assert backup_path.parent == backup_dir
    assert backup_path.exists()
    assert not (tmp_path / "legacy-data" / "backups").exists()


def test_current_state_updates_are_serialized_across_processes(tmp_path):
    state_path = tmp_path / "state" / "inspiration_db.json"
    environment = os.environ.copy()
    environment["KICHU_STATE_PATH"] = str(state_path)
    environment["PYTHONPATH"] = str(BACKEND_ROOT)
    script = """
import time
from storage.database import update_data

def increment(data):
    value = data.get('counter', 0)
    time.sleep(0.2)
    data['counter'] = value + 1

update_data(increment)
"""

    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script],
            cwd=BACKEND_ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    results = [process.communicate(timeout=10) for process in processes]

    assert all(process.returncode == 0 for process in processes), results
    assert json.loads(state_path.read_text(encoding="utf-8"))["counter"] == 2
