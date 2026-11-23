"""Mobile owner release on existing Tailnet HTTPS gateway: no real effects."""
from __future__ import annotations

import http.client
import json
import re
import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

from ai_foundation.remote_access import RemoteAccess, RemoteAccessConfig
from scripts.m1_mobile_owner_release import (
    MobileOwnerRelease, OwnerReleaseOperations, TailnetOwnerIdentity,
)
from scripts.remote_gateway import handler


HEAD = "b" * 40
SCOPE = "c" * 64
RUN = "release-phone-fixed"
REQUEST = "d" * 64
SECRET = "Q" * 48


class FakeOps:
    def __init__(self):
        self.state = None
        self.mutations = []
    def observe(self, head):
        assert head == HEAD
        return {"head": HEAD, "scope_ref": SCOPE, "preflight_ok": True,
                "release_state": "VERIFIED", "verified_incumbent_loaded": True}
    def pending(self, head, scope):
        assert head == HEAD and scope == SCOPE
        if not self.state:
            return None
        return {"run_id": RUN, "request_ref": REQUEST, "state": self.state}
    def request(self, head, scope, phrase):
        assert (head, scope, phrase) == (HEAD, SCOPE, "REQUEST " + SCOPE[:16])
        self.state = "PENDING"
        self.mutations.append("request")
        return {"status": "WAITING_HUMAN"}
    def approve(self, head, scope, run_id, request_ref):
        assert (head, scope, run_id, request_ref) == (HEAD, SCOPE, RUN, REQUEST)
        assert self.state == "PENDING"
        self.state = "APPROVED"
        self.mutations.append("approve")
        return {"status": "GUARD_APPROVED"}
    def apply(self, head, scope, run_id, request_ref, phrase):
        assert (head, scope, run_id, request_ref) == (HEAD, SCOPE, RUN, REQUEST)
        assert phrase == "APPLY " + SCOPE[:16]
        assert self.state == "APPROVED"
        self.state = "VERIFIED"
        self.mutations.append("apply")
        return {"status": "VERIFIED"}


def _form(service, action, peer="owner-phone"):
    run, request = (RUN, REQUEST) if action in ("approve", "apply") else ("", "")
    phrase = ("AUTHORIZE" if action == "approve" else action.upper()) + " " + SCOPE[:16]
    return {"head": [HEAD], "scope": [SCOPE],
            "run_id": [run], "request_ref": [request],
            "token": [service.token(action, peer, HEAD, SCOPE, run, request)],
            "confirmation": [phrase], "confirmed": ["yes"]}


def test_mobile_release_exact_three_step_flow_never_implicitly_approves():
    ops = FakeOps()
    service = MobileOwnerRelease(SECRET, ops=ops, now=lambda: 1700000000)
    status, page = service.render("owner-phone", HEAD)
    assert status == 200 and "/release/request" in page
    assert ops.mutations == []
    code, page = service.submit("request", "owner-phone", _form(service, "request"))
    assert code == 200 and "/release/approve" in page
    assert ops.mutations == ["request"]
    code, page = service.submit("approve", "owner-phone", _form(service, "approve"))
    assert code == 200 and "/release/apply" in page
    assert ops.mutations == ["request", "approve"]
    code, page = service.submit("apply", "owner-phone", _form(service, "apply"))
    assert code == 200 and "VERIFIED" in page
    assert ops.mutations == ["request", "approve", "apply"]
    assert service.submit("apply", "owner-phone", _form(service, "apply"))[0] == 409
    assert ops.mutations == ["request", "approve", "apply"]


