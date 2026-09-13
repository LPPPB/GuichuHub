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
