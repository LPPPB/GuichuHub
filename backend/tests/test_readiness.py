"""Liveness and PostgreSQL readiness endpoint contracts."""


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
