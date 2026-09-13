"""UP追踪申请（访客提交 / 站长审核）— 公网多用户改造 TDD 用例。

方案C（2026-08-28 与用户确认）：
  - "互粉UP主动态"改为"UP主动态"：现有138位原样保留为初始追踪池
  - 访客提交：昵称搜索（后端代理B站搜索，关键词缓存5min + 每访客10次/分）或粘贴链接/mid
  - 限速：每访客每日3个；全局pending≤50；追踪池软上限300
  - 审核：通过=入池+即时落地（ups登记 + up_obs并入最新批次）+后台日历回填；
    同mid其他pending自动superseded；拒绝需理由（访客可见）
  - 撤回：仅本人pending可撤
  - GET /api/up-trends/list（互粉同步）加admin守卫（访客不得触发cookie爬取/看账号信息）
"""

import json
import time

import pytest

import storage.tracked_ups as tracked_ups
import jobs.calendar_jobs as calendar_jobs
import app as app_module


ADMIN_TOKEN = 'test-admin-token-0123456789abcdef'
VID_A = '11111111-1111-1111-1111-111111111111'
VID_B = '22222222-2222-2222-2222-222222222222'


def test_public_roster_only_exposes_active_public_fields(client):
    tracked_ups.save_tracked_list([
        {'mid': 101, 'name': 'A', 'enabled': True, 'secret': 'private'},
        {'mid': 102, 'name': 'B', 'enabled': False},
    ])
    data = client.get('/api/up-trends/roster').get_json()['data']
    assert data['total'] == 1
    assert set(data['ups'][0]) == {'mid', 'name', 'face', 'added_at'}


def test_stop_request_requires_reason_and_admin_and_preserves_record(client, monkeypatch):
    tracked_ups.save_tracked_list([{'mid': 101, 'name': 'A', 'enabled': True}])
    monkeypatch.setattr(app_module, 'get_up_info_by_mid', lambda mid: pytest.fail('Stop must use local snapshot'))
    body = {'mid': 101, 'request_type': 'remove'}
    assert client.post('/api/up-trends/requests', json=body, headers={'X-Visitor-Id': VID_A}).status_code == 400
    body['reason'] = '不再适合当前观测范围'
    req = client.post('/api/up-trends/requests', json=body, headers={'X-Visitor-Id': VID_A}).get_json()['data']
    url = f"/api/up-trends/requests/{req['id']}/review"
    assert client.post(url, json={'action': 'approve'}).status_code == 401
    result, err = tracked_ups.review_up_request(req['id'], 'approve')
    assert err is None
    assert result['removed_from_pool'] and not result['added_to_pool']
    assert tracked_ups.load_tracked_list()['ups'][0]['enabled'] is False
    assert client.get('/api/up-trends/roster').get_json()['data']['total'] == 0
    assert tracked_ups.review_up_request(req['id'], 'approve')[1] == 'NOT_FOUND'


def test_reenable_existing_up_does_not_duplicate(client):
    tracked_ups.save_tracked_list([{'mid': 101, 'name': 'A', 'enabled': False}])
    req, err = tracked_ups.add_up_request(101, {'name': 'A'}, '', VID_A)
    assert err is None
    result, err = tracked_ups.review_up_request(req['id'], 'approve')
    assert err is None and result['added_to_pool']
    pool = tracked_ups.load_tracked_list()['ups']
    assert len(pool) == 1 and pool[0]['enabled']


def test_stop_untracked_and_invalid_type_rejected(client):
    assert tracked_ups.add_up_request(123, {}, '原因', VID_A, 'remove')[1] == 'NOT_TRACKED'
    assert client.post('/api/up-trends/requests', json={'mid': 123, 'request_type': 'invalid'}, headers={'X-Visitor-Id': VID_A}).status_code == 400


def test_management_roster_requires_admin(client):
    assert client.get('/api/up-trends/roster/manage').status_code in (401, 403)
    tracked_ups.save_tracked_list([{'mid': 101, 'enabled': False}])
    response = client.get('/api/up-trends/roster/manage', headers={'X-Write-Token': ADMIN_TOKEN})
    assert response.status_code == 200
    assert response.get_json()['data']['unchanged'][0]['enabled'] is False


