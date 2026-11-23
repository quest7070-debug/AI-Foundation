import http.client
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace
import threading

import pytest
from ai_foundation import operator_server
from ai_foundation.gateway_csrf import install_fast_csrf
from scripts.gateway_support import current_csrf

@pytest.fixture
def operator(monkeypatch):
    original=operator_server.make_handler
    monkeypatch.setattr(operator_server,'make_handler',original)
    install_fast_csrf()
    def slow_page(*args):
        raise AssertionError('operational rendering must not run')
    app=SimpleNamespace(csrf_token='test-only-token',page=slow_page)
    server=operator_server.serve(app)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield server
    finally:server.shutdown();server.server_close();thread.join()

def test_gateway_csrf_avoids_rendering_and_preserves_models(operator):
    port=operator.server_port
    assert current_csrf(port)=='test-only-token'
    client=http.client.HTTPConnection('127.0.0.1',port,timeout=2)
    client.request('GET','/v1/models')
    response=client.getresponse()
    assert response.status==200
    assert b'foundation-auto' in response.read()
    client.close()

def test_gateway_csrf_rejects_external_host(operator):
    client=http.client.HTTPConnection('127.0.0.1',operator.server_port,timeout=2)
    client.request('GET','/api/gateway/csrf',headers={'Host':'attacker.invalid'})
    response=client.getresponse()
    assert response.status==403
    response.read();client.close()

@pytest.mark.parametrize('unknown_status',[200,404])
def test_gateway_csrf_retains_older_operator_fallback(unknown_status):
    requests=[]
    class Old(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            body=b'<input name=csrf value="old-test-token">' if self.path=='/' else b''
            self.send_response(200 if self.path=='/' else unknown_status)
            self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def log_message(self,*args):pass
    server=HTTPServer(('127.0.0.1',0),Old)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        assert current_csrf(server.server_port)=='old-test-token'
        assert requests==['/api/gateway/csrf','/']
    finally:server.shutdown();server.server_close();thread.join()


def test_installed_operator_runner_enables_fast_csrf_before_serve():
    # The endpoint implementation existed but production's entrypoint did
    # not install it. This assertion protects against that wiring regression.
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    script=(root/'scripts/operator_server.py').read_text(encoding='utf-8')
    assert 'from ai_foundation.gateway_csrf import install_fast_csrf' in script
    assert script.index(' install_fast_csrf()') < script.index(' server=serve(app,port=a.port)')
