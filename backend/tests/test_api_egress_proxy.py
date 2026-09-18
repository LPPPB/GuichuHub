"""Exercise the deployed Squid policy against an isolated local HTTP stub."""

import base64
import json
import socket
import subprocess
import time
import uuid
from pathlib import Path

import pytest
import requests

from tests.test_compose_security import _production_config

ROOT = Path(__file__).resolve().parents[2]


def test_proxy_connect_allowlist_and_private_destination_denial(tmp_path, monkeypatch):
    config = _production_config(tmp_path)
    assert "api-egress" in config["services"], "Synchronous routes need the restricted proxy"
    image = config["services"]["api-egress"]["image"]
    assert "@sha256:" in image
    policy = (ROOT / "ops/egress/squid.conf").read_bytes()
    network = f"kichu-egress-test-{uuid.uuid4().hex}"
    subprocess.run(["docker", "network", "create", "--internal", "--subnet", "11.231.253.0/24", network], check=True, capture_output=True)
    containers = []
    try:
        stub_code = '''
import json, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
class Stub(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        data = {'code':0,'data':{'url':'https://fixture.invalid/qr','qrcode_key':'local-fixture','code':86101}}
        body = json.dumps(data).encode()
        self.send_response(200); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
threading.Thread(target=ThreadingHTTPServer(('0.0.0.0',80),Stub).serve_forever,daemon=True).start()
ThreadingHTTPServer(('0.0.0.0',443),Stub).serve_forever()
'''
        stub = subprocess.check_output(["docker", "run", "--rm", "-d", "--network", network,
            "--ip", "11.231.253.2", "python:3.12-slim", "python", "-c", stub_code], text=True).strip()
        containers.append(stub)
        command = ["docker", "run", "--rm", "-d", "--network", "bridge", "-p", "127.0.0.1::8080",
                   "--entrypoint", "sh"]
        for host in ("passport.bilibili.com", "api.bilibili.com", "www.bilibili.com", "i0.hdslb.com", "i0.biliimg.com"):
            command += ["--add-host", f"{host}:11.231.253.2"]
        command += ["--add-host", "private.hdslb.com:127.0.0.1", image, "-c",
                    'printf %s "$1" | base64 -d > /tmp/policy.conf; exec squid -N -f /tmp/policy.conf',
                    "sh", base64.b64encode(policy).decode()]
        proxy = subprocess.check_output(command, text=True).strip()
        containers.append(proxy)
        subprocess.run(["docker", "network", "connect", network, proxy], check=True, capture_output=True)
        port = int(subprocess.check_output(["docker", "port", proxy, "8080/tcp"], text=True).strip().rsplit(":", 1)[1])
        for _ in range(50):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    break
            except OSError:
                time.sleep(0.1)
        proxies = {"http": f"http://127.0.0.1:{port}", "https": f"http://127.0.0.1:{port}"}
        for host in ("api.bilibili.com", "i0.hdslb.com", "i0.biliimg.com"):
            assert requests.get(f"http://{host}/fixture", proxies=proxies, timeout=5).status_code == 200
        for target in ("http://example.invalid/", "http://bilibili.com.evil.invalid/", "http://private.hdslb.com/",
                       "http://127.0.0.1/", "http://169.254.169.254/", "http://api.bilibili.com:22/"):
            assert requests.get(target, proxies=proxies, timeout=5).status_code == 403
        with socket.create_connection(("127.0.0.1", port), timeout=5) as tunnel:
            tunnel.sendall(b"CONNECT passport.bilibili.com:443 HTTP/1.1\r\nHost: passport.bilibili.com\r\n\r\n")
            assert b"200 Connection established" in tunnel.recv(4096)
            tunnel.sendall(b"GET /fixture HTTP/1.0\r\nHost: passport.bilibili.com\r\n\r\n")
            assert b"200 OK" in tunnel.recv(4096)
        # Preserve collector behavior while the transport is an HTTP-only stub.
        send = requests.adapters.HTTPAdapter.send
        def stub_transport(adapter, request, **kwargs):
            request.url = request.url.replace("https://", "http://", 1)
            kwargs["proxies"] = proxies
            return send(adapter, request, **kwargs)
        monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", stub_transport)
        from collectors.bilibili_auth import generate_qrcode, check_login_status
        assert generate_qrcode()["qrcode_key"] == "local-fixture"
        assert check_login_status("local-fixture", save=False)["status"] == "waiting"
    finally:
        for container in reversed(containers):
            subprocess.run(["docker", "stop", container], capture_output=True)
        subprocess.run(["docker", "network", "rm", network], capture_output=True)