@pytest.fixture
def client(monkeypatch, tmp_path):
    """临时 tracked_ups.json + 已知管理员口令 + B站采集层全 mock（不打真实接口）"""
    monkeypatch.setattr(tracked_ups, 'TRACKED_FILE', str(tmp_path / 'tracked_ups.json'))
    monkeypatch.setattr(app_module, 'WRITE_TOKEN', ADMIN_TOKEN)
    monkeypatch.setattr(app_module, 'get_up_info_by_mid', lambda mid: {
        'mid': mid, 'name': f'UP{mid}', 'face': f'https://i.example/{mid}.jpg', 'sign': '签名'})
    monkeypatch.setattr(app_module, 'get_up_relation_stat', lambda mid: {'follower': 1000, 'following': 50})
    monkeypatch.setattr(app_module, 'search_up_users', lambda kw: [{
        'mid': 101, 'name': f'{kw}的UP', 'fans': 500, 'sign': 's', 'face': 'https://i.example/101.jpg'}])
    # 审核后即时落地 mock（个别用例内再细化为记录调用的版本）
    monkeypatch.setattr(app_module, 'upsert_up_obs', lambda **kw: 1)
    monkeypatch.setattr(app_module, 'register_up', lambda *a, **kw: None)
    monkeypatch.setattr(app_module, 'get_latest_batch_ts', lambda: 1700000000)
    monkeypatch.setattr(calendar_jobs, 'enqueue_baseline_jobs', lambda mids, **kwargs: [])

    # 搜索限速/缓存状态隔离
    for attr in ('_UP_SEARCH_RATE', '_UP_SEARCH_CACHE'):
        if hasattr(app_module, attr):
            getattr(app_module, attr).clear()

    app_module.app.config['TESTING'] = True
    with app_module.app.test_client() as c:
        yield c


def _submit(c, vid, mid, reason=''):
    return c.post('/api/up-trends/requests',
                  json={'mid': mid, 'reason': reason},
                  headers={'X-Visitor-Id': vid})


def _wait_bg(calls, timeout=2.0):
    """等待后台线程产生调用记录（日历回填线程）"""
    deadline = time.time() + timeout
    while time.time() < deadline and not calls:
        time.sleep(0.02)


# ==================== 访客提交 ====================

class TestSubmitRequest:

    def test_submit_ok(self, client):
        res = _submit(client, VID_A, 101, '想看他')
        assert res.status_code == 200
        body = res.get_json()
        assert body['success'] is True
        req = body['data']
        assert req['mid'] == 101 and req['status'] == 'pending'
        assert req['up']['name'] == 'UP101' and req['up']['fans'] == 1000
        assert req['visitor_id'] == VID_A
        assert req['reason'] == '想看他'

    def test_submit_reason_optional(self, client):
        res = _submit(client, VID_B, 102)
        assert res.status_code == 200
        assert res.get_json()['data']['reason'] == ''

    def test_submit_requires_visitor_id(self, client):
        res = client.post('/api/up-trends/requests', json={'mid': 101})
        assert res.status_code == 401

    def test_submit_invalid_mid(self, client):
        res = _submit(client, VID_A, 'abc')
        assert res.status_code == 400

    def test_submit_up_not_found(self, client, monkeypatch):
        monkeypatch.setattr(app_module, 'get_up_info_by_mid', lambda mid: None)
        res = _submit(client, VID_A, 999)
        assert res.status_code == 502

    def test_submit_already_tracked(self, client):
        tracked_ups.save_tracked_list([{'mid': 101, 'name': 'UP101', 'enabled': True}])
        res = _submit(client, VID_A, 101)
        assert res.status_code == 409
        assert res.get_json()['code'] == 'ALREADY_TRACKED'

    def test_submit_duplicate_pending(self, client):
        _submit(client, VID_A, 101)
        res = _submit(client, VID_B, 101)
        assert res.status_code == 409
        assert res.get_json()['code'] == 'DUPLICATE'

    def test_submit_daily_limit(self, client):
        for mid in (101, 102, 103):
            assert _submit(client, VID_A, mid).status_code == 200
        res = _submit(client, VID_A, 104)
        assert res.status_code == 429
        assert res.get_json()['code'] == 'DAILY_LIMIT'
        assert _submit(client, VID_B, 105).status_code == 200

    def test_submit_pool_full(self, client):
        ups = [{'mid': 1000 + i, 'name': f'U{i}'} for i in range(tracked_ups.TRACK_POOL_LIMIT)]
        tracked_ups.save_tracked_list(ups)
        res = _submit(client, VID_A, 555001)
        assert res.status_code == 409
        assert res.get_json()['code'] == 'POOL_FULL'

    def test_submit_queue_full(self, client):
        reqs = {'pending': [{'id': f'r{i}', 'mid': 2000 + i, 'up': {}, 'reason': '',
                             'visitor_id': f'other-{i}', 'submitted_at': 1, 'status': 'pending'}
                            for i in range(tracked_ups.REQUESTS_PENDING_LIMIT)],
                'processed': []}
        with open(tracked_ups.TRACKED_FILE, 'w', encoding='utf-8') as f:
            json.dump({'ups': [], 'requests': reqs}, f, ensure_ascii=False)
        res = _submit(client, VID_A, 101)
        assert res.status_code == 429
        assert res.get_json()['code'] == 'QUEUE_FULL'