def test_mobile_release_owner_peer_scope_hmac_and_confirm_are_mandatory():
    ops = FakeOps()
    clock = [1700000000]
    service = MobileOwnerRelease(SECRET, ops=ops, now=lambda: clock[0])
    good = _form(service, "request")
    assert service.submit("request", "other-owner-node", good)[0] == 403
    assert service.submit("request", "owner-phone", {**good, "head": ["a" * 40]})[0] == 403
    assert service.submit("request", "owner-phone", {**good, "confirmed": ["no"]})[0] == 403
    assert service.submit("request", "owner-phone", {**good, "confirmation": ["APPLY " + SCOPE[:16]]})[0] == 403
    assert service.submit("request", "owner-phone", {**good, "extra": ["unsafe"]})[0] == 400
    assert ops.mutations == []
    clock[0] += 301
    assert service.submit("request", "owner-phone", good)[0] == 403
    assert ops.mutations == []


def test_tailnet_whois_accepts_only_owners_exact_untagged_peer_cidr():
    self_user = 1000123
    source = {
        "status": {"Self": {"ID": "node-self", "UserID": self_user}},
        "whois": {"Node": {
            "ID": "node-phone", "User": self_user,
            "Addresses": ["100.86.71.22/32", "fd7a:115c:a1e0::123/128"],
            "Tags": None, "Sharer": None,
        }, "UserProfile": {"ID": self_user, "LoginName": "owner@example.invalid"}}
    }
    def invoke(argv, **kwargs):
        assert argv[0] == "/usr/local/bin/tailscale"
        key = argv[1]
        assert kwargs["check"] is True
        return SimpleNamespace(stdout=json.dumps(source[key]))
    owner = TailnetOwnerIdentity(invoke=invoke)
    assert owner.owner_peer("100.86.71.22") == "node-phone"
    assert owner.owner_peer("fd7a:115c:a1e0::123") == "node-phone"
    assert owner.owner_peer("10.0.0.20") is None
    assert owner.owner_peer("127.0.0.1") is None
    source["whois"]["Node"]["Tags"] = ["tag:server"]
    assert owner.owner_peer("100.86.71.22") is None
    source["whois"]["Node"]["Tags"] = None
    source["whois"]["Node"]["User"] = self_user + 1
    assert owner.owner_peer("100.86.71.22") is None
    source["whois"]["Node"]["User"] = self_user
    source["whois"]["Node"]["Sharer"] = self_user
    assert owner.owner_peer("100.86.71.22") is None
    source["whois"]["Node"]["Sharer"] = None
    source["whois"]["Node"]["Addresses"] = ["100.86.71.23/32"]
    assert owner.owner_peer("100.86.71.22") is None


def test_owner_release_ops_pass_only_pin_to_existing_guarded_cli(monkeypatch, tmp_path):
    from scripts import m1_operator_release_cli as cli
    calls = []
    def fake_run(args, *, trusted_source_root, confirmer):
        calls.append((args.operation, args.expected_head, str(trusted_source_root)))
        assert confirmer("request", "REQUEST " + SCOPE[:16]) is True
        return {"status": "WAITING_HUMAN"}
    monkeypatch.setattr(cli, "run", fake_run)
    ops = OwnerReleaseOperations(home=tmp_path)
    result = ops._cli(HEAD, "request", phrase="REQUEST " + SCOPE[:16])
    assert result["status"] == "WAITING_HUMAN"
    assert calls == [("request", HEAD, str(tmp_path / ".ai-foundation-tunnel-sources" / HEAD))]
    with pytest.raises(PermissionError):
        ops._cli("..", "request", phrase="REQUEST " + SCOPE[:16])


class _Peer:
    def __init__(self, *, value="owner-phone"):
        self.value = value
    def owner_peer(self, _remote_ip):
        return self.value


def _server(ops, peer):
    access = RemoteAccess(RemoteAccessConfig(
        SECRET, frozenset({"owner-m1.example.ts.net"}), True))
    mobile = MobileOwnerRelease(SECRET, ops=ops)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler(
        access, 1, mobile_release=mobile, tailnet_owner=peer))
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    return srv, mobile


