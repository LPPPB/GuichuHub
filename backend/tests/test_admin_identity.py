"""管理员身份体系测试：B站账号判定链 + 名单管理 + 多会话登录 + 采集解耦。

设计（2026-08-29 方案，替代纯口令判定）：
  判定链（三态）：
    1. X-Write-Token 匹配 → 超级管理员（应急后门，永不过期）
    2. X-Session-Token → bili_sessions 有效 → mid ∈ admin_accounts → 管理员
    3. 其他（仅访客身份 / 未在名单的B站登录 / 会话过期）→ 普通访客
  多会话登录：
    访客扫码登录自己的B站账号 → 凭证只落服务器（bili_sessions.cookies），
    浏览器只拿 session token（绝不回传 SESSDATA/bili_jct）；
    同浏览器重新登录替换旧会话（单浏览器单账号）。
  采集解耦：
    身份登录不写 bilibili_cookie.json（save=False）；
    采集账号登录走管理员专属路由 collect-login/collect-check 才写（save=True）。
  名单保护：
    删除最后一名管理员被拒（防自锁）；支持 mid 直填与最近登录参考。
"""

import pytest

import storage.auth_store as auth_store
import storage.database as database
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
def client(monkeypatch, tmp_path):
    """独立临时数据文件 + 临时 auth.db + 已知超管口令的 Flask test client"""
    monkeypatch.setattr(database, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(auth_store, 'AUTH_DB_PATH', str(tmp_path / 'auth.db'))
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
    """走完整身份登录流程（qrcode → check），返回 (session_token, user)"""
    if monkeypatch is not None:
        monkeypatch.setattr(app_module, 'check_login_status',
                            lambda key, save=True: {
                                'success': True, 'status': 'success', 'message': '登录成功',
                                'user_mid': mid,
                                'cookies': {'SESSDATA': 'S', 'bili_jct': 'J', 'DedeUserID': str(mid)},
                            })
    res = client.get('/api/bili-auth/qrcode', headers={'X-Visitor-Id': vid})
    assert res.status_code == 200, '二维码生成对访客开放'
    res = client.get(f'/api/bili-auth/check?key={QR_KEY}', headers={'X-Visitor-Id': vid})
    body = res.get_json()
    assert res.status_code == 200 and body.get('success'), f'登录失败: {body}'
    return body['session_token'], body['user']


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
        """B站账号 mid 在管理员名单 → 管理员"""
        _add_admin(client, 42)
        token, user = _login(client, monkeypatch, mid=42)
        res = client.get('/api/auth/me', headers={'X-Session-Token': token})
        data = res.get_json()['data']
        assert data['admin'] is True
        assert data['via'] == 'session'
        assert data['user']['mid'] == 42

    def test_session_not_in_list_is_visitor(self, client, monkeypatch):
        """B站登录但不在名单 → 非管理员（有身份的访客）"""
        token, user = _login(client, monkeypatch, mid=99)
        res = client.get('/api/auth/me', headers={'X-Session-Token': token})
        data = res.get_json()['data']
        assert data['admin'] is False
        assert data['user'] is not None and data['user']['mid'] == 99

    def test_no_identity_plain_visitor(self, client):
        """无任何凭证 → 纯访客"""
        res = client.get('/api/auth/me')
        data = res.get_json()['data']
        assert data['admin'] is False
        assert data['user'] is None

    def test_invalid_session_token(self, client):
        """伪造 session token → 视为访客"""
        res = client.get('/api/auth/me', headers={'X-Session-Token': 'forged-token'})
        data = res.get_json()['data']
        assert data['admin'] is False
        assert data['user'] is None

    def test_expired_session_not_admin(self, client, monkeypatch):
        """会话过期 → 身份失效"""
        _add_admin(client, 42)
        token, _ = _login(client, monkeypatch, mid=42)
        # 直接把会话改成过期
        conn = auth_store._conn()
        conn.execute('UPDATE bili_sessions SET expires_at = 1 WHERE token = ?', (token,))
        conn.commit()
        res = client.get('/api/auth/me', headers={'X-Session-Token': token})
        data = res.get_json()['data']
        assert data['admin'] is False
        assert data['user'] is None

    def test_write_token_beats_session(self, client, monkeypatch):
        """口令与 session 同在 → 管理员（超管优先级最高），且不透传吞掉 B站 user"""
        token, _ = _login(client, monkeypatch, mid=99)  # 99 不在名单
        res = client.get('/api/auth/me',
                         headers={'X-Session-Token': token, 'X-Write-Token': ADMIN_TOKEN})
        data = res.get_json()['data']
        assert data['admin'] is True and data['via'] == 'write_token'
        # 修复：写口令只决定 admin 权限，不得吞掉会话 user（否则登录状态“消失”）
        assert data['user'] is not None and data['user']['mid'] == 99


# ==================== 多会话登录 ====================

class TestSessionLogin:

    def test_login_returns_token_not_credentials(self, client):
        """浏览器只拿 session token：响应不得含 cookies/SESSDATA/bili_jct"""
        _, body = None, None
        res = client.get('/api/bili-auth/qrcode', headers={'X-Visitor-Id': VID_A})
        assert res.status_code == 200
        res = client.get(f'/api/bili-auth/check?key={QR_KEY}', headers={'X-Visitor-Id': VID_A})
        body = res.get_json()
        assert body['success'] is True
        assert body.get('session_token')
        assert 'cookies' not in body
        assert 'SESSDATA' not in str(body)
        assert 'bili_jct' not in str(body)

    def test_identity_login_does_not_write_crawl_cookie(self, client, monkeypatch):
        """身份登录不落采集 Cookie：check_login_status 必须以 save=False 调用"""
        calls = []
        monkeypatch.setattr(app_module, 'check_login_status',
                            lambda key, save=True: (calls.append(save), _fake_check(key))[1])
        _login(client)
        assert calls == [False], f'身份登录不得写采集cookie，实际 save 调用: {calls}'

    def test_qrcode_requires_visitor_id(self, client):
        res = client.get('/api/bili-auth/qrcode')
        assert res.status_code == 401

    def test_check_requires_registered_key(self, client):
        """未注册的二维码 key → 404（防 key 伪造/挪用）"""
        res = client.get('/api/bili-auth/check?key=never-issued', headers={'X-Visitor-Id': VID_A})
        assert res.status_code == 404

    def test_check_bound_to_generating_visitor(self, client):
        """A 生成的二维码，B 不能拿来完成登录"""
        client.get('/api/bili-auth/qrcode', headers={'X-Visitor-Id': VID_A})
        res = client.get(f'/api/bili-auth/check?key={QR_KEY}', headers={'X-Visitor-Id': VID_B})
        assert res.status_code == 403

    def test_relogin_replaces_old_session(self, client, monkeypatch):
        """同浏览器重新登录（换账号）→ 旧会话失效"""
        token1, _ = _login(client, monkeypatch, mid=42)
        token2, _ = _login(client, monkeypatch, mid=43)
        assert token1 != token2
        old = client.get('/api/auth/me', headers={'X-Session-Token': token1})
        assert old.get_json()['data']['user'] is None, '旧会话应已替换失效'
        new = client.get('/api/auth/me', headers={'X-Session-Token': token2})
        assert new.get_json()['data']['user']['mid'] == 43

    def test_logout_deletes_session(self, client, monkeypatch):
        token, _ = _login(client, monkeypatch, mid=42)
        res = client.post('/api/bili-auth/logout', headers={'X-Session-Token': token})
        assert res.status_code == 200
        me = client.get('/api/auth/me', headers={'X-Session-Token': token})
        assert me.get_json()['data']['user'] is None

    def test_logout_without_session_rejected(self, client):
        res = client.post('/api/bili-auth/logout')
        assert res.status_code == 401

    def test_login_admin_selfheals_profile(self, client, monkeypatch):
        """登录时回写名单内的昵称头像（管理员资料自愈）"""
        _add_admin(client, 42, name='')
        _login(client, monkeypatch, mid=42)
        accounts = client.get('/api/admin/accounts',
                              headers={'X-Write-Token': ADMIN_TOKEN}).get_json()['data']['accounts']
        row = next(a for a in accounts if a['mid'] == 42)
        assert row['name'] == '测试账号'
        assert row['face'] == 'http://face/42.png'


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

    def test_session_admin_can_manage(self, client, monkeypatch):
        """B站会话管理员也能增删名单（与超管等权）"""
        _add_admin(client, 42)
        token, _ = _login(client, monkeypatch, mid=42)
        res = client.post('/api/admin/accounts', json={'mid': 43},
                          headers={'X-Session-Token': token})
        assert res.status_code == 200
        res = client.delete('/api/admin/accounts/43', headers={'X-Session-Token': token})
        assert res.status_code == 200

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
        assert res.status_code == 403

    def test_collect_check_blocked_for_visitor(self, client):
        res = client.get('/api/bili-auth/collect-check?key=x')
        assert res.status_code == 403

    def test_collect_login_writes_crawl_cookie(self, client, monkeypatch):
        """采集登录：check_login_status 以 save=True 调用（写 bilibili_cookie.json）"""
        calls = []
        monkeypatch.setattr(app_module, 'check_login_status',
                            lambda key, save=True: (calls.append(save), _fake_check(key))[1])
        res = client.get('/api/bili-auth/collect-login',
                         headers={'X-Write-Token': ADMIN_TOKEN})
        assert res.status_code == 200
        res = client.get(f'/api/bili-auth/collect-check?key={QR_KEY}',
                         headers={'X-Write-Token': ADMIN_TOKEN})
        assert res.status_code == 200
        assert calls == [True], '采集登录必须 save=True 写爬虫 Cookie'
        assert 'cookies' not in res.get_json()

    def test_collect_logout_requires_admin(self, client):
        res = client.post('/api/bili-auth/collect-logout')
        assert res.status_code == 401

    def test_collect_logout_clears_crawl_cookie(self, client, monkeypatch):
        cleared = []
        monkeypatch.setattr(app_module, 'bili_logout', lambda: cleared.append(True))
        res = client.post('/api/bili-auth/collect-logout',
                          headers={'X-Write-Token': ADMIN_TOKEN})
        assert res.status_code == 200
        assert cleared == [True]

    def test_crawl_user_info_still_admin_only(self, client):
        """采集账号信息（昵称/头像）仍不对访客暴露"""
        res = client.get('/api/bili-auth/user')
        assert res.status_code == 403


# ==================== 写口令全局门与会话管理员兼容 ====================

class TestWriteGateWithSession:

    def test_session_admin_passes_write_gate(self, client, monkeypatch):
        """B站会话管理员无需写口令即可执行写操作（以 /auth/verify 为最轻探针）"""
        _add_admin(client, 42)
        token, _ = _login(client, monkeypatch, mid=42)
        res = client.post('/api/auth/verify', headers={'X-Session-Token': token})
        assert res.status_code == 200

    def test_visitor_session_blocked_from_write(self, client, monkeypatch):
        token, _ = _login(client, monkeypatch, mid=99)  # 不在名单
        res = client.post('/api/auth/verify', headers={'X-Session-Token': token})
        assert res.status_code == 401
