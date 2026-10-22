"""管理员身份体系测试：B站账号判定链 + 名单管理 + 多会话登录 + 采集解耦。

设计（2026-08-29 方案，替代纯口令判定）：
  判定链（三态）：
    1. X-Write-Token 匹配 → 超级管理员（应急后门，永不过期）
    2. HttpOnly 会话 Cookie → bili_sessions 有效 → mid ∈ admin_accounts → 管理员
    3. 其他（仅访客身份 / 未在名单的B站登录 / 会话过期）→ 普通访客
  多会话登录：
    访客扫码登录自己的B站账号 → 凭证只落服务器（bili_sessions.cookies），
    浏览器仅接收 HttpOnly 会话 Cookie（绝不回传 SESSDATA/bili_jct）；
    同浏览器重新登录替换旧会话（单浏览器单账号）。
  采集解耦：
    身份登录不写 bilibili_cookie.json（save=False）；
    采集账号登录走管理员专属路由 collect-login/collect-check 才写（save=True）。
  名单保护：
    删除最后一名管理员被拒（防自锁）；支持 mid 直填与最近登录参考。
"""

import pytest

import storage.auth_store as auth_store
import app as app_module


ADMIN_TOKEN = 'test-admin-token-0123456789abcdef'
QR_KEY = 'qr-key-001'
VID_A = '11111111-1111-1111-1111-111111111111'
VID_B = '22222222-2222-2222-2222-222222222222'


def _fake_qr():
    return {'success': True, 'url': 'https://qr', 'qrcode_key': QR_KEY,
            'qrcode_image': 'data:image/png;base64,x'}


def _fake_check(key, save=True):
    """身份/采集登录成功响应（含凭证——路由必须剥除后才能出网）"""
    return {
        'success': True, 'status': 'success', 'message': '登录成功', 'user_mid': 42,
        'cookies': {'SESSDATA': 'SECRET_SESSDATA', 'bili_jct': 'SECRET_JCT',
                    'DedeUserID': '42'},
    }


@pytest.fixture
def client(monkeypatch, postgres_runtime):
    """独立 PostgreSQL 测试库 + 已知超管口令的 Flask test client"""
    monkeypatch.setattr(app_module, 'WRITE_TOKEN', ADMIN_TOKEN)
    # 采集层 mock：登录链路不依赖真实B站
    monkeypatch.setattr(app_module, 'generate_qrcode', _fake_qr)
    monkeypatch.setattr(app_module, 'check_login_status', _fake_check)
    monkeypatch.setattr(app_module, 'get_user_info_with_cookie',
                        lambda cs: {'mid': 42, 'name': '测试账号', 'face': 'http://face/42.png'})

    app_module.app.config['TESTING'] = True
    if hasattr(app_module, '_VERIFY_FAILURES'):
        app_module._VERIFY_FAILURES.clear()
    if hasattr(app_module, '_QR_PENDING'):
        app_module._QR_PENDING.clear()
    with app_module.app.test_client() as c:
        yield c


def _login(client, monkeypatch=None, vid=VID_A, mid=42, name='测试账号'):
    """Seed a historical session directly; the retired QR API cannot create one."""
    token = auth_store.create_session(vid, mid, name, '', {'SESSDATA': 'synthetic'})
    client.set_cookie(app_module.SESSION_COOKIE_NAME, token)
    return token, {'mid': mid, 'name': name, 'face': ''}


def _use_session(client, token, headers=None):
    """切换 Flask 测试客户端的 HttpOnly 会话 Cookie。"""
    client.set_cookie(app_module.SESSION_COOKIE_NAME, token)
    return headers or {}


def _add_admin(client, mid, name=''):
    """超管口令添加管理员名单"""
    return client.post('/api/admin/accounts', json={'mid': mid, 'name': name},
                       headers={'X-Write-Token': ADMIN_TOKEN})


# ==================== 判定链（三态） ====================

