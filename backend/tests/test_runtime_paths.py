from pathlib import Path

from runtime_paths import RuntimePaths


def test_runtime_paths_use_explicit_environment_values(tmp_path):
    paths = RuntimePaths.from_environment(
        {
            "KICHU_DB_PATH": str(tmp_path / "db" / "business.db"),
            "KICHU_AUTH_DB_PATH": str(tmp_path / "auth" / "auth.db"),
            "KICHU_COOKIE_PATH": str(tmp_path / "private" / "cookie.json"),
            "KICHU_LOG_DIR": str(tmp_path / "logs"),
            "KICHU_BACKUP_DIR": str(tmp_path / "backups"),
        }
    )

    assert paths.business_db == (tmp_path / "db" / "business.db").resolve()
    assert paths.auth_db == (tmp_path / "auth" / "auth.db").resolve()
    assert paths.cookie_file == (tmp_path / "private" / "cookie.json").resolve()
    assert paths.log_dir == (tmp_path / "logs").resolve()
    assert paths.backup_dir == (tmp_path / "backups").resolve()


def test_runtime_paths_create_only_required_parent_directories(tmp_path):
    cookie_file = tmp_path / "private" / "cookie.json"
    paths = RuntimePaths.from_environment(
        {
            "KICHU_DB_PATH": str(tmp_path / "db" / "business.db"),
            "KICHU_AUTH_DB_PATH": str(tmp_path / "auth" / "auth.db"),
            "KICHU_COOKIE_PATH": str(cookie_file),
            "KICHU_LOG_DIR": str(tmp_path / "logs"),
            "KICHU_BACKUP_DIR": str(tmp_path / "backups"),
        }
    )

    paths.create_required_directories()

    assert paths.business_db.parent.is_dir()
    assert paths.auth_db.parent.is_dir()
    assert paths.cookie_file.parent.is_dir()
    assert paths.log_dir.is_dir()
    assert paths.backup_dir.is_dir()
    assert not paths.cookie_file.exists()
    assert not paths.business_db.exists()
    assert not paths.auth_db.exists()


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
