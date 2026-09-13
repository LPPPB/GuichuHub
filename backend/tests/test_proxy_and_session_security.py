"""Session-cookie, CORS and trusted-proxy boundary regression tests."""

from flask import Flask, jsonify, request
import pytest

import app as app_module
import storage.auth_store as auth_store
import storage.database as database


SESSION_COOKIE = "kichu_session"
QR_KEY = "security-qr-key"
VISITOR_ID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def client(monkeypatch, tmp_path):
    """Use real Flask cookie handling and a disposable server-side session DB."""
    monkeypatch.setattr(database, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(auth_store, "AUTH_DB_PATH", str(tmp_path / "auth.db"))
    monkeypatch.setattr(
        app_module,
        "generate_qrcode",
        lambda: {
            "success": True,
            "url": "https://qr",
            "qrcode_key": QR_KEY,
            "qrcode_image": "data:image/png;base64,x",
        },
    )
    monkeypatch.setattr(
        app_module,
        "check_login_status",
        lambda key, save=True: {
            "success": True,
            "status": "success",
            "message": "登录成功",
            "user_mid": 42,
            "cookies": {
                "SESSDATA": "SECRET_SESSDATA",
                "bili_jct": "SECRET_JCT",
                "DedeUserID": "42",
            },
        },
    )
    monkeypatch.setattr(
        app_module,
        "get_user_info_with_cookie",
        lambda cookie_string: {"mid": 42, "name": "测试账号", "face": ""},
    )
    app_module.app.config["TESTING"] = True
    app_module._QR_PENDING.clear()
    with app_module.app.test_client() as test_client:
        yield test_client


def _login(client):
    response = client.get(
        "/api/bili-auth/qrcode", headers={"X-Visitor-Id": VISITOR_ID}
    )
    assert response.status_code == 200
    return client.get(
        f"/api/bili-auth/check?key={QR_KEY}",
        headers={"X-Visitor-Id": VISITOR_ID},
    )


def _make_probe_app(environ):
    probe = Flask(__name__)

    @probe.get("/probe")
    def transport_probe():
        return jsonify(
            remote_addr=request.remote_addr,
            scheme=request.scheme,
            host=request.host,
        )

    app_module._configure_transport_security(probe, environ)
    return probe


def test_login_sets_hardened_cookie_without_returning_session_token(client):
    """Removing any cookie flag or returning the opaque token breaks this test."""
    response = _login(client)

    cookie = response.headers.get("Set-Cookie", "")
    assert f"{SESSION_COOKIE}=" in cookie
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=Lax" in cookie
    assert "Path=/" in cookie
    assert "session_token" not in response.get_json()


def test_server_uses_cookie_and_ignores_legacy_session_header(client):
    """A copied X-Session-Token header must not authenticate a new browser."""
    _login(client)
    cookie = client.get_cookie(SESSION_COOKIE)
    assert cookie is not None

    authenticated = client.get("/api/auth/me").get_json()["data"]
    assert authenticated["user"]["mid"] == 42

    token = cookie.value
    client.delete_cookie(SESSION_COOKIE)
    header_only = client.get(
        "/api/auth/me", headers={"X-Session-Token": token}
    ).get_json()["data"]
    assert header_only["user"] is None


def test_logout_clears_cookie_and_deletes_server_session(client):
    """Logout must invalidate both halves of the cookie-backed session."""
    _login(client)
    token = client.get_cookie(SESSION_COOKIE).value
    assert auth_store.get_session(token) is not None

    response = client.post("/api/bili-auth/logout")

    assert response.status_code == 200
    cleared = response.headers.get("Set-Cookie", "")
    assert f"{SESSION_COOKIE}=" in cleared
    assert "Max-Age=0" in cleared
    assert auth_store.get_session(token) is None


def test_logout_clears_stale_cookie_without_write_token(client):
    """A present Cookie stays safely logout-able after its server row is gone."""
    client.set_cookie(SESSION_COOKIE, "expired-or-deleted-session")

    response = client.post("/api/bili-auth/logout")

    assert response.status_code == 200
    assert response.get_json()["success"] is True
    cleared = response.headers.get("Set-Cookie", "")
    assert f"{SESSION_COOKIE}=" in cleared
    assert "Max-Age=0" in cleared
    assert "HttpOnly" in cleared
    assert "Secure" in cleared
    assert "SameSite=Lax" in cleared
    assert "Path=/" in cleared
    assert client.get_cookie(SESSION_COOKIE) is None


def test_production_has_no_cross_origin_access_or_proxy_trust():
    """Default production mode must ignore browser Origin and forwarded headers."""
    probe = _make_probe_app({})
    response = probe.test_client().get(
        "/probe",
        headers={
            "Origin": "http://localhost:5173",
            "X-Forwarded-For": "203.0.113.9",
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "dashboard.example",
        },
    )

    assert "Access-Control-Allow-Origin" not in response.headers
    assert response.get_json() == {
        "remote_addr": "127.0.0.1",
        "scheme": "http",
        "host": "localhost",
    }


@pytest.mark.parametrize(
    "origin", ["http://127.0.0.1:5173", "http://localhost:5173"]
)
def test_development_cors_allows_only_declared_vite_origins(origin):
    """Each supported Vite origin is explicitly echoed in development only."""
    probe = _make_probe_app({"KICHU_ENV": "development"})
    response = probe.test_client().get("/probe", headers={"Origin": origin})

    assert response.headers["Access-Control-Allow-Origin"] == origin
    assert response.headers["Access-Control-Allow-Credentials"] == "true"


def test_development_cors_rejects_other_origins():
    """Adding a wildcard or an extra development origin breaks this test."""
    probe = _make_probe_app({"KICHU_ENV": "development"})
    response = probe.test_client().get(
        "/probe", headers={"Origin": "https://attacker.example"}
    )

    assert "Access-Control-Allow-Origin" not in response.headers


def test_proxyfix_trusts_exactly_one_proxy_layer_when_enabled():
    """Only the right-most hop supplied by the direct proxy becomes the client."""
    probe = _make_probe_app({"KICHU_TRUST_PROXY": "1"})
    response = probe.test_client().get(
        "/probe",
        headers={
            "X-Forwarded-For": "198.51.100.7, 10.0.0.8",
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "dashboard.example",
        },
    )

    assert response.get_json() == {
        "remote_addr": "10.0.0.8",
        "scheme": "https",
        "host": "dashboard.example",
    }