class TestAdminChain:

    def test_write_token_is_super_admin(self, client):
        """应急后门：写口令命中 → 管理员（无B站身份）"""
        res = client.get('/api/auth/me', headers={'X-Write-Token': ADMIN_TOKEN})
        data = res.get_json()['data']
        assert data['admin'] is True
        assert data['via'] == 'write_token'
        assert data['user'] is None

    def test_session_admin_in_list(self, client, monkeypatch):
        _add_admin(client, 42)
        token, _ = _login(client, mid=42)
        data = client.get('/api/auth/me', headers=_use_session(client, token)).get_json()['data']
        assert data == {'admin': False, 'via': None, 'user': None}
        assert auth_store.get_session(token) is not None

    def test_session_not_in_list_is_visitor(self, client, monkeypatch):
        token, _ = _login(client, mid=99)
        data = client.get('/api/auth/me', headers=_use_session(client, token)).get_json()['data']
        assert data == {'admin': False, 'via': None, 'user': None}

    def test_no_identity_plain_visitor(self, client):
        """无任何凭证 → 纯访客"""
        res = client.get('/api/auth/me')
        data = res.get_json()['data']
        assert data['admin'] is False
        assert data['user'] is None

    def test_invalid_session_token(self, client):
        """伪造 session token → 视为访客"""
        res = client.get('/api/auth/me', headers=_use_session(client, 'forged-token'))
        data = res.get_json()['data']
        assert data['admin'] is False
        assert data['user'] is None

    def test_expired_session_not_admin(self, client, monkeypatch):
        """会话过期 → 身份失效"""
        _add_admin(client, 42)
        token, _ = _login(client, monkeypatch, mid=42)
        # 直接把会话改成过期
        from storage.models import browser_sessions
        repository = auth_store._auth_repository
        with repository._sessions.begin() as session:
            session.execute(browser_sessions.update().where(
                browser_sessions.c.token == token,
            ).values(expires_at=1))
        res = client.get('/api/auth/me', headers=_use_session(client, token))
        data = res.get_json()['data']
        assert data['admin'] is False
        assert data['user'] is None

    def test_write_token_beats_session(self, client, monkeypatch):
        token, _ = _login(client, mid=99)
        data = client.get('/api/auth/me', headers=_use_session(client, token, {'X-Write-Token': ADMIN_TOKEN})).get_json()['data']
        assert data == {'admin': True, 'via': 'write_token', 'user': None}


# ==================== 多会话登录 ====================

class TestSessionLogin:
    def test_retired_login_cannot_replace_historical_session(self, client):
        token, _ = _login(client)
        for path in ('qrcode', 'check?key=never-issued'):
            response = client.get('/api/bili-auth/' + path)
            assert response.status_code == 410
            assert 'Set-Cookie' not in response.headers
            assert 'SESSDATA' not in response.get_data(as_text=True)
        assert auth_store.get_session(token) is not None

    def test_logout_deletes_session_only_when_explicitly_requested(self, client):
        token, _ = _login(client)
        assert client.post('/api/bili-auth/logout').status_code == 200
        assert auth_store.get_session(token) is None

    def test_logout_without_session_rejected(self, client):
        assert client.post('/api/bili-auth/logout').status_code == 401

    def test_retired_login_does_not_update_admin_profile(self, client):
        _add_admin(client, 42, name='retained name')
        assert client.get('/api/bili-auth/check?key=old').status_code == 410
        accounts = client.get('/api/admin/accounts', headers={'X-Write-Token': ADMIN_TOKEN}).get_json()['data']['accounts']
        assert accounts[0]['name'] == 'retained name'


# ==================== 管理员名单管理 ====================

