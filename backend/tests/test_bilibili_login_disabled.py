"""Retiring QR login must neither contact Bilibili nor consume stored sessions."""

from unittest.mock import Mock

import pytest

import app as app_module


@pytest.fixture
def retired_client(monkeypatch):
    generate = Mock(return_value={"success": True, "qrcode_key": "retired-qr"})
    poll = Mock(return_value={"success": False, "status": "waiting"})
    lookup = Mock(return_value={"mid": 42, "name": "old user", "face": ""})
    monkeypatch.setattr(app_module, "generate_qrcode", generate)
    monkeypatch.setattr(app_module, "check_login_status", poll)
    monkeypatch.setattr(app_module, "get_session", lookup)
    monkeypatch.setattr(app_module, "is_admin_mid", lambda mid: True)
    app_module._QR_PENDING.clear()
    app_module._qr_register("retired-qr", "visitor", "identity")
    with app_module.app.test_client() as client:
        yield client, generate, poll, lookup
    app_module._QR_PENDING.clear()


@pytest.mark.parametrize("path", ["qrcode", "check", "collect-login", "collect-check"])
@pytest.mark.parametrize("admin", [False, True])
def test_qr_endpoints_are_gone_even_for_administrators(retired_client, path, admin):
    client, generate, poll, _ = retired_client
    headers = {"X-Visitor-Id": "visitor"}
    if admin:
        headers["X-Write-Token"] = app_module.WRITE_TOKEN
    response = client.get(f"/api/bili-auth/{path}?key=retired-qr", headers=headers)
    assert response.status_code == 410
    assert response.get_json()["code"] == "BILIBILI_LOGIN_DISABLED"
    assert response.headers["Cache-Control"] == "no-store"
    assert "Set-Cookie" not in response.headers
    generate.assert_not_called()
    poll.assert_not_called()


def test_old_bilibili_cookie_cannot_authenticate_or_trigger_lazy_session_deletion(retired_client):
    client, _, _, lookup = retired_client
    client.set_cookie(app_module.SESSION_COOKIE_NAME, "old-site-session")
    response = client.get("/api/auth/me")
    assert response.get_json()["data"] == {"admin": False, "via": None, "user": None}
    lookup.assert_not_called()


def test_write_token_administration_survives_without_bilibili_identity(retired_client):
    client, _, _, lookup = retired_client
    client.set_cookie(app_module.SESSION_COOKIE_NAME, "old-site-session")
    headers = {"X-Write-Token": app_module.WRITE_TOKEN}
    assert client.get("/api/auth/me", headers=headers).get_json()["data"] == {
        "admin": True, "via": "write_token", "user": None,
    }
    assert client.post("/api/auth/verify", headers=headers).status_code == 200
    lookup.assert_not_called()
