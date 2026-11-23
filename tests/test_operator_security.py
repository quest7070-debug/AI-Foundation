import sqlite3
from ai_foundation.core import GuardState
from ai_foundation.guard import GuardCore
from ai_foundation.operator import snapshot,render_json
from ai_foundation.human_view import from_snapshot
from ai_foundation.human_renderer import render
from ai_foundation.operator_actions import OperatorActions
from ai_foundation.productization import FoundationConfig

class Credentials:
    def available(self,binding): return True

def test_operator_never_renders_raw_secret(tmp_path):
    root=tmp_path/'data'; root.mkdir()
    secret='sk-test-DO-NOT-LEAK-123456'
    c=FoundationConfig(str(root.resolve()))
    s=snapshot(c,Credentials(),('prod-api',))
    output=render_json(s)+render(from_snapshot(s),'responsive')
    assert secret not in output
    assert 'prod-api' in output
    assert 'available' in output

def test_attention_escapes_untrusted_db_values(tmp_path):
    root=tmp_path/'data'; root.mkdir()
    from ai_foundation.store import SQLiteGuardStore
    from ai_foundation.core import GuardState,EffectIntent,EffectStatus
    store=SQLiteGuardStore(root/'guard.db')
    store.save(GuardState(effects={'e1':EffectIntent('e1','r1','<script>alert(1)</script>','x',EffectStatus.EXECUTING,0)}))
    store.transition_effect('e1',EffectStatus.EXECUTING,EffectStatus.UNCERTAIN)
    page=render(from_snapshot(snapshot(FoundationConfig(str(root.resolve())))),'responsive')
    assert '<script>alert(1)</script>' not in page
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' not in page  # target is intentionally not rendered in minimal HTML

def test_duplicate_operator_actions_are_idempotent_in_memory():
    state=GuardState(); actions=OperatorActions(GuardCore(state))
    assert actions.approve_run('run-1').ok and actions.approve_run('run-1').ok
    assert state.approvals=={'run-1'}
    assert actions.cancel_run('run-2').ok and actions.cancel_run('run-2').ok
    assert state.cancellations=={'run-2'}

def test_post_requires_csrf_and_same_origin(tmp_path):
    import threading, urllib.request, urllib.error
    from ai_foundation.operator_server import OperatorApplication, serve
    class Actions:
        def approve_run(self,x): raise AssertionError('must not reach action')
        def cancel_run(self,x): raise AssertionError('must not reach action')
    app=OperatorApplication(type('C',(),{})(),Actions(),csrf_token='known-token')
    server=serve(app); t=threading.Thread(target=server.serve_forever,daemon=True); t.start()
    try:
        base=f'http://127.0.0.1:{server.server_port}'
        for headers in ({},{'X-Foundation-CSRF':'known-token','Origin':'https://evil.invalid'}):
            req=urllib.request.Request(base+'/action/approve/run1',method='POST',headers=headers)
            try: urllib.request.urlopen(req); assert False
            except urllib.error.HTTPError as e: assert e.code==403
    finally: server.shutdown(); server.server_close()



def _security_server():
    import threading
    from ai_foundation.operator_server import OperatorApplication,serve
    app=OperatorApplication(type('C',(),{})(),object(),csrf_token='T'); app.snapshot=lambda:type('S',(),{'as_dict':lambda self:{'ready':True,'attention':[],'waiting_human':0,'effects':{}}})()
    srv=serve(app);threading.Thread(target=srv.serve_forever,daemon=True).start();return app,srv

def test_get_rejects_non_loopback_host():
    app,srv=_security_server()
    import http.client
    try:
        c=http.client.HTTPConnection('127.0.0.1',srv.server_port);c.request('GET','/',headers={'Host':'evil.example'});r=c.getresponse();assert r.status==403
    finally:srv.shutdown();srv.server_close()

def test_post_rejects_transfer_encoding():
    app,srv=_security_server()
    import http.client
    try:
        c=http.client.HTTPConnection('127.0.0.1',srv.server_port);c.putrequest('POST','/task/submit');c.putheader('Host',f'127.0.0.1:{srv.server_port}');c.putheader('Transfer-Encoding','chunked');c.putheader('X-Foundation-CSRF',app.csrf_token);c.endheaders();c.send(b'0\r\n\r\n');r=c.getresponse();assert r.status==411
    finally:srv.shutdown();srv.server_close()