# ==================== 我的申请 ====================

class TestMyRequests:

    def test_mine_isolated(self, client):
        _submit(client, VID_A, 101)
        _submit(client, VID_B, 102)
        a = client.get('/api/up-trends/requests/mine', headers={'X-Visitor-Id': VID_A}).get_json()['data']
        assert [r['mid'] for r in a['pending']] == [101]
        b = client.get('/api/up-trends/requests/mine', headers={'X-Visitor-Id': VID_B}).get_json()['data']
        assert [r['mid'] for r in b['pending']] == [102]

    def test_mine_requires_visitor_id(self, client):
        res = client.get('/api/up-trends/requests/mine')
        assert res.status_code == 401


# ==================== 撤回 ====================

class TestWithdraw:

    def test_withdraw_own_pending(self, client):
        rid = _submit(client, VID_A, 101).get_json()['data']['id']
        res = client.post(f'/api/up-trends/requests/{rid}/withdraw', headers={'X-Visitor-Id': VID_A})
        assert res.status_code == 200
        mine = client.get('/api/up-trends/requests/mine', headers={'X-Visitor-Id': VID_A}).get_json()['data']
        assert mine['pending'] == []
        assert mine['processed'][0]['status'] == 'withdrawn'
        # 撤回后可重新提交（不再占用 DUPLICATE）
        assert _submit(client, VID_A, 101).status_code == 200

    def test_withdraw_not_owner(self, client):
        rid = _submit(client, VID_A, 101).get_json()['data']['id']
        res = client.post(f'/api/up-trends/requests/{rid}/withdraw', headers={'X-Visitor-Id': VID_B})
        assert res.status_code == 403

    def test_withdraw_after_reviewed(self, client):
        rid = _submit(client, VID_A, 101).get_json()['data']['id']
        client.post(f'/api/up-trends/requests/{rid}/review', json={'action': 'approve'},
                    headers={'X-Write-Token': ADMIN_TOKEN})
        res = client.post(f'/api/up-trends/requests/{rid}/withdraw', headers={'X-Visitor-Id': VID_A})
        assert res.status_code == 404


# ==================== 站长审核 ====================

