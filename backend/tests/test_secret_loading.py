import os
import subprocess
import sys

from config import get_write_token


def test_get_write_token_reads_runtime_secret_file(tmp_path, monkeypatch):
    secret_file = tmp_path / "secrets" / "write_token"
    secret_file.parent.mkdir()
    secret_file.write_text("file-token-value\n", encoding="utf-8")
    monkeypatch.delenv("KICHU_WRITE_TOKEN", raising=False)
    monkeypatch.setenv("KICHU_WRITE_TOKEN_FILE", str(secret_file))

    assert get_write_token() == "file-token-value"


def test_api_startup_never_prints_write_token(tmp_path):
    token = "never-print-this-write-token"
    env = os.environ.copy()
    env.update(
        {
            "KICHU_WRITE_TOKEN": token,
            "KICHU_DB_PATH": str(tmp_path / "db" / "business.db"),
            "KICHU_AUTH_DB_PATH": str(tmp_path / "auth" / "auth.db"),
            "KICHU_STATE_PATH": str(tmp_path / "state" / "state.json"),
            "KICHU_COOKIE_PATH": str(tmp_path / "private" / "cookie.json"),
            "KICHU_LOG_DIR": str(tmp_path / "logs"),
            "KICHU_BACKUP_DIR": str(tmp_path / "backups"),
        }
    )

    result = subprocess.run(
        [sys.executable, "-c", "import app"],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert token not in result.stdout
    assert token not in result.stderr
