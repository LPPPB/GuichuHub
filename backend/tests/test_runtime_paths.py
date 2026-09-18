from runtime_paths import RuntimePaths


def test_runtime_paths_use_explicit_environment_values(tmp_path):
    paths = RuntimePaths.from_environment(
        {
            "KICHU_COOKIE_PATH": str(tmp_path / "private" / "cookie.json"),
            "KICHU_LOG_DIR": str(tmp_path / "logs"),
        }
    )

    assert paths.cookie_file == (tmp_path / "private" / "cookie.json").resolve()
    assert paths.log_dir == (tmp_path / "logs").resolve()
    assert not hasattr(paths, "business_db")
    assert not hasattr(paths, "auth_db")
    assert not hasattr(paths, "current_state")
    assert not hasattr(paths, "backup_dir")


def test_runtime_paths_create_only_required_parent_directories(tmp_path):
    cookie_file = tmp_path / "private" / "cookie.json"
    paths = RuntimePaths.from_environment(
        {
            "KICHU_COOKIE_PATH": str(cookie_file),
            "KICHU_LOG_DIR": str(tmp_path / "logs"),
        }
    )

    paths.create_required_directories()

    assert paths.cookie_file.parent.is_dir()
    assert paths.log_dir.is_dir()
    assert not paths.cookie_file.exists()
