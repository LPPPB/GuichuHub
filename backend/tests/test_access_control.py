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

import json

import pytest

import storage.auth_store as auth_store
import storage.database as database
import app as app_module


ADMIN_TOKEN = 'test-admin-token-0123456789abcdef'
QR_KEY = 'access-ctrl-qr-key'
VID_A = '11111111-1111-1111-1111-111111111111'
VID_B = '22222222-2222-2222-2222-222222222222'


@pytest.fixture
def client(monkeypatch, tmp_path):
    """独立临时数据文件 + 已知管理员口令的 Flask test client"""
    monkeypatch.setattr(database, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(auth_store, 'AUTH_DB_PATH', str(tmp_path / 'auth.db'))
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
    monkeypatch.setattr(app_module, 'bili_logout', lambda: True)

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
    """完整身份登录流程（qrcode → check），返回 session_token（浏览器只拿 token）"""
    monkeypatch.setattr(app_module, 'check_login_status',
                        lambda key, save=True: {
                            'success': True, 'status': 'success', 'message': '登录成功',
                            'user_mid': mid,
                            'cookies': {'SESSDATA': 'S', 'bili_jct': 'J', 'DedeUserID': str(mid)},
                        })
    monkeypatch.setattr(app_module, 'get_user_info_with_cookie',
                        lambda cs: {'mid': mid, 'name': name, 'face': ''})
    res = client.get('/api/bili-auth/qrcode', headers={'X-Visitor-Id': vid})
    assert res.status_code == 200, '二维码生成对访客开放'
    res = client.get(f'/api/bili-auth/check?key={QR_KEY}', headers={'X-Visitor-Id': vid})
    body = res.get_json()
    assert res.status_code == 200 and body.get('success'), f'登录失败：{body}'
    return body['session_token']


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
        """登录 B站账号后凭 X-Session-Token 即可收藏"""
        token = _login(client, monkeypatch, mid=1)
        res = _add(client, {'X-Session-Token': token})
        assert res.status_code == 200
        assert res.get_json()['success'] is True

    def test_users_isolated(self, client, monkeypatch):
        """两个不同 mid 各自只看到自己的收藏"""
        t1 = _login(client, monkeypatch, vid=VID_A, mid=1)
        _add(client, {'X-Session-Token': t1}, item={'keyword': 'A的梗'})
        t2 = _login(client, monkeypatch, vid=VID_B, mid=2)
        _add(client, {'X-Session-Token': t2}, item={'keyword': 'B的梗'})
        a = client.get('/api/favorites', headers={'X-Session-Token': t1}).get_json()['data']
        b = client.get('/api/favorites', headers={'X-Session-Token': t2}).get_json()['data']
        assert [f['keyword'] for f in a] == ['A的梗']
        assert [f['keyword'] for f in b] == ['B的梗']

    def test_user_cannot_delete_others(self, client, monkeypatch):
        """mid2 不能删除 mid1 的收藏（404 而非成功）"""
        t1 = _login(client, monkeypatch, vid=VID_A, mid=1)
        _add(client, {'X-Session-Token': t1}, item={'keyword': 'A的梗'})
        fav_id = client.get('/api/favorites', headers={'X-Session-Token': t1}).get_json()['data'][0]['id']
        t2 = _login(client, monkeypatch, vid=VID_B, mid=2)
        res = client.delete(f'/api/favorites/{fav_id}', headers={'X-Session-Token': t2})
        assert res.status_code == 404
        a = client.get('/api/favorites', headers={'X-Session-Token': t1}).get_json()['data']
        assert len(a) == 1

    def test_owner_can_delete_own(self, client, monkeypatch):
        """mid 可删除自己的收藏"""
        token = _login(client, monkeypatch, mid=1)
        _add(client, {'X-Session-Token': token}, item={'keyword': 'A的梗'})
        fav_id = client.get('/api/favorites', headers={'X-Session-Token': token}).get_json()['data'][0]['id']
        res = client.delete(f'/api/favorites/{fav_id}', headers={'X-Session-Token': token})
        assert res.status_code == 200
        a = client.get('/api/favorites', headers={'X-Session-Token': token}).get_json()['data']
        assert len(a) == 0

    def test_same_mid_cross_device(self, client, monkeypatch):
        """同一 mid 在不同浏览器登录 → 同一份收藏（跨设备持久，跟账号走）"""
        t1 = _login(client, monkeypatch, vid=VID_A, mid=1)
        _add(client, {'X-Session-Token': t1}, item={'keyword': '管理员的梗'})
        # 换一台设备（不同 visitor id），同一 B站账号再次登录
        t2 = _login(client, monkeypatch, vid=VID_B, mid=1)
        b = client.get('/api/favorites', headers={'X-Session-Token': t2}).get_json()['data']
        assert [f['keyword'] for f in b] == ['管理员的梗']

    def test_favorites_invisible_to_other_users(self, client, monkeypatch):
        """mid1 的收藏对 mid2 不可见"""
        t1 = _login(client, monkeypatch, vid=VID_A, mid=1)
        _add(client, {'X-Session-Token': t1}, item={'keyword': '管理员的梗'})
        t2 = _login(client, monkeypatch, vid=VID_B, mid=2)
        visitor = client.get('/api/favorites', headers={'X-Session-Token': t2}).get_json()['data']
        assert visitor == []


class TestLegacyClaim:

    def _legacy_db(self, tmp_path, owners):
        """写入存量收藏库：owners 元素为 None（无主）或 'admin'（旧写口令归属）"""
        db_file = tmp_path / 'inspiration_db.json'
        favs = []
        for i, owner in enumerate(owners):
            fav = {'id': f'meme_{i}', 'type': 'meme', 'keyword': f'存量梗{i}',
                   'tags': [], 'notes': ''}
            if owner is not None:
                fav['owner'] = owner
            favs.append(fav)
        legacy = {
            'hot_memes': [], 'hot_songs': [], 'hot_videos': [], 'danmaku_words': [],
            'comments_gold': [], 'favorites': favs, 'last_updated': None,
        }
        db_file.write_text(json.dumps(legacy, ensure_ascii=False), encoding='utf-8')
        return db_file

    def test_unowned_and_admin_claimed_by_admin_session(self, client, monkeypatch, tmp_path):
        """存量无主 + 旧'admin'归属收藏：首个 B站管理员会话访问时迁到其 mid"""
        db_file = self._legacy_db(tmp_path, owners=[None, 'admin'])
        _add_admin(client, 1, name='站长')
        token = _login(client, monkeypatch, mid=1)

        # 管理员会话首次读：迁移并返回
        data = client.get('/api/favorites', headers={'X-Session-Token': token}).get_json()['data']
        assert sorted(f['keyword'] for f in data) == ['存量梗0', '存量梗1']

        # 落盘：owner 全部迁到 str(mid)
        saved = json.loads(db_file.read_text(encoding='utf-8'))
        assert [f['owner'] for f in saved['favorites']] == ['1', '1']

        # 幂等：二次访问不重复
        again = client.get('/api/favorites', headers={'X-Session-Token': token}).get_json()['data']
        assert len(again) == 2

    def test_migration_not_triggered_by_plain_user(self, client, monkeypatch, tmp_path):
        """普通登录用户（不在管理员名单）不触发迁移，存量收藏保持无主"""
        db_file = self._legacy_db(tmp_path, owners=[None])
        token = _login(client, monkeypatch, mid=99)  # 99 不在名单

        # 普通用户读到空（无主收藏不属于他），且不迁移
        data = client.get('/api/favorites', headers={'X-Session-Token': token}).get_json()['data']
        assert data == []
        saved = json.loads(db_file.read_text(encoding='utf-8'))
        assert 'owner' not in saved['favorites'][0]


# ==================== B站账号保护（身份登录开放 + 采集保护） ====================

class TestBiliAuthGuard:

    def test_qrcode_open_to_visitor(self, client):
        """身份登录二维码对访客开放（登录自己的B站账号，不碰采集 Cookie）"""
        res = client.get('/api/bili-auth/qrcode', headers={'X-Visitor-Id': VID_A})
        assert res.status_code == 200
        assert res.get_json()['success'] is True

    def test_qrcode_requires_visitor_id(self, client):
        res = client.get('/api/bili-auth/qrcode')
        assert res.status_code == 401

    def test_check_requires_registered_key(self, client):
        """未注册的 key → 404（防 key 伪造）"""
        res = client.get('/api/bili-auth/check?key=never-issued', headers={'X-Visitor-Id': VID_A})
        assert res.status_code == 404

    def test_collect_login_requires_admin(self, client):
        """采集账号登录入口对访客关闭（防扫码顶替爬虫 Cookie）"""
        res = client.get('/api/bili-auth/collect-login')
        assert res.status_code == 403

    def test_collect_check_requires_admin(self, client):
        res = client.get('/api/bili-auth/collect-check?key=x')
        assert res.status_code == 403

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
        """会话登出：无 X-Session-Token → 401（不做全局写口令要求）"""
        res = client.post('/api/bili-auth/logout')
        assert res.status_code == 401

    def test_login_success_no_cookie_leak(self, client):
        """凭证只留服务器：登录成功响应不得携带 SESSDATA/bili_jct，只发会话 token"""
        client.get('/api/bili-auth/qrcode', headers={'X-Visitor-Id': VID_A})
        res = client.get(f'/api/bili-auth/check?key={QR_KEY}', headers={'X-Visitor-Id': VID_A})
        assert res.status_code == 200
        body = res.get_json()
        assert 'cookies' not in body, 'SESSDATA/bili_jct 不得回传浏览器'
        assert 'SESSDATA' not in str(body)
        assert body['success'] is True and body['status'] == 'success'
        assert body.get('session_token'), '应签发会话 token'


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

    def _fail(self, client, n, xff=None):
        for i in range(n):
            headers = {'X-Write-Token': f'bad-token-{i}'}
            if xff:
                headers['X-Forwarded-For'] = xff
            client.post('/api/auth/verify', headers=headers)

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
        """限速按客户端 IP 隔离（部署在反代后按 X-Forwarded-For 首段取真实 IP）"""
        self._fail(client, 5, xff='9.9.9.9')
        other = client.post('/api/auth/verify', headers={'X-Write-Token': 'bad', 'X-Forwarded-For': '8.8.8.8'})
        assert other.status_code == 401  # 其他 IP 不受影响
        ok = client.post('/api/auth/verify', headers={'X-Write-Token': ADMIN_TOKEN, 'X-Forwarded-For': '8.8.8.8'})
        assert ok.status_code == 200
