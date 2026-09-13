import importlib
import sys


def _import_fresh(module_name):
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


def test_importing_api_entrypoint_does_not_start_scheduler(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "jobs.scheduler.setup_scheduler",
        lambda: calls.append("scheduler"),
    )

    api_entrypoint = _import_fresh("api_entrypoint")

    assert api_entrypoint.app is not None
    assert calls == []


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

    class FakeEvent:
        def wait(self):
            calls.append("wait")

    monkeypatch.setattr(worker_entrypoint, "Event", FakeEvent)

    worker_entrypoint.run_worker()

    assert calls == ["database", "scheduler", "calendar", "wait"]
