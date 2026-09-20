import json

from storage import auth_store


def test_collector_cookie_handoff_is_durable_until_worker_ack(postgres_runtime):
    auth_store.request_collector_cookie_update(
        {"SESSDATA": "pending-secret", "bili_jct": "csrf"},
        requested_by="write_token",
    )

    pending = auth_store.get_pending_collector_action()

    assert pending["action"] == "replace"
    assert json.loads(pending["payload"])["SESSDATA"] == "pending-secret"
    assert auth_store.complete_collector_action(pending["id"]) is True
    assert auth_store.get_pending_collector_action() is None


def test_worker_consumes_cookie_handoff_once(tmp_path, monkeypatch, postgres_runtime):
    from collectors import bilibili_auth
    from jobs.collector_handoff import process_pending_collector_action

    cookie_file = tmp_path / "private" / "bilibili_cookie.json"
    monkeypatch.setattr(bilibili_auth, "COOKIE_FILE", str(cookie_file))
    auth_store.request_collector_cookie_update(
        {"SESSDATA": "worker-owned"}, requested_by="session:42"
    )

    assert process_pending_collector_action() is True
    assert process_pending_collector_action() is False
    assert json.loads(cookie_file.read_text(encoding="utf-8"))["cookies"]["SESSDATA"] == "worker-owned"
    assert auth_store.get_pending_collector_action() is None


def test_worker_delete_handoff_is_idempotent(tmp_path, monkeypatch, postgres_runtime):
    from collectors import bilibili_auth
    from jobs.collector_handoff import process_pending_collector_action

    cookie_file = tmp_path / "private" / "bilibili_cookie.json"
    cookie_file.parent.mkdir(parents=True)
    cookie_file.write_text('{"cookies":{"SESSDATA":"old"}}', encoding="utf-8")
    monkeypatch.setattr(bilibili_auth, "COOKIE_FILE", str(cookie_file))
    auth_store.request_collector_logout(requested_by="write_token")

    assert process_pending_collector_action() is True
    assert process_pending_collector_action() is False
    assert not cookie_file.exists()


def test_worker_keeps_handoff_pending_when_cookie_write_fails(
    tmp_path, monkeypatch, postgres_runtime,
):
    from jobs import collector_handoff

    auth_store.request_collector_cookie_update(
        {"SESSDATA": "retry-me"}, requested_by="write_token"
    )
    monkeypatch.setattr(
        collector_handoff,
        "save_cookie",
        lambda cookies: (_ for _ in ()).throw(OSError("disk unavailable")),
    )

    try:
        collector_handoff.process_pending_collector_action()
    except OSError as exc:
        assert str(exc) == "disk unavailable"
    else:
        raise AssertionError("worker must surface persistence failure")

    assert auth_store.get_pending_collector_action() is not None
