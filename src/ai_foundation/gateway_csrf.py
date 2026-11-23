"""Expose the existing loopback CSRF token without rendering operational state."""
import json
from urllib.parse import urlparse

def install_fast_csrf():
    from . import operator_server
    original=operator_server.make_handler
    def make_handler(app):
        base=original(app)
        class Handler(base):
            def do_GET(self):
                if urlparse(self.path).path!='/api/gateway/csrf':
                    return super().do_GET()
                host=self.headers.get('Host','').rsplit(':',1)[0].strip('[]').lower()
                if host not in {'127.0.0.1','localhost','::1'}:
                    self._send(403,'forbidden\n','text/plain; charset=utf-8');return
                raw=(json.dumps({'csrf':app.csrf_token})+'\n').encode()
                self.send_response(200)
                self.send_header('Content-Type','application/json; charset=utf-8')
                self.send_header('Content-Length',str(len(raw)))
                self.send_header('Cache-Control','no-store')
                self.send_header('X-Content-Type-Options','nosniff')
                self.send_header('X-Foundation-CSRF-Endpoint','1')
                self.end_headers();self.wfile.write(raw)
        return Handler
    operator_server.make_handler=make_handler
