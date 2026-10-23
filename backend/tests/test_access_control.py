"""访问控制测试：收藏归属 B站账号 + 存量迁移（公网多用户部署安全修复）。

背景：原版所有收藏全局共享——公网访客可：
  1. GET /api/favorites 看到站主全部收藏（数据无用户概念）
  2. 打开登录弹窗生成二维码，用自己的 B 站 App 扫码顶替服务器爬虫 Cookie
     （2026-08-29 已由身份/采集解耦修复）

修复设计（2026-08-29 收藏归属改造）：
  收藏归属：登录 B站账号 → 按 mid 隔离（跨设备持久）；未登录 → 拒绝读写（401）
  存量迁移：无主收藏 + 旧写口令归属('admin')收藏，在首个 B站管理员会话访问时迁到其 mid
  账号保护：
    身份登录（qrcode/check）全员开放——登录自己的B站账号只落服务器会话表，
    不写采集 Cookie；采集登录（collect-*）与账号信息（user）仍要求管理员。
"""

import pytest
from sqlalchemy import select

import storage.auth_store as auth_store
import storage.database as database
import app as app_module
from storage.models import favorites


ADMIN_TOKEN = 'test-admin-token-0123456789abcdef'
QR_KEY = 'access-ctrl-qr-key'
VID_A = '11111111-1111-1111-1111-111111111111'
VID_B = '22222222-2222-2222-2222-222222222222'


@pytest.fixture
def client(monkeypatch, postgres_runtime):
    """独立临时数据文件 + 已知管理员口令的 Flask test client"""
    monkeypatch.setattr(app_module, 'WRITE_TOKEN', ADMIN_TOKEN)
    # bili-auth 采集层 mock：路由守卫测试不依赖真实 B 站 API
    monkeypatch.setattr(app_module, 'generate_qrcode',
                        lambda: {'success': True, 'url': 'https://qr', 'qrcode_key': QR_KEY,
                                 'qrcode_image': 'data:image/png;base64,x'})
    monkeypatch.setattr(app_module, 'check_login_status',
                        lambda key, save=True: {
                            'success': True, 'status': 'success', 'message': '登录成功',
                            'user_mid': 1,
                            'cookies': {'SESSDATA': 'SECRET_SESSDATA', 'bili_jct': 'SECRET_JCT',
                                        'DedeUserID': '1'},
                        })
    monkeypatch.setattr(app_module, 'get_user_info_with_cookie',
                        lambda cs: {'mid': 1, 'name': '站长', 'face': '', 'level': 6,
                                    'vip_status': 0, 'vip_type': 0, 'is_login': True})
    monkeypatch.setattr(app_module, 'get_user_info', lambda: {'name': '站长', 'face': '', 'mid': 1})
    monkeypatch.setattr(app_module, 'request_collector_logout', lambda requested_by: True)

    app_module.app.config['TESTING'] = True
    # 限速器状态隔离：每个用例从零失败开始（缺实现时 AttributeError = TDD 红）
    if hasattr(app_module, '_VERIFY_FAILURES'):
        app_module._VERIFY_FAILURES.clear()
    # 二维码待登录注册表隔离
    if hasattr(app_module, '_QR_PENDING'):
        app_module._QR_PENDING.clear()
    with app_module.app.test_client() as c:
        yield c


def _add(c, headers, item=None):
    return c.post('/api/favorites',
                  json={'type': 'meme', 'item': item or {'keyword': '测试梗', 'heat': 100}},
                  headers=headers)


def _login(client, monkeypatch, vid=VID_A, mid=1, name='站长'):
    """Inject a verified identity to isolate favorites ownership policy from QR login.

    Production session retirement is exercised separately without this stub.
    """
    token = auth_store.create_session(vid, mid, name, '', {})
    from flask import request
    def policy_identity():
        session = auth_store.get_session(request.cookies.get(app_module.SESSION_COOKIE_NAME, ''))
        is_token_admin = request.headers.get('X-Write-Token') == ADMIN_TOKEN
        user = {k: session[k] for k in ('mid', 'name', 'face')} if session else None
        return {'admin': is_token_admin or bool(session and auth_store.is_admin_mid(session['mid'])),
                'via': 'write_token' if is_token_admin else 'session' if session else None,
                'user': user, 'visitor_id': request.headers.get('X-Visitor-Id')}
    monkeypatch.setattr(app_module, '_current_identity', policy_identity)
    client.set_cookie(app_module.SESSION_COOKIE_NAME, token)
    return token


