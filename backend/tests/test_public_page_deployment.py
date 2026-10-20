from tests.test_compose_security import _production_config, ROOT


def test_public_html_service_has_only_dedicated_cache_and_internal_network(tmp_path):
    config = _production_config(tmp_path)
    service = config['services']['public-pages']
    assert set(service['networks']) == {'core'}
    assert not service.get('ports')
    assert not service.get('secrets')
    assert service['build']['target'] == 'public-pages'
    assert service['read_only'] is True
    assert [(v['type'], v['target']) for v in service['volumes']] == [('volume', '/cache')]
    assert config['services']['frontend']['build']['target'] == 'frontend'
    assert 'public-pages' in config['services']['frontend']['depends_on']


def test_public_ingress_rejects_internal_paths_and_has_no_spa_fallback():
    nginx = (ROOT / 'frontend/nginx.conf').read_text(encoding='utf-8')
    caddy = (ROOT / 'ops/caddy/Caddyfile').read_text(encoding='utf-8')
    assert '/internal/' in nginx and '/internal/' in caddy
    assert 'try_files $uri $uri/ /index.html' not in nginx
    assert 'include /etc/nginx/public-routes.inc' in nginx
