"""Real Flask queue contract and least-privilege API submission."""
import pytest
from sqlalchemy import text

import app as app_module
import storage.tracked_ups as tracked
from tests.test_calendar_api import client, _admin_headers, ADMIN_TOKEN
from tests.test_final_artifact import production_roles, bootstrap_roles


def test_refresh_and_reload_reuse_durable_active_task(client, postgres_runtime):
    tracked.save_tracked_list([{"mid": 1, "name": "A", "enabled": True}])
    first = client.post("/api/up-trends/refresh", headers=_admin_headers())
    assert first.status_code == 200
    busy = client.post("/api/up-trends/refresh", headers=_admin_headers())
    assert busy.status_code == 409 and busy.json["busy"] is True
    assert busy.json["task_id"] == first.json["task_id"]
    check = client.get("/api/up-trends/check")
    assert check.json["active_task_id"] == first.json["task_id"]
    response = client.get(f"/api/up-trends/progress?task_id={first.json['task_id']}")
    assert response.json["data"]["status"] == "queued"
    assert response.json["data"]["done"] is False
    assert response.json["data"]["worker_unavailable"] is True
    postgres_runtime.state.record_worker_heartbeat("worker", int(app_module.time.time()), {})
    available = client.get(f"/api/up-trends/progress?task_id={first.json['task_id']}")
    assert available.json["data"]["worker_unavailable"] is False
    assert postgres_runtime.analysis_jobs.get(first.json["task_id"])["requested_by"] != "system"


def test_unknown_task_and_unauthorized_submit(client):
    assert client.post("/api/up-trends/refresh").status_code == 401
    assert client.get("/api/up-trends/progress").status_code == 400
    unknown = client.get("/api/up-trends/progress?task_id=not-a-uuid")
    assert unknown.status_code == 404 and unknown.json["code"] == "task_not_found"
    assert client.post("/api/up-trends/refresh", headers=_admin_headers()).status_code == 400


def test_submission_database_error_is_safe(client, postgres_runtime, monkeypatch):
    tracked.save_tracked_list([{"mid": 1, "name": "A", "enabled": True}])
    def fail(*args):
        raise RuntimeError("PRIVATE_CONNECTION_SECRET_MARKER")
    monkeypatch.setattr(postgres_runtime.analysis_jobs, "enqueue", fail)
    response = client.post("/api/up-trends/refresh", headers=_admin_headers())
    assert response.status_code == 503
    assert response.json["code"] == "analysis_queue_unavailable"
    assert "PRIVATE_CONNECTION_SECRET_MARKER" not in response.get_data(as_text=True)


def test_real_api_role_can_submit_without_collection_write_grants(production_roles, monkeypatch, tmp_path):
    from storage.repositories.state import StateRepository
    from storage.runtime import configure_postgres_runtime
    from storage.repositories.analysis_jobs import configure_analysis_repository
    from storage import auth_store, database, db, runtime_settings
    StateRepository.from_url(production_roles.url).save_tracked_list([{"mid": 1, "name": "A", "enabled": True}], 1)
    url_file = tmp_path / "ephemeral-api-url"
    url_file.write_text(production_roles.url.set(username="kichu_api", password="fixture-password").render_as_string(hide_password=False), encoding="utf-8")
    runtime = configure_postgres_runtime("api", {"KICHU_API_DATABASE_URL_FILE": str(url_file)})
    monkeypatch.setattr(app_module, "WRITE_TOKEN", ADMIN_TOKEN)
    try:
        with app_module.app.test_client() as client:
            response = client.post("/api/up-trends/refresh", headers=_admin_headers())
        assert response.status_code == 200
        assert runtime.analysis_jobs.get(response.json["task_id"])["status"] == "queued"
        with pytest.raises(Exception) as denied:
            with runtime.sessions.begin() as session:
                session.execute(text("INSERT INTO app.video_snapshot_documents(ts,field,payload) VALUES(1,'probe','{}')"))
        assert denied.value.orig.sqlstate == '42501'
    finally:
        configure_analysis_repository(None)
        db.configure_business_repository(None)
        auth_store.configure_auth_repository(None)
        database.configure_state_repository(None)
        runtime_settings.configure_runtime_settings_repository(None)
        tracked.configure_state_repository(None)
        runtime.sessions.kw["bind"].dispose()