class TestAdminAccountsApi:

    def test_list_requires_admin(self, client):
        res = client.get('/api/admin/accounts')
        assert res.status_code == 403

    def test_super_admin_add_and_list(self, client):
        res = _add_admin(client, 42, name='站长')
        assert res.status_code == 200
        data = client.get('/api/admin/accounts',
                          headers={'X-Write-Token': ADMIN_TOKEN}).get_json()['data']
        assert [a['mid'] for a in data['accounts']] == [42]
        assert data['accounts'][0]['name'] == '站长'

    def test_duplicate_add_conflict(self, client):
        _add_admin(client, 42)
        res = _add_admin(client, 42)
        assert res.status_code == 409

    def test_invalid_mid_rejected(self, client):
        res = client.post('/api/admin/accounts', json={'mid': 'abc'},
                          headers={'X-Write-Token': ADMIN_TOKEN})
        assert res.status_code == 400

    def test_delete_last_admin_forbidden(self, client):
        """删除保护：名单只剩一人时拒绝删除（防自锁）"""
        _add_admin(client, 42)
        res = client.delete('/api/admin/accounts/42', headers={'X-Write-Token': ADMIN_TOKEN})
        assert res.status_code == 400
        assert '至少' in res.get_json()['message']

    def test_delete_ok_when_others_remain(self, client):
        _add_admin(client, 42)
        _add_admin(client, 43)
        res = client.delete('/api/admin/accounts/42', headers={'X-Write-Token': ADMIN_TOKEN})
        assert res.status_code == 200
        assert auth_store.is_admin_mid(42) is False
        assert auth_store.is_admin_mid(43) is True

    def test_delete_not_found(self, client):
        _add_admin(client, 42)
        res = client.delete('/api/admin/accounts/999', headers={'X-Write-Token': ADMIN_TOKEN})
        assert res.status_code == 404

    def test_session_admin_cannot_manage_after_retirement(self, client, monkeypatch):
        _add_admin(client, 42)
        token, _ = _login(client, mid=42)
        assert client.post('/api/admin/accounts', json={'mid': 43}, headers=_use_session(client, token)).status_code == 401
        assert client.delete('/api/admin/accounts/43', headers=_use_session(client, token)).status_code == 401

    def test_recent_logins_reference(self, client, monkeypatch):
        """最近登录列表：给"一键设为管理员"提供参考"""
        _login(client, monkeypatch, mid=77)
        data = client.get('/api/admin/accounts',
                          headers={'X-Write-Token': ADMIN_TOKEN}).get_json()['data']
        mids = [r['mid'] for r in data['recent_logins']]
        assert 77 in mids


# ==================== 采集账号（管理员专属） ====================

class TestCollectLogin:

    def test_collect_login_blocked_for_visitor(self, client):
        """访客不能发起采集账号登录（防扫码顶替爬虫 Cookie）"""
        res = client.get('/api/bili-auth/collect-login')
        assert res.status_code == 410

    def test_collect_check_blocked_for_visitor(self, client):
        res = client.get('/api/bili-auth/collect-check?key=x')
        assert res.status_code == 410

    def test_retired_collect_login_never_hands_off_credentials(self, client, monkeypatch):
        handed_off = []
        monkeypatch.setattr(app_module, 'request_collector_cookie_update', lambda *args: handed_off.append(args))
        for path in ('collect-login', 'collect-check?key=old'):
            assert client.get('/api/bili-auth/' + path, headers={'X-Write-Token': ADMIN_TOKEN}).status_code == 410
        assert handed_off == []

    def test_collect_logout_requires_admin(self, client):
        res = client.post('/api/bili-auth/collect-logout')
        assert res.status_code == 401

    def test_collect_logout_clears_crawl_cookie(self, client, monkeypatch):
        cleared = []
        monkeypatch.setattr(app_module, 'request_collector_logout',
                            lambda requested_by: cleared.append(requested_by))
        res = client.post('/api/bili-auth/collect-logout',
                          headers={'X-Write-Token': ADMIN_TOKEN})
        assert res.status_code == 200
        assert cleared == ['write_token']

    def test_crawl_user_info_still_admin_only(self, client):
        """采集账号信息（昵称/头像）仍不对访客暴露"""
        res = client.get('/api/bili-auth/user')
        assert res.status_code == 403


# ==================== 写口令全局门与会话管理员兼容 ====================

class TestWriteGateWithSession:

    def test_session_admin_cannot_pass_write_gate(self, client, monkeypatch):
        _add_admin(client, 42)
        token, _ = _login(client, mid=42)
        assert client.post('/api/auth/verify', headers=_use_session(client, token)).status_code == 401

    def test_visitor_session_blocked_from_write(self, client, monkeypatch):
        token, _ = _login(client, monkeypatch, mid=99)  # 不在名单
        res = client.post('/api/auth/verify', headers=_use_session(client, token))
        assert res.status_code == 401
