"""发布日历 API 鉴权、任务协议、年份日期与名单基线回填测试。"""
import pytest

import app as app_module
import jobs.calendar_jobs as calendar_jobs
import storage.db as db
import storage.tracked_ups as tracked_ups

ADMIN_TOKEN = 'calendar-test-admin-token'


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(db, 'DB_PATH', str(tmp_path / 'calendar.db'))
    monkeypatch.setattr(db, 'DATA_DIR', str(tmp_path))
    db._thread_local.conn = None
    db.get_conn()
    monkeypatch.setattr(tracked_ups, 'TRACKED_FILE', str(tmp_path / 'tracked_ups.json'))
    monkeypatch.setattr(app_module, 'WRITE_TOKEN', ADMIN_TOKEN)
    monkeypatch.setattr(calendar_jobs, 'ensure_calendar_worker', lambda: None)
    app_module.app.config['TESTING'] = True
    with app_module.app.test_client() as test_client:
        yield test_client
    db._thread_local.conn = None


def _admin_headers():
    return {'X-Write-Token': ADMIN_TOKEN}


def test_backfill_requires_admin_and_returns_persistent_job(client):
    tracked_ups.save_tracked_list([{'mid': 1, 'name': 'A', 'enabled': True}])
    denied = client.post('/api/up-trends/calendar/backfill', json={'mode': 'recent', 'days': 7})
    assert denied.status_code == 401

    created = client.post(
        '/api/up-trends/calendar/backfill', json={'mode': 'recent', 'days': 7},
        headers=_admin_headers(),
    )
    body = created.get_json()
    assert created.status_code == 202 and body['success'] and body['job_id']

    assert client.get(f"/api/up-trends/calendar/jobs/{body['job_id']}").status_code == 403
    status = client.get(
        f"/api/up-trends/calendar/jobs/{body['job_id']}", headers=_admin_headers(),
    )
    assert status.status_code == 200
    assert status.get_json()['data']['status'] == 'queued'


def test_backfill_rejects_unbounded_manual_window(client):
    res = client.post(
        '/api/up-trends/calendar/backfill', json={'mode': 'recent', 'days': 3650},
        headers=_admin_headers(),
    )
    assert res.status_code == 400


def test_calendar_year_and_day_validation(client):
    assert client.get('/api/up-trends/calendar?year=1900').status_code == 400
    assert client.get('/api/up-trends/calendar/day?date=09-05').status_code == 400
    assert client.get('/api/up-trends/calendar/day?date=2026-02-30').status_code == 400
    ok = client.get('/api/up-trends/calendar?year=2026')
    assert ok.status_code == 200 and ok.get_json()['meta']['year'] == 2026


def test_save_detects_new_and_reenabled_up_without_frontend_added_at(client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        calendar_jobs, 'enqueue_baseline_jobs',
        lambda mids, **kwargs: calls.append(list(mids)) or [{'id': 'baseline'}],
    )
    payload = {'ups': [{'mid': 123, 'name': 'A', 'enabled': True}]}
    first = client.post('/api/up-trends/list', json=payload, headers=_admin_headers())
    assert first.status_code == 200 and calls == [[123]]
    saved = tracked_ups.load_tracked_list()['ups'][0]
    assert saved['added_at'] > 0

    client.post('/api/up-trends/list', json=payload, headers=_admin_headers())
    assert calls == [[123]], '未变化的名单不能重复创建基线任务'
    client.post('/api/up-trends/list', json={
        'ups': [{'mid': 123, 'name': 'A', 'enabled': False}],
    }, headers=_admin_headers())
    client.post('/api/up-trends/list', json=payload, headers=_admin_headers())
    assert calls == [[123], [123]], '重新启用应补一次基线'


def test_import_creates_baseline_for_new_enabled_ups(client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        calendar_jobs, 'enqueue_baseline_jobs',
        lambda mids, **kwargs: calls.append(list(mids)) or [{'id': 'import-job'}],
    )
    res = client.post('/api/up-trends/list/import', json={
        'ups': [{'mid': 88, 'name': '导入UP', 'enabled': True}],
    }, headers=_admin_headers())
    assert res.status_code == 200
    assert calls == [[88]]
    assert res.get_json()['calendar_job_ids'] == ['import-job']