def _http(srv, method, path, fields=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", srv.server_port, timeout=5)
    h = {"Host": "owner-m1.example.ts.net:8793"}
    if fields is not None:
        h.update({"Origin": "https://owner-m1.example.ts.net:8793",
                  "Content-Type": "application/x-www-form-urlencoded"})
    h.update(headers or {})
    try:
        c.request(method, path, body=urlencode(fields, doseq=True) if fields is not None else None, headers=h)
        r = c.getresponse()
        return r.status, r.read().decode(), r.getheader("Content-Security-Policy")
    finally:
        c.close()


def test_private_gateway_mobile_owner_release_origin_csrf_and_404_guards():
    ops = FakeOps()
    server, service = _server(ops, _Peer())
    try:
        status, body, csp = _http(server, "GET", "/release?sha=" + HEAD)
        assert status == 200 and "REQUEST" in body
        assert "script-src 'none'" in csp
        # Loopback hosts may serve ordinary human status, but never a
        # privileged phone release: no trusted .ts.net owner identity.
        assert _http(server, "GET", "/release", headers={"Host": "127.0.0.1"})[0] == 403
        assert _http(server, "GET", "/release?sha=bad")[0] == 409
        assert _http(server, "GET", "/release?sha=" + HEAD + "&sha=" + HEAD)[0] == 400
        form = _form(service, "request", peer="owner-phone")
        for headers in (
            {"Origin": "https://evil.invalid"},
            {"Origin": "http://owner-m1.example.ts.net:8793"},
            {"Sec-Fetch-Site": "cross-site"},
            {"Content-Type": "text/plain"},
        ):
            assert _http(server, "POST", "/release/request", form, headers)[0] == 403
        assert ops.mutations == []
        assert _http(server, "POST", "/release/request", form)[0] == 200
        assert ops.mutations == ["request"]
        assert _http(server, "POST", "/release/unknown", form)[0] == 400
        assert ops.mutations == ["request"]
    finally:
        server.shutdown()
        server.server_close()


def test_private_gateway_never_opens_release_to_unverified_peer():
    ops = FakeOps()
    server, service = _server(ops, _Peer(value=None))
    try:
        assert _http(server, "GET", "/release")[0] == 403
        assert _http(server, "POST", "/release/request", _form(service, "request"))[0] == 403
        assert ops.mutations == []
    finally:
        server.shutdown()
        server.server_close()


def test_private_gateway_defaults_to_no_release_service():
    access = RemoteAccess(RemoteAccessConfig(
        SECRET, frozenset({"owner-m1.example.ts.net"}), True))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler(access, 1))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert _http(server, "GET", "/release")[0] == 403
        assert _http(server, "POST", "/release/apply", _form(
            MobileOwnerRelease(SECRET, ops=FakeOps()), "apply"))[0] == 403
    finally:
        server.shutdown()
        server.server_close()



def test_serve_identity_matches_live_owner_profile_never_just_the_login_header():
    uid=11337
    status={
        "BackendState":"Running",
        "Self":{"UserID":uid,"ID":"node-owner"},
        "User":{str(uid):{"ID":uid,"LoginName":"owner@example.invalid"}},
    }
    def invoke(argv,**kw):
        assert argv==["/usr/local/bin/tailscale","status","--json"]
        assert kw["check"] is True
        return SimpleNamespace(stdout=json.dumps(status))
    identity=TailnetOwnerIdentity(invoke=invoke)
    assert identity.serve_owner_login("owner@example.invalid")=="serve-owner:11337"
    assert identity.serve_owner_login("shared@example.invalid") is None
    assert identity.serve_owner_login("owner@example.invalid\nInjected: yes") is None
    assert identity.serve_owner_login(None) is None
    status["Self"]["Tags"]=["tag:server"]
    assert identity.serve_owner_login("owner@example.invalid") is None
    status["Self"]["Tags"]=[]
    status["BackendState"]="NeedsLogin"
    assert identity.serve_owner_login("owner@example.invalid") is None
    status["BackendState"]="Running"
    status["User"][str(uid)]["ID"]=99
    assert identity.serve_owner_login("owner@example.invalid") is None
    status["User"][str(uid)]["ID"]=uid
    status["User"][str(uid)]["LoginName"]="different@example.invalid"
    assert identity.serve_owner_login("owner@example.invalid") is None