class TestReview:

    def _pending_id(self, client, vid, mid):
        return _submit(client, vid, mid).get_json()['data']['id']

    def test_review_requires_admin(self, client):
        rid = self._pending_id(client, VID_A, 101)
        res = client.post(f'/api/up-trends/requests/{rid}/review', json={'action': 'approve'})
        assert res.status_code == 401
        res2 = client.post(f'/api/up-trends/requests/{rid}/review', json={'action': 'approve'},
                           headers={'X-Write-Token': 'wrong'})
        assert res2.status_code == 401

    def test_approve_adds_to_pool_and_immediate_writes(self, client, monkeypatch):
        rid = self._pending_id(client, VID_A, 101)
        obs_calls, ups_calls, bf_calls = [], [], []
        monkeypatch.setattr(app_module, 'upsert_up_obs', lambda **kw: obs_calls.append(kw) or 1)
        monkeypatch.setattr(app_module, 'register_up', lambda *a, **kw: ups_calls.append(a) or None)
        monkeypatch.setattr(
            calendar_jobs, 'enqueue_baseline_jobs',
            lambda mids, **kwargs: bf_calls.extend(mids) or [],
        )

        res = client.post(f'/api/up-trends/requests/{rid}/review',
                          json={'action': 'approve'}, headers={'X-Write-Token': ADMIN_TOKEN})
        assert res.status_code == 200
        # 名单入池（enabled + added_at，供日历增量回填识别新UP）
        tracked = tracked_ups.load_tracked_list()
        entry = [u for u in tracked['ups'] if u['mid'] == 101][0]
        assert entry['enabled'] is True and entry['added_at'] > 0
        # 即时落地：up_obs 并入最新批次（不新开批次）+ ups 表登记 + 日历回填
        assert len(obs_calls) == 1
        assert obs_calls[0]['ts'] == 1700000000
        assert [u['mid'] for u in obs_calls[0]['up_list']] == [101]
        assert len(ups_calls) == 1 and ups_calls[0][0] == 101
        assert bf_calls == [101]

    def test_approve_supersedes_same_mid_pending(self, client):
        reqs = {'pending': [
            {'id': 'req_a', 'mid': 101, 'up': {'mid': 101, 'name': 'UP101'}, 'reason': '',
             'visitor_id': VID_A, 'submitted_at': 1, 'status': 'pending'},
            {'id': 'req_b', 'mid': 101, 'up': {'mid': 101, 'name': 'UP101'}, 'reason': '',
             'visitor_id': VID_B, 'submitted_at': 2, 'status': 'pending'},
        ], 'processed': []}
        with open(tracked_ups.TRACKED_FILE, 'w', encoding='utf-8') as f:
            json.dump({'ups': [], 'requests': reqs}, f, ensure_ascii=False)
        res = client.post('/api/up-trends/requests/req_a/review', json={'action': 'approve'},
                          headers={'X-Write-Token': ADMIN_TOKEN})
        assert res.status_code == 200
        data = client.get('/api/up-trends/requests', headers={'X-Write-Token': ADMIN_TOKEN}).get_json()['data']
        assert data['pending'] == []
        statuses = {r['id']: r['status'] for r in data['processed']}
        assert statuses['req_a'] == 'approved'
        assert statuses['req_b'] == 'superseded'

    def test_approve_idempotent_when_in_pool(self, client):
        rid = self._pending_id(client, VID_A, 101)
        # 审核前 UP 已被站长手动导入名单
        tracked_ups.save_tracked_list([{'mid': 101, 'name': '手动导入的UP101'}])
        res = client.post(f'/api/up-trends/requests/{rid}/review', json={'action': 'approve'},
                          headers={'X-Write-Token': ADMIN_TOKEN})
        assert res.status_code == 200
        assert res.get_json()['data']['added_to_pool'] is False
        tracked = tracked_ups.load_tracked_list()
        assert len([u for u in tracked['ups'] if u['mid'] == 101]) == 1

    def test_reject_requires_reason(self, client):
        rid = self._pending_id(client, VID_A, 101)
        res = client.post(f'/api/up-trends/requests/{rid}/review', json={'action': 'reject'},
                          headers={'X-Write-Token': ADMIN_TOKEN})
        assert res.status_code == 400

    def test_reject_reason_visible_to_visitor(self, client):
        rid = self._pending_id(client, VID_A, 101)
        res = client.post(f'/api/up-trends/requests/{rid}/review',
                          json={'action': 'reject', 'reason': '非鬼畜区UP'},
                          headers={'X-Write-Token': ADMIN_TOKEN})
        assert res.status_code == 200
        mine = client.get('/api/up-trends/requests/mine', headers={'X-Visitor-Id': VID_A}).get_json()['data']
        assert mine['pending'] == []
        assert mine['processed'][0]['status'] == 'rejected'
        assert mine['processed'][0]['reject_reason'] == '非鬼畜区UP'

    def test_review_double_review_conflict(self, client):
        rid = self._pending_id(client, VID_A, 101)
        h = {'X-Write-Token': ADMIN_TOKEN}
        first = client.post(f'/api/up-trends/requests/{rid}/review', json={'action': 'approve'}, headers=h)
        assert first.status_code == 200
        res = client.post(f'/api/up-trends/requests/{rid}/review', json={'action': 'approve'}, headers=h)
        assert res.status_code == 409

    def test_review_not_found(self, client):
        res = client.post('/api/up-trends/requests/req_none/review', json={'action': 'approve'},
                          headers={'X-Write-Token': ADMIN_TOKEN})
        assert res.status_code == 404

    def test_admin_list_guard(self, client):
        assert client.get('/api/up-trends/requests').status_code == 403
        assert client.get('/api/up-trends/requests', headers={'X-Visitor-Id': VID_A}).status_code == 403
        assert client.get('/api/up-trends/requests', headers={'X-Write-Token': ADMIN_TOKEN}).status_code == 200

    def test_admin_list_shows_all(self, client):
        _submit(client, VID_A, 101)
        _submit(client, VID_B, 102)
        data = client.get('/api/up-trends/requests', headers={'X-Write-Token': ADMIN_TOKEN}).get_json()['data']
        assert {r['mid'] for r in data['pending']} == {101, 102}