def _use_session(client, token, headers=None):
    """切换 Flask 测试客户端的 HttpOnly 会话 Cookie。"""
    client.set_cookie(app_module.SESSION_COOKIE_NAME, token)
    return headers or {}


def _add_admin(client, mid, name=''):
    """超管口令把 mid 加入管理员名单"""
    return client.post('/api/admin/accounts', json={'mid': mid, 'name': name},
                       headers={'X-Write-Token': ADMIN_TOKEN})


# ==================== 收藏隔离（归属 = B站账号 mid） ====================

class TestFavoritesIsolation:

    def test_no_login_cannot_favorite(self, client):
        """未登录（无会话 token）→ 写收藏被拒"""
        res = _add(client, {})
        assert res.status_code == 401
        assert '请先登录' in res.get_json()['message']

    def test_visitor_id_without_login_rejected(self, client):
        """只有浏览器身份 X-Visitor-Id、无 B站会话 → 写收藏被拒（归属已不再看浏览器）"""
        res = _add(client, {'X-Visitor-Id': VID_A})
        assert res.status_code == 401

    def test_logged_in_can_favorite(self, client, monkeypatch):
        """登录 B站账号后凭 HttpOnly 会话 Cookie 即可收藏"""
        token = _login(client, monkeypatch, mid=1)
        res = _add(client, _use_session(client, token))
        assert res.status_code == 200
        assert res.get_json()['success'] is True

    def test_users_isolated(self, client, monkeypatch):
        """两个不同 mid 各自只看到自己的收藏"""
        t1 = _login(client, monkeypatch, vid=VID_A, mid=1)
        _add(client, _use_session(client, t1), item={'keyword': 'A的梗'})
        t2 = _login(client, monkeypatch, vid=VID_B, mid=2)
        _add(client, _use_session(client, t2), item={'keyword': 'B的梗'})
        a = client.get('/api/favorites', headers=_use_session(client, t1)).get_json()['data']
        b = client.get('/api/favorites', headers=_use_session(client, t2)).get_json()['data']
        assert [f['keyword'] for f in a] == ['A的梗']
        assert [f['keyword'] for f in b] == ['B的梗']

    def test_user_cannot_delete_others(self, client, monkeypatch):
        """mid2 不能删除 mid1 的收藏（404 而非成功）"""
        t1 = _login(client, monkeypatch, vid=VID_A, mid=1)
        _add(client, _use_session(client, t1), item={'keyword': 'A的梗'})
        fav_id = client.get('/api/favorites', headers=_use_session(client, t1)).get_json()['data'][0]['id']
        t2 = _login(client, monkeypatch, vid=VID_B, mid=2)
        res = client.delete(f'/api/favorites/{fav_id}', headers=_use_session(client, t2))
        assert res.status_code == 404
        a = client.get('/api/favorites', headers=_use_session(client, t1)).get_json()['data']
        assert len(a) == 1

    def test_owner_can_delete_own(self, client, monkeypatch):
        """mid 可删除自己的收藏"""
        token = _login(client, monkeypatch, mid=1)
        _add(client, _use_session(client, token), item={'keyword': 'A的梗'})
        fav_id = client.get('/api/favorites', headers=_use_session(client, token)).get_json()['data'][0]['id']
        res = client.delete(f'/api/favorites/{fav_id}', headers=_use_session(client, token))
        assert res.status_code == 200
        a = client.get('/api/favorites', headers=_use_session(client, token)).get_json()['data']
        assert len(a) == 0

    def test_same_mid_cross_device(self, client, monkeypatch):
        """同一 mid 在不同浏览器登录 → 同一份收藏（跨设备持久，跟账号走）"""
        t1 = _login(client, monkeypatch, vid=VID_A, mid=1)
        _add(client, _use_session(client, t1), item={'keyword': '管理员的梗'})
        # 换一台设备（不同 visitor id），同一 B站账号再次登录
        t2 = _login(client, monkeypatch, vid=VID_B, mid=1)
        b = client.get('/api/favorites', headers=_use_session(client, t2)).get_json()['data']
        assert [f['keyword'] for f in b] == ['管理员的梗']

    def test_favorites_invisible_to_other_users(self, client, monkeypatch):
        """mid1 的收藏对 mid2 不可见"""
        t1 = _login(client, monkeypatch, vid=VID_A, mid=1)
        _add(client, _use_session(client, t1), item={'keyword': '管理员的梗'})
        t2 = _login(client, monkeypatch, vid=VID_B, mid=2)
        visitor = client.get('/api/favorites', headers=_use_session(client, t2)).get_json()['data']
        assert visitor == []