def test_serve_proxy_owner_headers_are_opt_in_loopback_only(monkeypatch):
    class ServeOnlyOwner:
        def owner_peer(self,ip):
            assert ip=="127.0.0.1"
            return None
        def serve_owner_login(self,login):
            return "serve-owner:42" if login=="owner@example.invalid" else None

    ops=FakeOps()
    srv,release=_server(ops,ServeOnlyOwner())
    host="owner-m1.example.ts.net:8793"
    owner_header={"Tailscale-User-Login":"owner@example.invalid"}
    try:
        assert _http(srv,"GET","/release",headers=owner_header)[0]==403
        monkeypatch.setenv("FOUNDATION_REMOTE_SERVE_OWNER_ENABLED","1")
        # Enabled only if the socket itself is truly loopback bound.
        assert _http(srv,"GET","/release",headers=owner_header)[0]==200
        assert _http(srv,"GET","/release",headers={
            "Tailscale-User-Login":"other@example.invalid"})[0]==403
        assert _http(srv,"GET","/release",headers={
            "Tailscale_User_Login":"owner@example.invalid"})[0]==403
        form=_form(release,"request",peer="serve-owner:42")
        # Tailscale Serve publishes :8454 but the gateway can observe
        # the backend :8793 Host. Only the exact external origin is accepted.
        browser={**owner_header,"Origin":"https://owner-m1.example.ts.net:8454"}
        for bad in (
            {"Origin":"null"},
            {"Origin":""},
            {"Origin":"https://owner-m1.example.ts.net:8455"},
            {"Origin":"https://attacker.invalid:8454"},
            {"Origin":"http://owner-m1.example.ts.net:8454"},
            {"Origin":"https://owner-m1.example.ts.net:8454","Sec-Fetch-Site":"cross-site"},
            {"Origin":"https://owner-m1.example.ts.net:8454","Content-Type":"text/plain"},
        ):
            assert _http(srv,"POST","/release/request",form,
                         headers={**owner_header,**bad})[0]==403
        assert ops.mutations==[]
        assert _http(srv,"POST","/release/request",form,headers=browser)[0]==200
        assert ops.mutations==["request"]
        assert _http(srv,"POST","/release/request",form,headers=browser)[0]==409
        assert ops.mutations==["request"]
        original=srv.server_address
        srv.server_address=("0.0.0.0",original[1])
        assert _http(srv,"GET","/release",headers=owner_header)[0]==403
        assert _http(srv,"POST","/release/approve",_form(
            release,"approve",peer="serve-owner:42"),headers=owner_header)[0]==403
        assert ops.mutations==["request"]
    finally:
        srv.shutdown()
        srv.server_close()