# ==================== 搜索代理 ====================

class TestSearchProxy:

    def test_search_ok(self, client):
        res = client.get('/api/up-trends/search?keyword=老笛', headers={'X-Visitor-Id': VID_A})
        assert res.status_code == 200
        body = res.get_json()
        assert body['success'] is True
        assert body['data'][0]['mid'] == 101
        assert set(body['data'][0].keys()) == {'mid', 'name', 'fans', 'sign', 'face'}

    def test_search_keyword_cache(self, client, monkeypatch):
        calls = []
        monkeypatch.setattr(app_module, 'search_up_users', lambda kw: calls.append(kw) or [
            {'mid': 1, 'name': 'x', 'fans': 0, 'sign': '', 'face': ''}])
        for _ in range(3):
            client.get('/api/up-trends/search?keyword=同词', headers={'X-Visitor-Id': VID_A})
        assert calls == ['同词']

    def test_search_rate_limited(self, client):
        for i in range(10):
            assert client.get(f'/api/up-trends/search?keyword=词{i}',
                              headers={'X-Visitor-Id': VID_A}).status_code == 200
        res = client.get('/api/up-trends/search?keyword=再搜', headers={'X-Visitor-Id': VID_A})
        assert res.status_code == 429
        assert client.get('/api/up-trends/search?keyword=词',
                          headers={'X-Visitor-Id': VID_B}).status_code == 200

    def test_search_degraded_on_failure(self, client, monkeypatch):
        monkeypatch.setattr(app_module, 'search_up_users', lambda kw: None)
        res = client.get('/api/up-trends/search?keyword=失败', headers={'X-Visitor-Id': VID_A})
        assert res.status_code == 503
        assert '粘贴' in res.get_json()['message']

    def test_search_requires_keyword_and_visitor(self, client):
        assert client.get('/api/up-trends/search', headers={'X-Visitor-Id': VID_A}).status_code == 400
        assert client.get('/api/up-trends/search?keyword=x').status_code == 401


# ==================== 互粉同步守卫 ====================

class TestMutualListGuard:

    def test_up_trends_list_requires_admin(self, client):
        assert client.get('/api/up-trends/list').status_code == 403
        assert client.get('/api/up-trends/list', headers={'X-Visitor-Id': VID_A}).status_code == 403
