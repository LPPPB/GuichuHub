from tests.test_public_pages import source

def test_readonly_export_does_not_depend_on_request_identity(monkeypatch):
    from types import SimpleNamespace
    from app import app
    monkeypatch.setattr('storage.cache.get_data', source)
    monkeypatch.setattr('storage.up_trends_reader.load_analysis', lambda: None)
    monkeypatch.setattr('storage.repositories.radar.get_radar_repository', lambda: SimpleNamespace(video_contexts=lambda ids, now: {}))
    with app.test_client() as client:
        anonymous = client.get('/internal/public-pages')
        member = client.get('/internal/public-pages', headers={'Cookie': 'kichu_session=untrusted', 'X-Write-Token': 'invalid'})
        assert anonymous.status_code == member.status_code == 200
        assert anonymous.json == member.json
        assert anonymous.json['sections']['kichu-rank']['status'] == 'ready'
        assert client.head('/internal/public-pages').data == b''
