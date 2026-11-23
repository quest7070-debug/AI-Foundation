import threading
import urllib.request

import pytest

from ai_foundation.core import GuardState
from ai_foundation.guard import GuardCore
from ai_foundation.operator_actions import OperatorActions
from ai_foundation.operator_server import OperatorApplication, serve
from ai_foundation.productization import FoundationConfig


def test_real_http_operator_surface(tmp_path):
    config = FoundationConfig(str((tmp_path / "data").resolve()))
    state = GuardState()
    guard = GuardCore(state)

    app = OperatorApplication(
        config,
        OperatorActions(guard),
    )

    server = serve(app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        host, port = server.server_address

        with urllib.request.urlopen(
            f"http://{host}:{port}/",
            timeout=2,
        ) as response:
            page = response.read().decode()

        assert "AI FOUNDATION" in page and "AI FOUNDATION / TERMINAL" not in page
        assert "SYSTEM STATUS" in page
        assert "NOTIFICATIONS" in page

        request = urllib.request.Request(
            f"http://{host}:{port}/action/approve/run-1",
            method="POST",
            data=b"",
            headers={"X-Foundation-CSRF": app.csrf_token},
        )

        with urllib.request.urlopen(request, timeout=2) as response:
            body = response.read().decode()

        assert '"APPROVED"' in body
        assert "run-1" in state.approvals

    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_concurrent_stuck_service_probe_never_blocks_other_status_probes(tmp_path):
    from threading import Event
    from time import monotonic
    started, release = Event(), Event()

    def stalled():
        started.set()
        assert release.wait(3)
        return True

    app = OperatorApplication(
        FoundationConfig(str((tmp_path / "data").resolve())),
        OperatorActions(GuardCore(GuardState())),
        service_probes={"STALLED": stalled, "OTHER": lambda: True},
    )
    observed = []
    thread = threading.Thread(
        target=lambda: observed.append(app.service_probes["STALLED"]()),
        daemon=True,
    )
    thread.start()
    try:
        assert started.wait(2)
        began = monotonic()
        # An overlapping read is UNKNOWN, not an invented DOWN service.
        assert app.service_probes["STALLED"]() is None
        assert monotonic() - began < 1.5
        assert app.service_probes["OTHER"]() is True
        rows = {row["name"]: row for row in app.snapshot().services}
        assert rows["STALLED"] == {
            "name": "STALLED", "ok": None, "detail": "probe-in-progress"}
        assert rows["OTHER"]["ok"] is True
        assert app.human_payload()["runtime_health"] != "DEGRADED"
    finally:
        release.set()
        thread.join(timeout=3)
    assert not thread.is_alive()
    assert observed == [True]
    assert app.service_probes["STALLED"]() is True


def test_service_probe_unknown_and_real_down_are_distinct(tmp_path):
    def unavailable():
        raise RuntimeError("private diagnostic must not be exposed")
    app = OperatorApplication(
        FoundationConfig(str((tmp_path / "data").resolve())),
        OperatorActions(GuardCore(GuardState())),
        service_probes={"ERROR": unavailable, "NONE": lambda: None,
                        "DOWN": lambda: False, "UP": lambda: True},
    )
    rows = {row["name"]: row for row in app.snapshot().services}
    assert rows["ERROR"]["ok"] is None
    assert rows["ERROR"]["detail"] == "probe-failed"
    assert rows["NONE"]["detail"] == "probe-unverified"
    assert rows["DOWN"]["ok"] is False
    assert rows["UP"]["ok"] is True
    assert "private diagnostic" not in str(rows)


def test_operator_live_guard_requests_not_cached_with_integrity_preflight(
        tmp_path):
    from ai_foundation.preflight import CachedPreflight, preflight
    from ai_foundation.store import SQLiteGuardStore
    root = tmp_path / "data"
    root.mkdir()
    config = FoundationConfig(str(root.resolve()))
    store = SQLiteGuardStore(root / config.guard_db)
    app = OperatorApplication(config, OperatorActions(
        GuardCore(store.load(), store=store)))
    calls = []
    def full_check():
        calls.append("integrity")
        return preflight(config)
    app.cached_preflight = CachedPreflight(full_check)
    assert app.human_payload()["development"]["guard_pending"] == 0
    assert store.request_approval("new-run", "production_deploy",
                                  "release-scope:fixed", "canon", "effect")
    assert app.human_payload()["development"]["guard_pending"] == 1
    assert len(calls) == 1


def test_operator_snapshot_locked_db_returns_503_without_private_error(
        tmp_path, monkeypatch):
    import http.client
    import ai_foundation.operator as operator_db
    from ai_foundation.operator import OperatorReadError

    app = OperatorApplication(
        FoundationConfig(str((tmp_path / "data").resolve())),
        OperatorActions(GuardCore(GuardState())))
    def locked(*_args, **_kwargs):
        raise OperatorReadError("PRIVATE_HOST_DB_NAME")
    monkeypatch.setattr(operator_db, "_rows", locked)
    srv = serve(app)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", srv.server_port, timeout=2)
        conn.request("GET", "/api/human")
        res = conn.getresponse()
        body = res.read()
        assert res.status == 503
        assert b"operator snapshot unavailable" in body
        assert b"PRIVATE_HOST" not in body
        conn.close()
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=2)


