"""Synthetic isolated test service. Never copied into a production image."""
import hashlib
import json
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

FIXTURE = json.loads(Path('/fixtures/fixtures.json').read_text(encoding='utf-8'))
state = {'version': 1, 'up_version': 1, 'fail': False, 'up_fail': False}


def sections():
    result = deepcopy(FIXTURE)
    for tab, section in result['sections'].items():
        if (state['up_fail'] and tab == 'up-trends') or (state['fail'] and tab != 'up-trends'):
            result['sections'][tab] = {'status': 'unavailable', 'data': {}, 'content_version': None, 'source_updated_at': None}
            continue
        version = state['up_version'] if tab == 'up-trends' else state['version']
        section['data'] = json.loads(json.dumps(section['data'], ensure_ascii=False).replace('合成公开', f'合成公开v{version}'))
        section['content_version'] = hashlib.sha256(json.dumps(section['data'], sort_keys=True).encode()).hexdigest()
    return result


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        if path.startswith('/__test/'):
            command = path.removeprefix('/__test/')
            if command == 'change':
                state['version'] += 1
            elif command == 'up-change':
                state['up_version'] += 1
            elif command == 'fail':
                state['fail'] = True
            elif command == 'up-fail':
                state['up_fail'] = True
            elif command == 'reset':
                state.update(version=1, up_version=1, fail=False, up_fail=False)
            return self.send_json(state)
        public = sections()
        dashboard = {}
        for tab, section in public['sections'].items():
            if tab != 'up-trends':
                dashboard.update(section['data'])
        if path == '/internal/public-pages':
            return self.send_json(public)
        if path == '/api/dashboard':
            return self.send_json({'success': True, 'data': dashboard})
        if path == '/api/up-trends/analysis':
            return self.send_json({'success': True, 'data': public['sections']['up-trends']['data'].get('up_analysis')})
        if path == '/api/up-trends/check':
            return self.send_json({'success': True, 'has_list': True, 'has_analysis': True, 'analyzing': False})
        if path == '/api/auth/me':
            return self.send_json({'success': True, 'data': {'admin': False, 'user': None}})
        if path == '/api/status':
            return self.send_json({'success': True, 'data': {'crawling': False}})
        return self.send_json({'success': True, 'data': []})

    def send_json(self, data):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


ThreadingHTTPServer(('0.0.0.0', 5000), Handler).serve_forever()
