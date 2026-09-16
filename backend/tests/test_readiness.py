"""Liveness and PostgreSQL readiness endpoint contracts."""

import time

from storage.health import PostgresReadinessService


class _Readiness:
    def __init__(self, ready, reason=None):
        self.ready = ready
        self.reason = reason

    def check(self):
        return self.ready, self.reason


def test_live_does_not_require_readiness_dependency(monkeypatch):
    from app import app

    monkeypatch.setitem(app.config, "READINESS_SERVICE", _Readiness(False, "database_unavailable"))
    client = app.test_client()

    assert client.get("/api/health/live").status_code == 200


def test_ready_returns_503_for_stale_worker(monkeypatch):
    from app import app

    monkeypatch.setitem(app.config, "READINESS_SERVICE", _Readiness(False, "worker_stale"))
    response = app.test_client().get("/api/health/ready")

    assert response.status_code == 503
    assert response.get_json()["reason"] == "worker_stale"


def test_postgres_readiness_rejects_stale_worker_heartbeat():
    service = PostgresReadinessService(
        probe=lambda: {"revision": "head", "worker_heartbeat": 100},
        expected_revision="head", now=lambda: 221,
    )

    assert service.check() == (False, "worker_stale")


def test_heartbeat_service_records_once_before_sleeping():
    calls = []
    from storage.health import HeartbeatService

    service = HeartbeatService(
        repository=lambda worker_id, now, details: calls.append((worker_id, now, details)),
        worker_id="worker-1", details={"kind": "scheduler"}, now=lambda: 100,
    )

    service.beat()

    assert calls == [("worker-1", 100, {"kind": "scheduler"})]