def test_missing_origin_release_controls_still_need_owner_referer_and_signed_guard_form(monkeypatch):
    """Even owner-approved fallback must preserve exact 3-step Guard gate."""
    class ServeOnlyOwner:
        def owner_peer(self, ip):
            assert ip == "127.0.0.1"
            return None
        def serve_owner_login(self, login):
            return "serve-owner:42" if login == "owner@example.invalid" else None

    ops = FakeOps()
    srv, release = _server(ops, ServeOnlyOwner())
    monkeypatch.setenv("FOUNDATION_REMOTE_SERVE_OWNER_ENABLED", "1")
    header = {
        "Tailscale-User-Login": "owner@example.invalid",
        "Origin": "",
        "Sec-Fetch-Site": "same-origin",
        "Referer": "https://owner-m1.example.ts.net:8454/release",
    }
    try:
        form = _form(release, "request", peer="serve-owner:42")
        for changed in (
            {"Referer": "https://attacker.invalid/release"},
            {"Referer": "https://owner-m1.example.ts.net:8455/release"},
            {"Sec-Fetch-Site": "cross-site"},
            {"Sec-Fetch-Site": "same-site"},
            {"Origin": "https://attacker.invalid"},
            {"Tailscale-User-Login": "stranger@example.invalid"},
        ):
            code, _, _ = _http(srv, "POST", "/release/request", form,
                              headers={**header, **changed})
            assert code == 403, changed
        assert ops.mutations == []
        code, _, _ = _http(srv, "POST", "/release/request", form,
                          headers=header)
        assert code == 200
        assert ops.mutations == ["request"]
        # The existing authenticated Guard state-machine still blocks a
        # missing decision; no accidental promotion on reusing a request.
        assert _http(srv, "POST", "/release/request", form,
                     headers=header)[0] == 409
        assert ops.mutations == ["request"]
        form = _form(release, "approve", peer="serve-owner:42")
        assert _http(srv, "POST", "/release/approve", form,
                     headers=header)[0] == 200
        assert ops.mutations == ["request", "approve"]
        form = _form(release, "apply", peer="serve-owner:42")
        assert _http(srv, "POST", "/release/apply", form,
                     headers=header)[0] == 200
        assert ops.mutations == ["request", "approve", "apply"]
        assert _http(srv, "POST", "/release/apply", form,
                     headers=header)[0] == 409
    finally:
        srv.shutdown()
        srv.server_close()


def test_unpinned_mobile_owner_page_never_promotes_old_guard_or_staged_source(
        monkeypatch, tmp_path):
    from scripts import m1_operator_release_cli as cli
    # An authenticated owner GET must never search staging or old Guard
    # requests to decide which release can be executed. Explicit SHA only.
    def forbid(*args, **kwargs):
        pytest.fail("status-only GET must not scan Guard approval inventory")
    monkeypatch.setattr(cli, "_guard_gate", forbid)
    ops = FakeOps()
    release = MobileOwnerRelease(SECRET, ops=ops)
    status, html = release.render("owner-phone")
    assert status == 200
    assert "現在のサービス状態" in html
    assert "稼働状態を確認できません" in html
    assert '/release/probe-post' in html
    assert '/release/request' not in html
    assert ops.mutations == []


def test_cancelled_exact_guard_request_cannot_be_approved_from_phone(monkeypatch, tmp_path):
    from scripts import m1_operator_release_cli as cli
    record = SimpleNamespace(
        status="PREPARED", release_scope_ref=SCOPE,
        candidate_authority="github-commit:" + HEAD,
        release_run_id=RUN, release_request_ref=REQUEST)
    gate = SimpleNamespace(
        registry=SimpleNamespace(get=lambda _: record),
        store=SimpleNamespace(is_cancelled=lambda run: run == RUN))
    monkeypatch.setattr(cli, "_guard_gate", lambda *_args, **_kwargs: gate)
    # The scoped candidate must be recovered before choosing its Guard ledger.
    monkeypatch.setattr(cli, "_release_scope", lambda *_args:
                        SimpleNamespace(scope_ref=SCOPE))
    ops = OwnerReleaseOperations(home=tmp_path)
    state = ops.pending(HEAD, SCOPE)
    assert state["state"] == "CANCELLED"
    fake = FakeOps()
    fake.state = "CANCELLED"
    svc = MobileOwnerRelease(SECRET, ops=fake)
    code, page = svc.render("owner-phone", HEAD)
    assert code == 409 and "取消済み" in page
    code, _ = svc.submit("approve", "owner-phone", _form(svc, "approve"))
    assert code == 409
    assert fake.mutations == []


