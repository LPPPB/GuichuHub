"""Production entrypoints must not touch SQLite or JSON state files."""

import os
from pathlib import Path
import subprocess
import sys


def test_production_api_liveness_never_opens_sqlite_or_state_json(tmp_path):
    url_file = tmp_path / "api-url"
    url_file.write_text("postgresql+psycopg://api:secret@db/kichu\n", encoding="utf-8")
    state_path = tmp_path / "inspiration_db.json"
    script = """
import sqlite3
sqlite3.connect = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("SQLite runtime access"))
import api_entrypoint
assert api_entrypoint.app.test_client().get('/api/health/live').status_code == 200
"""
    env = os.environ | {
        "KICHU_API_DATABASE_URL_FILE": str(url_file),
        "KICHU_STATE_PATH": str(state_path),
        "KICHU_WRITE_TOKEN": "test-token",
    }
    result = subprocess.run([sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[1],
                            env=env, text=True, capture_output=True)

    assert result.returncode == 0, result.stdout + result.stderr
    assert not state_path.exists()
