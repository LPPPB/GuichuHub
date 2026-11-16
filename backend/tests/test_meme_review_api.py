import pytest


@pytest.mark.parametrize('method,path', [('GET','overview'),('PUT','draft'),('POST','preview'),
    ('POST','publish'),('GET','dictionary'),('GET','adjustments'),('GET','cleanup-preview'),
    ('POST','undo-preview'),('POST','undo')])
def test_review_endpoints_require_admin(client, method, path):
    response = client.open('/api/admin/meme-review/'+path, method=method, json={})
    assert response.status_code in (401, 403)


def test_admin_can_preview_publish_and_save_empty_seeds_with_cas(client, monkeypatch):
    import app
    monkeypatch.setattr(app, 'WRITE_TOKEN', 'review-test')
    headers = {'X-Write-Token': 'review-test'}
    preview = client.post('/api/admin/meme-review/preview', headers=headers, json={'proposal': {}})
    assert preview.status_code == 200
    response = client.post('/api/admin/meme-review/publish', headers=headers,
        json={'proposal': {}, 'token': preview.json['data']['token'], 'request_id': 'api-test'})
    assert response.status_code == 200
    snapshot = client.get('/api/config/meme-seed-words', headers=headers).json['data']
    assert client.put('/api/config/meme-seed-words', headers=headers,
        json={'words': [], 'version': snapshot['version']}).status_code == 200
    assert client.get('/api/config/meme-seed-words', headers=headers).json['data']['words'] == []
    assert client.put('/api/config/meme-seed-words', headers=headers,
        json={'words': ['test'], 'version': snapshot['version']}).status_code == 409
    assert client.put('/api/config/meme-seed-words', headers=headers, json={'words': []}).status_code == 428