def test_browser_release_double_tap_cannot_reenter_effect_adapter():
    fake = FakeOps()
    svc = MobileOwnerRelease(SECRET, ops=fake)
    original = fake.request
    def reentrant(head, scope, phrase):
        other_code, _ = svc.submit("request", "owner-phone", _form(svc, "request"))
        assert other_code == 409
        assert fake.mutations == []
        return original(head, scope, phrase)
    fake.request = reentrant
    code, page = svc.submit("request", "owner-phone", _form(svc, "request"))
    assert code == 200 and "/release/approve" in page
    assert fake.mutations == ["request"]


def test_mobile_pending_pins_current_guard_ledger_before_read(monkeypatch, tmp_path):
    from scripts import m1_operator_release_cli as cli
    exact = SimpleNamespace(scope_ref=SCOPE)
    visited = []
    monkeypatch.setattr(cli, "_release_scope", lambda *_: exact)
    def gate(home, *, readonly=False, scope=None):
        assert readonly and scope is exact
        visited.append(scope)
        return SimpleNamespace(
            registry=SimpleNamespace(get=lambda _: None))
    monkeypatch.setattr(cli, "_guard_gate", gate)
    ops = OwnerReleaseOperations(home=tmp_path)
    assert ops.pending(HEAD, SCOPE) is None
    assert visited == [exact]
    assert ops.pending(HEAD, "0"*64) is None
    assert visited == [exact]



class _StatusOps(FakeOps):
    """The installed owner UI serves a verified GET page without candidates."""
    def __init__(self, *, operator="API_RESPONSIVE",
                 gateway="HTTPS_AND_UPSTREAM_RESPONSIVE", source=HEAD):
        super().__init__()
        self.operator = operator
        self.gateway = gateway
        self.source = source

    def runtime_status(self):
        return {
            "operator": self.operator,
            "gateway": self.gateway,
            "gateway_source": self.source,
            "mobile_owner_get": "OWNER_AUTHENTICATED",
            "mobile_owner_post": "NOT_VERIFIED",
        }



def test_mobile_status_first_after_cleared_verified_release_requires_no_candidate():
    ops = _StatusOps()
    page = MobileOwnerRelease(SECRET, ops=ops)
    code, document = page.render("owner-phone")
    assert code == 200
    assert "現在のサービス状態" in document
    assert "Operator" in document and "API応答を確認" in document
    assert "HTTPS応答・上流応答を確認" in document
    assert HEAD in document
    assert "スマホPOST：</strong>未検証" in document
    assert "配備候補がありません" not in document
    assert '<form method="post" action="/release/probe-post">' in document
    assert '/release/request' not in document
    assert ops.mutations == []


def test_mobile_status_failure_never_claims_verified_or_triggers_effect():
    ops = _StatusOps(operator="API_UNAVAILABLE",
                     gateway="UNVERIFIED", source="NOT_VERIFIED")
    page = MobileOwnerRelease(SECRET, ops=ops)
    code, document = page.render("owner-phone")
    assert code == 200
    assert "API応答なし" in document
    assert "稼働状態を確認できません" in document
    assert "本番切替：VERIFIED" not in document
    assert "スマホPOST：</strong>未検証" in document
    assert '/release/probe-post' in document
    assert '/release/apply' not in document
    assert ops.mutations == []


def test_mobile_status_cannot_render_untrusted_runtime_as_success():
    ops = _StatusOps(operator="INVENTED_SUCCESS")
    status, html = MobileOwnerRelease(SECRET, ops=ops).render("owner-phone")
    assert status == 200
    assert "現在の実機応答を照合できません" in html
    assert "INVENTED_SUCCESS" not in html
    assert "<form" not in html