class TestLegacyClaim:

    def _seed_legacy_favorites(self, owners):
        """Seed imported favorites: None is unowned, admin is the old owner."""
        repository = database._require_state_repository()
        for i, owner in enumerate(owners):
            repository.add_favorite('meme', {'keyword': f'存量梗{i}'}, owner, 100 + i)

    def test_unowned_and_admin_claimed_by_admin_session(self, client, monkeypatch):
        """存量无主 + 旧'admin'归属收藏：首个 B站管理员会话访问时迁到其 mid"""
        self._seed_legacy_favorites(owners=[None, 'admin'])
        _add_admin(client, 1, name='站长')
        token = _login(client, monkeypatch, mid=1)

        # 管理员会话首次读：迁移并返回
        data = client.get('/api/favorites', headers=_use_session(client, token)).get_json()['data']
        assert sorted(f['keyword'] for f in data) == ['存量梗0', '存量梗1']

        repository = database._require_state_repository()
        with repository._sessions() as session:
            saved_owners = session.execute(select(favorites.c.owner).order_by(
                favorites.c.saved_at,
            )).scalars().all()
        assert saved_owners == ['1', '1']

        # 幂等：二次访问不重复
        again = client.get('/api/favorites', headers=_use_session(client, token)).get_json()['data']
        assert len(again) == 2

    def test_migration_not_triggered_by_plain_user(self, client, monkeypatch):
        """普通登录用户（不在管理员名单）不触发迁移，存量收藏保持无主"""
        self._seed_legacy_favorites(owners=[None])
        token = _login(client, monkeypatch, mid=99)  # 99 不在名单

        # 普通用户读到空（无主收藏不属于他），且不迁移
        data = client.get('/api/favorites', headers=_use_session(client, token)).get_json()['data']
        assert data == []
        repository = database._require_state_repository()
        with repository._sessions() as session:
            saved_owners = session.execute(select(favorites.c.owner)).scalars().all()
        assert saved_owners == ['']


# ==================== B站账号保护（身份登录开放 + 采集保护） ====================