def test_operator_server_rejects_non_loopback(tmp_path):
    config = FoundationConfig(str((tmp_path / "data").resolve()))
    guard = GuardCore(GuardState())
    app = OperatorApplication(config, OperatorActions(guard))

    with pytest.raises(ValueError, match="loopback"):
        serve(app, host="0.0.0.0")

def test_operator_rejects_malformed_and_unknown_actions(tmp_path):
    config = FoundationConfig(str((tmp_path / "data").resolve()))
    state = GuardState()
    app = OperatorApplication(config, OperatorActions(GuardCore(state)))

    for action, subject in [
        ("delete-everything", "run-1"),
        ("approve", ".."),
        ("approve", "%2Fetc%2Fpasswd"),
        ("approve", "x" * 129),
    ]:
        with pytest.raises(ValueError):
            app.act(action, subject)

    assert not state.approvals
    assert not state.cancellations


def test_operator_security_headers(tmp_path):
    config = FoundationConfig(str((tmp_path / "data").resolve()))
    app = OperatorApplication(
        config,
        OperatorActions(GuardCore(GuardState())),
    )

    server = serve(app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        host, port = server.server_address
        with urllib.request.urlopen(
            f"http://{host}:{port}/",
            timeout=2,
        ) as response:
            assert response.headers["Cache-Control"] == "no-store"
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            assert "default-src 'none'" in response.headers[
                "Content-Security-Policy"
            ]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

# Phase G keeps the legacy page identity while evolving the visual shell.

def test_real_surface_routes_share_semantics_but_limit_authority(tmp_path):
 import threading,urllib.request
 from ai_foundation.operator_server import OperatorApplication,serve
 class C:data_dir=str(tmp_path);work_db='w.db'
 class A:pass
 class S:
  def as_dict(self):return {'ready':True,'waiting_human':0,'effects':{},'attention':[]}
 app=OperatorApplication(C(),A());app.snapshot=lambda:S();srv=serve(app);threading.Thread(target=srv.serve_forever,daemon=True).start()
 try:
  base=f'http://127.0.0.1:{srv.server_port}'
  d=urllib.request.urlopen(base+'/').read().decode();m=urllib.request.urlopen(base+'/mobile').read().decode();e=urllib.request.urlopen(base+'/echo').read().decode()
  assert 'class=responsive' in d and 'class=responsive' in m and 'class=echo' in e and d==m
  assert 'SUBMIT TASK' not in d+m+e and 'ADD API' in d and 'ADD API' in m and 'ADD API' not in e
 finally:srv.shutdown();srv.server_close()

def test_operator_page_csp_allows_its_same_origin_theme_sync_script(tmp_path):
 config=FoundationConfig(str((tmp_path/'data').resolve()));app=OperatorApplication(config,OperatorActions(GuardCore(GuardState())));srv=serve(app);import http.client
 t=threading.Thread(target=srv.serve_forever,daemon=True);t.start()
 try:
  host,port=srv.server_address;c=http.client.HTTPConnection(host,port);c.request('GET','/');r=c.getresponse();r.read();csp=r.getheader('Content-Security-Policy');assert "script-src 'unsafe-inline'" in csp and "connect-src 'self'" in csp
 finally:srv.shutdown();srv.server_close()


def test_browser_operator_action_redirects_back_to_human_surface(tmp_path):
    import urllib.parse, urllib.error
    config=FoundationConfig(str((tmp_path/'data').resolve()))
    state=GuardState(); app=OperatorApplication(config,OperatorActions(GuardCore(state)))
    server=serve(app); thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        host,port=server.server_address
        data=urllib.parse.urlencode({'csrf':app.csrf_token,'return_to':'/'}).encode()
        req=urllib.request.Request(f'http://{host}:{port}/action/approve/run-browser',method='POST',data=data)
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs): return None
        try:
            urllib.request.build_opener(NoRedirect).open(req,timeout=2); assert False
        except urllib.error.HTTPError as exc:
            assert exc.code==303 and exc.headers['Location']=='/' and exc.headers['Cache-Control']=='no-store'
        assert 'run-browser' in state.approvals
    finally:
        server.shutdown();server.server_close();thread.join(timeout=2)