def test_explicit_immutable_sha_still_uses_original_guard_release_flow():
    ops = _StatusOps()
    page = MobileOwnerRelease(SECRET, ops=ops, now=lambda: 1700000000)
    status, html = page.render("owner-phone", HEAD)
    assert status == 200 and "/release/request" in html
    assert "REQUEST " + SCOPE[:16] in html
    assert "mobile owner POST" not in html
    assert ops.mutations == []
    # Only a valid owner scope, current token and exact phrase can submit.
    form = _form(page, "request")
    status, html = page.submit("request", "owner-phone", form)
    assert status == 200 and "/release/approve" in html
    assert ops.mutations == ["request"]


def test_owner_get_status_never_creates_guard_request_or_changes_services():
    ops = _StatusOps()
    server, service = _server(ops, _Peer())
    try:
        code, html, csp = _http(server, "GET", "/release")
        assert code == 200 and "現在のサービス状態" in html
        assert '/release/probe-post' in html
        assert '/release/approve' not in html
        assert ops.mutations == []
        code, html, csp = _http(server, "GET", "/release?sha=" + HEAD)
        assert code == 200 and "/release/request" in html
        assert ops.mutations == []
        code, html, csp = _http(
            server, "GET", "/release",
            headers={"Host": "owner-m1.example.ts.net:8793"})
        assert code == 200
    finally:
        server.shutdown()
        server.server_close()


def test_native_owner_runtime_reads_pid_bound_operator_and_gateway_without_guard(
        monkeypatch, tmp_path):
    from scripts import m1_operator_release_host as host
    from scripts import m1_mobile_gateway_bootstrap as bootstrap
    from scripts import m1_mobile_gateway_successor as successor
    from scripts import m1_operator_release_cli as cli

    def forbid(*a, **kw):
        pytest.fail("status view must not access original Guard or mutate service")
    monkeypatch.setattr(cli, "_guard_gate", forbid)
    monkeypatch.setattr(bootstrap, "_stop_and_start", forbid)
    class PhysicalOperator:
        def __init__(self, source, *, home):
            assert home == tmp_path
        def _registered(self):
            return True
        def _pid_owned(self):
            return True
        def _human(self):
            return {"status": "READY"}
    monkeypatch.setattr(host, "FixedOperatorHost", PhysicalOperator)
    stage = tmp_path / ".ai-foundation-tunnel-sources" / HEAD
    runner = stage / "scripts/run_remote_gateway.py"
    monkeypatch.setattr(bootstrap, "_owned_plist", lambda: (
        tmp_path / "gateway.plist", b"trusted",
        {"WorkingDirectory": str(stage),
         "ProgramArguments": ["/usr/bin/python3", str(runner)]}, 0o600))
    monkeypatch.setattr(bootstrap, "_running", lambda: 40)
    monkeypatch.setattr(bootstrap, "_port_owned",
                        lambda pid, *, strict_local: pid == 40 and strict_local)
    monkeypatch.setattr(successor, "_gateway_transport_state",
                        lambda: "OPERATOR_READY")
    result = OwnerReleaseOperations(home=tmp_path).runtime_status()
    assert result == {
        "operator": "API_RESPONSIVE",
        "gateway": "HTTPS_AND_UPSTREAM_RESPONSIVE",
        "gateway_source": HEAD,
        "mobile_owner_get": "OWNER_AUTHENTICATED",
        "mobile_owner_post": "NOT_VERIFIED",
    }


