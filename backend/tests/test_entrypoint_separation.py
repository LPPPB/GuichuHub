import importlib
import os
from pathlib import Path
import subprocess
import sys


def _import_fresh(module_name):
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


def test_cold_importing_api_entrypoint_does_not_start_scheduler(tmp_path):
    backend_dir = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env.update(
        {
            "ENTRYPOINT_TEST_DATA_DIR": str(tmp_path / "cache"),
            "KICHU_DB_PATH": str(tmp_path / "db" / "business.db"),
            "KICHU_AUTH_DB_PATH": str(tmp_path / "auth" / "auth.db"),
            "KICHU_STATE_PATH": str(tmp_path / "state" / "state.json"),
            "KICHU_COOKIE_PATH": str(tmp_path / "private" / "cookie.json"),
            "KICHU_LOG_DIR": str(tmp_path / "logs"),
            "KICHU_BACKUP_DIR": str(tmp_path / "backups"),
            "KICHU_WRITE_TOKEN": "entrypoint-test-token",
        }
    )
    script = """
import os
from jobs import scheduler
from storage import database

calls = []
database.DATA_DIR = os.environ["ENTRYPOINT_TEST_DATA_DIR"]
scheduler.setup_scheduler = lambda: calls.append("scheduler")

import api_entrypoint

assert api_entrypoint.app is not None
assert calls == []
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=backend_dir,
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_worker_entrypoint_initializes_services_once_then_waits(monkeypatch):
    worker_entrypoint = _import_fresh("worker_entrypoint")
    calls = []

    monkeypatch.setattr(
        worker_entrypoint,
        "init_db",
        lambda: calls.append("database"),
    )
    monkeypatch.setattr(
        worker_entrypoint,
        "setup_scheduler",
        lambda: calls.append("scheduler"),
    )
    monkeypatch.setattr(
        worker_entrypoint,
        "ensure_calendar_worker",
        lambda: calls.append("calendar"),
    )
    monkeypatch.setattr(
        worker_entrypoint,
        "ensure_collector_handoff_worker",
        lambda: calls.append("collector-handoff"),
        raising=False,
    )
    monkeypatch.setattr(
        worker_entrypoint,
        "_crawl_once",
        lambda reason: calls.append(f"crawl:{reason}"),
        raising=False,
    )

    class FakeThread:
        def __init__(self, *, target, args, daemon):
            assert target is worker_entrypoint._crawl_once
            assert args == ("startup",)
            assert daemon is True
            self.target = target
            self.args = args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(worker_entrypoint, "Thread", FakeThread, raising=False)

    class FakeEvent:
        def wait(self):
            calls.append("wait")

    monkeypatch.setattr(worker_entrypoint, "Event", FakeEvent)

    worker_entrypoint.run_worker()

    assert calls == [
        "database",
        "scheduler",
        "calendar",
        "collector-handoff",
        "crawl:startup",
        "wait",
    ]