def test_operational_failure_notice_is_in_human_payload(tmp_path):
 from ai_foundation.productization import FoundationConfig
 from ai_foundation.operator_server import OperatorApplication
 from ai_foundation.operator_actions import OperatorActions
 from ai_foundation.guard import GuardCore
 from ai_foundation.core import GuardState
 from ai_foundation.human_operations import HumanNotice
 app=OperatorApplication(FoundationConfig(str(tmp_path.resolve())),OperatorActions(GuardCore(GuardState())),operational_notices=lambda:(HumanNotice(3,'system','long-term-health','FAILED','Long-term health requires attention.','free-space: 1 bytes free'),))
 payload=app.human_payload();rows=[x for x in payload['notices'] if x['subject']=='long-term-health']
 assert len(rows)==1 and rows[0]['level']==3 and 'free-space' in rows[0]['detail_ja']


def test_human_api_includes_component_service_health(tmp_path):
 app=OperatorApplication(FoundationConfig(str((tmp_path/'data').resolve())),OperatorActions(GuardCore(GuardState())),service_probes={'TOOLHIVE FILES':lambda:True,'TOOLHIVE CODE':lambda:False})
 rows={x['name']:x for x in app.human_payload()['services']}
 assert rows['TOOLHIVE FILES']['ok'] is True and rows['TOOLHIVE CODE']['ok'] is False



def test_runtime_humanmodel_factory_wiring_is_read_only_and_explicit(tmp_path):
    config=FoundationConfig(str((tmp_path/'data').resolve()))
    actions=OperatorActions(GuardCore(GuardState()))
    def owner_factory(request, run_id):
        raise AssertionError("Never run an agent from this status test")
    owner_factory._foundation_owner_humanmodel_factory=True
    app=OperatorApplication(config,actions,inference=lambda _:None,
                            auto_agent_factory=owner_factory)
    snapshot=app.human_payload()
    assert snapshot['development']['humanmodel_factory_registered'] is True
    assert snapshot['development']['legacy_question_resolver_enabled'] is False
    assert snapshot['development']['host_question_resolver_registered'] is False
    assert snapshot['development']['approved_humanmodel_view']=='UNVERIFIED'
    # It is a runtime wiring bit, not a Grant or a successful View read.
    assert app.openai.auto_agent_factory is owner_factory
    no_factory=OperatorApplication(config,actions,inference=lambda _:None)
    assert no_factory.human_payload()['development']['humanmodel_factory_registered'] is False
    owner_factory._foundation_owner_humanmodel_factory='true'
    untrusted=OperatorApplication(config,actions,inference=lambda _:None,
                                  auto_agent_factory=owner_factory)
    assert untrusted.human_payload()['development']['humanmodel_factory_registered'] is False
    # Observe in-process callbacks without executing either resolver.
    legacy=OperatorApplication(config,actions,
                               question_resolver=lambda request: None,
                               host_question_resolver=lambda bundle, authority: None)
    wired=legacy.human_payload()['development']
    assert wired['legacy_question_resolver_enabled'] is True
    assert wired['host_question_resolver_registered'] is True


def test_failed_banner_remains_visible_when_failure_notice_dismissed(tmp_path):
    from ai_foundation.operator import OperatorSnapshot
    import json
    config = FoundationConfig(str((tmp_path / 'data').resolve()))
    app = OperatorApplication(config, OperatorActions(GuardCore(GuardState())))
    class DismissAll:
        def hidden(self, subject, status):
            return status == 'FAILED'
    app.dismissals = DismissAll()
    snapshot = OperatorSnapshot(
        version=1, ready=True, checks=(), effects={}, waiting_human=0,
        work={'FAILED': 1}, trace_present=False,
        attention=({'kind': 'work', 'id': 'PRIVATE_JOB', 'run_id': 'PRIVATE_RUN',
                    'step': 'PRIVATE_STEP', 'status': 'FAILED', 'updated_at': 0},
                   {'kind': 'effect', 'id': 'PRIVATE_EFFECT', 'run_id': 'PRIVATE_RUN',
                    'target': 'PRIVATE_TARGET', 'status': 'FAILED', 'updated_at': 0}),
    )
    app.snapshot = lambda: snapshot
    result = app.human_payload()
    assert result['state'] == 'FAILED'
    assert result['notices'] == []
    assert result['state_diagnostics'] == {
        'failed_work_window': 1, 'failed_effect_window': 1,
        'dismissed_failed_notices_window': 2,
    }
    assert 'PRIVATE_' not in json.dumps(result)