class TestBiliAuthGuard:

    def test_qrcode_retired_for_visitor(self, client):
        response = client.get('/api/bili-auth/qrcode', headers={'X-Visitor-Id': VID_A})
        assert response.status_code == 410
        assert response.get_json()['success'] is False

    def test_qrcode_requires_visitor_id(self, client):
        res = client.get('/api/bili-auth/qrcode')
        assert res.status_code == 410

    def test_check_requires_registered_key(self, client):
        """未注册的 key → 404（防 key 伪造）"""
        res = client.get('/api/bili-auth/check?key=never-issued', headers={'X-Visitor-Id': VID_A})
        assert res.status_code == 410

    def test_collect_login_requires_admin(self, client):
        """采集账号登录入口对访客关闭（防扫码顶替爬虫 Cookie）"""
        res = client.get('/api/bili-auth/collect-login')
        assert res.status_code == 410

    def test_collect_check_requires_admin(self, client):
        res = client.get('/api/bili-auth/collect-check?key=x')
        assert res.status_code == 410

    def test_collect_logout_blocked_for_visitor(self, client):
        """采集登出是 POST：无管理员凭证被全局写口令拦截（401）"""
        res = client.post('/api/bili-auth/collect-logout')
        assert res.status_code == 401

    def test_user_info_requires_admin(self, client):
        """访客请求采集账号信息 → 403，站主昵称头像不泄露"""
        res = client.get('/api/bili-auth/user')
        assert res.status_code == 403
        assert 'data' not in res.get_json()

    def test_user_info_with_admin_token(self, client):
        res = client.get('/api/bili-auth/user', headers={'X-Write-Token': ADMIN_TOKEN})
        assert res.status_code == 200
        assert res.get_json()['data']['name'] == '站长'

    def test_logout_without_session_rejected(self, client):
        """会话登出：无会话 Cookie → 401（不做全局写口令要求）"""
        res = client.post('/api/bili-auth/logout')
        assert res.status_code == 401

    def test_retired_login_has_no_cookie_leak(self, client):
        response = client.get('/api/bili-auth/check?key=old', headers={'X-Visitor-Id': VID_A})
        assert response.status_code == 410
        assert 'cookies' not in response.get_json()
        assert 'SESSDATA' not in response.get_data(as_text=True)
        assert 'Set-Cookie' not in response.headers


# ==================== 管理员验证入口 ====================

class TestAdminVerify:

    def test_verify_with_correct_token(self, client):
        res = client.post('/api/auth/verify', headers={'X-Write-Token': ADMIN_TOKEN})
        assert res.status_code == 200
        assert res.get_json()['success'] is True

    def test_verify_with_wrong_token(self, client):
        res = client.post('/api/auth/verify', headers={'X-Write-Token': 'wrong-token'})
        assert res.status_code == 401

    def test_verify_without_token(self, client):
        res = client.post('/api/auth/verify')
        assert res.status_code == 401


# ==================== /auth/verify 失败限速 ====================

class TestVerifyRateLimit:

    def _fail(self, client, n, remote_addr=None):
        for i in range(n):
            headers = {'X-Write-Token': f'bad-token-{i}'}
            environ = {'REMOTE_ADDR': remote_addr} if remote_addr else None
            client.post('/api/auth/verify', headers=headers, environ_overrides=environ)

    def test_locked_after_5_failures(self, client):
        """15 分钟窗口内 5 次失败后，第 6 次错误口令直接 429（不再消耗比对）"""
        self._fail(client, 5)
        res = client.post('/api/auth/verify', headers={'X-Write-Token': 'another-guess'})
        assert res.status_code == 429
        assert '尝试次数过多' in res.get_json()['message']

    def test_correct_token_still_works_when_locked(self, client):
        """锁定期内正确口令仍放行——恶意访客无法把管理员锁死在自己 IP 上"""
        self._fail(client, 5)
        res = client.post('/api/auth/verify', headers={'X-Write-Token': ADMIN_TOKEN})
        assert res.status_code == 200

    def test_success_resets_counter(self, client):
        """登录成功即清零失败计数（相邻的误输不会累积到下次登录）"""
        self._fail(client, 4)
        assert client.post('/api/auth/verify', headers={'X-Write-Token': ADMIN_TOKEN}).status_code == 200
        res = client.post('/api/auth/verify', headers={'X-Write-Token': 'one-more-bad'})
        assert res.status_code == 401  # 清零后 1 次失败不触发锁定
        assert client.post('/api/auth/verify', headers={'X-Write-Token': ADMIN_TOKEN}).status_code == 200

    def test_rate_limit_isolated_per_ip(self, client):
        """限速按 Werkzeug 已规范化的客户端 IP 隔离。"""
        self._fail(client, 5, remote_addr='9.9.9.9')
        other = client.post('/api/auth/verify', headers={'X-Write-Token': 'bad'},
                            environ_overrides={'REMOTE_ADDR': '8.8.8.8'})
        assert other.status_code == 401  # 其他 IP 不受影响
        ok = client.post('/api/auth/verify', headers={'X-Write-Token': ADMIN_TOKEN},
                         environ_overrides={'REMOTE_ADDR': '8.8.8.8'})
        assert ok.status_code == 200