def test_native_runtime_fails_closed_on_wrong_gateway_listener(monkeypatch,
                                                                 tmp_path):
    from scripts import m1_operator_release_host as host
    from scripts import m1_mobile_gateway_bootstrap as bootstrap
    from scripts import m1_mobile_gateway_successor as successor
    class BrokenOperator:
        def __init__(self, source, *, home):
            pass
        def _registered(self):
            return True
        def _pid_owned(self):
            return True
        def _human(self):
            return None
    monkeypatch.setattr(host, "FixedOperatorHost", BrokenOperator)
    monkeypatch.setattr(bootstrap, "_owned_plist", lambda: (
        tmp_path / "old.plist", b"original",
        {"WorkingDirectory": str(tmp_path / HEAD),
         "ProgramArguments": []}, 0o600))
    monkeypatch.setattr(bootstrap, "_running", lambda: 40)
    monkeypatch.setattr(bootstrap, "_port_owned",
                        lambda pid, *, strict_local: False)
    monkeypatch.setattr(successor, "_gateway_transport_state",
                        lambda: pytest.fail("must not probe unowned listener"))
    row = OwnerReleaseOperations(home=tmp_path).runtime_status()
    assert row["operator"] == "API_UNAVAILABLE"
    assert row["gateway"] == "UNVERIFIED"
    assert row["gateway_source"] == "NOT_VERIFIED"
    assert row["mobile_owner_post"] == "NOT_VERIFIED"



def _post_probe(service, peer="owner-phone"):
    return {"token": [service.token("probe-post", peer, "", "")],
            "confirmed": ["yes"]}


def test_mobile_post_transport_success_is_guard_and_service_noop():
    ops = _StatusOps()
    server, mobile = _server(ops, _Peer())
    try:
        status, body, _ = _http(server, "GET", "/release")
        assert status == 200 and "/release/probe-post" in body
        status, body, _ = _http(
            server, "POST", "/release/probe-post", _post_probe(mobile))
        assert status == 200 and "OWNER_POST_TRANSPORT_VERIFIED" in body
        assert "変更は0件" in body
        assert ops.mutations == []
        assert "/release/approve" not in body
    finally:
        server.shutdown()
        server.server_close()


def test_mobile_post_transport_needs_same_owner_exact_origin_and_token():
    ops = _StatusOps()
    server, mobile = _server(ops, _Peer())
    try:
        valid = _post_probe(mobile)
        for bad_headers in (
                {"Origin": "https://attacker.invalid"},
                {"Origin": "null"},
                {"Sec-Fetch-Site": "cross-site"},
                {"Content-Type": "text/plain"},
                {"Origin": "http://owner-m1.example.ts.net:8793"}):
            assert _http(server, "POST", "/release/probe-post", valid,
                         headers=bad_headers)[0] == 403
        for bad in (
                {**valid, "confirmed": ["no"]},
                {**valid, "token": ["invalid"]},
                {**valid, "extra": ["unexpected"]},
                _post_probe(mobile, "another-phone")):
            assert _http(server, "POST", "/release/probe-post", bad)[0] == 403
        assert ops.mutations == []
    finally:
        server.shutdown()
        server.server_close()


def test_mobile_post_transport_denies_unverified_owner_even_valid_hmac():
    ops = _StatusOps()
    server, mobile = _server(ops, _Peer(value=None))
    try:
        assert _http(server, "POST", "/release/probe-post",
                     _post_probe(mobile))[0] == 403
        assert ops.mutations == []
    finally:
        server.shutdown()
        server.server_close()


def test_mobile_post_transport_expired_nonce_never_grants():
    ops = _StatusOps()
    time_now = [1700000000]
    mobile = MobileOwnerRelease(SECRET, ops=ops, now=lambda: time_now[0])
    form = _post_probe(mobile)
    assert mobile.verify_transport("owner-phone", form)[0] == 200
    time_now[0] += 301
    assert mobile.verify_transport("owner-phone", form)[0] == 403
    assert ops.mutations == []



def test_post_probe_action_can_never_enter_release_apply_state_machine():
    ops = _StatusOps()
    mobile = MobileOwnerRelease(SECRET, ops=ops)
    # Form is intentionally constructed like a release apply, but carries
    # the probe's valid HMAC. It must be rejected by the mutation dispatcher.
    form = _form(mobile, "apply")
    form["token"] = [mobile.token("probe-post", "owner-phone",
                                  HEAD, SCOPE, RUN, REQUEST)]
    code, page = mobile.submit("probe-post", "owner-phone", form)
    assert code == 400
    assert ops.mutations == []
