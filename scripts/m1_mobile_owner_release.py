"""Phone owner -> existing exact Guard/Operator release over the private tailnet.

This module adds no release registry, model permission, service or independent
approval authority. The existing verified Operator cutover code owns all effects.
Remote gateway opt-in, *live* Tailscale WhoIs, exact HTTPS Origin, bounded HMAC
form tokens and an explicit phrase are required before each mutation.
"""
from __future__ import annotations

from hashlib import sha256
from html import escape
import hmac
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
from types import SimpleNamespace
import subprocess
import threading
import time

_SHA = re.compile(r"[0-9a-f]{40}\Z")
_SCOPE = re.compile(r"[0-9a-f]{64}\Z")
_RUN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_TOKEN = re.compile(r"([0-9]{10})\.([0-9a-f]{24})\.([0-9a-f]{64})\Z")
_BIN = "/usr/local/bin/tailscale"
_ACTIONS = frozenset({"request", "approve", "apply"})
_TOKEN_ACTIONS = _ACTIONS | frozenset({"probe-post"})


class MobileReleaseDenied(PermissionError):
    pass


class TailnetOwnerIdentity:
    """Prove the request's actual Tailscale peer has the M1 owner's user ID.

    Never trust Host/X-Forwarded-For/headers or merely belonging to a tailnet.
    Tagged devices, shared nodes, proxy/public/LAN IPs and failed queries
    are not owner authentication.
    """

    def __init__(self, *, invoke=subprocess.run):
        self.invoke = invoke

    def _json(self, *argv):
        response = self.invoke(
            [_BIN, *argv], capture_output=True, text=True,
            timeout=4, check=True)
        if type(response.stdout) is not str or len(response.stdout) > 65536:
            raise MobileReleaseDenied("TAILNET_IDENTITY_UNVERIFIED")
        data = json.loads(response.stdout)
        if type(data) is not dict:
            raise MobileReleaseDenied("TAILNET_IDENTITY_UNVERIFIED")
        return data

    def serve_owner_login(self, login):
        """Validate Serve's login against the *current* M1 Tailscale owner.

        The caller MUST first prove this request came through a strictly
        loopback-bound, opt-in Tailscale Serve backend. A header from a LAN
        socket, direct tailnet socket, or shared peer is NEVER authority.
        """
        if (type(login) is not str or not (3 <= len(login) <= 254)
                or "@" not in login or any(
                    ord(c) < 33 or ord(c) > 126 for c in login)):
            return None
        try:
            status = self._json("status", "--json")
            me = status.get("Self")
            users = status.get("User")
            if (type(me) is not dict or type(users) is not dict
                    or me.get("Tags") or status.get("BackendState") != "Running"):
                return None
            user_id = me.get("UserID")
            if (type(user_id) not in (str, int)
                    or str(user_id) in ("", "0")):
                return None
            profile = users.get(str(user_id))
            if (type(profile) is not dict
                    or str(profile.get("ID")) != str(user_id)
                    or type(profile.get("LoginName")) is not str
                    or profile["LoginName"] != login):
                return None
            # Keep the HMAC token tied to a verified owner identity type,
            # not a forwarded IP address or an unverified browser hint.
            return "serve-owner:" + str(user_id)
        except (OSError, ValueError, TypeError, KeyError,
                json.JSONDecodeError, subprocess.SubprocessError,
                MobileReleaseDenied):
            return None

    def owner_peer(self, ip):
        try:
            address = ipaddress.ip_address(ip)
            # Tailscale's CGNAT IPv4 range and its ULA IPv6 block.
            is_tailnet = (
                address in ipaddress.ip_network("100.64.0.0/10")
                or address in ipaddress.ip_network("fd7a:115c:a1e0::/48"))
            if not is_tailnet:
                return None
            status = self._json("status", "--json")
            who = self._json("whois", "--json", str(address))
            self_node, peer, profile = status.get("Self"), who.get("Node"), who.get("UserProfile")
            if any(type(value) is not dict for value in (self_node, peer, profile)):
                return None
            owner_id = self_node.get("UserID")
            node_user = peer.get("User")
            user_profile_id = profile.get("ID")
            # A user-authenticated phone must belong to the same owner as M1.
            if (type(owner_id) not in (int, str) or str(owner_id) in ("", "0")
                    or str(owner_id) != str(node_user)
                    or str(owner_id) != str(user_profile_id)
                    or not peer.get("ID") or peer.get("Tags")
                    or peer.get("Sharer")
                    or (self_node.get("ID") and
                        str(peer["ID"]) == str(self_node["ID"]))):
                return None
            addresses = peer.get("Addresses")
            if type(addresses) is not list or len(addresses) > 16:
                return None
            # Tailscale Node.Addresses are CIDR prefixes (/32 or /128)
            # rather than necessarily bare IP strings.
            exact_addresses = []
            for raw in addresses:
                if type(raw) is not str:
                    return None
                network = ipaddress.ip_network(raw, strict=False)
                if network.prefixlen == network.max_prefixlen:
                    exact_addresses.append(network.network_address)
            if address not in exact_addresses:
                return None
            return str(peer["ID"])
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError,
                subprocess.SubprocessError, MobileReleaseDenied):
            return None


class OwnerReleaseOperations:
    """Adapter to the *single* preexisting verified CLI/Guard state machine."""

    def __init__(self, *, home=None):
        self.home = Path.home() if home is None else Path(home)

    def runtime_status(self):
        """Read current installed services without requiring a NEW candidate.

        Never load old PREPARED Guard receipts, grant approval, show private
        launchd arguments or invent a mobile POST acceptance result. Each
        service's result is independent of its release-planning inventory.
        """
        result = {"operator": "UNVERIFIED", "gateway": "UNVERIFIED",
                  "gateway_source": "NOT_VERIFIED",
                  "mobile_owner_get": "OWNER_AUTHENTICATED",
                  "mobile_owner_post": "NOT_VERIFIED"}
        try:
            from scripts.m1_operator_release_host import FixedOperatorHost
            installed = FixedOperatorHost(
                Path(__file__).resolve().parents[1], home=self.home)
            if installed._registered() and installed._pid_owned():
                result["operator"] = (
                    "API_RESPONSIVE" if type(installed._human()) is dict
                    else "API_UNAVAILABLE")
        except (OSError, ValueError, TypeError, RuntimeError,
                PermissionError, subprocess.SubprocessError):
            pass
        try:
            from scripts import m1_mobile_gateway_bootstrap as bootstrap
            from scripts import m1_mobile_gateway_successor as successor
            _, raw, doc, _ = bootstrap._owned_plist()
            pid = bootstrap._running()
            if pid is not None and bootstrap._port_owned(pid, strict_local=True):
                upstream = successor._gateway_transport_state()
                if upstream == "OPERATOR_READY":
                    result["gateway"] = "HTTPS_AND_UPSTREAM_RESPONSIVE"
                elif upstream == "OPERATOR_UNAVAILABLE":
                    result["gateway"] = "HTTPS_RESPONSIVE_UPSTREAM_UNAVAILABLE"
                # Never guess the loaded source from the newest staged dir.
                # Report the installed plist's fixed runner binding only.
                root = self.home / ".ai-foundation-tunnel-sources"
                directory = doc.get("WorkingDirectory")
                args = doc.get("ProgramArguments")
                if (type(directory) is str and type(args) is list
                        and all(type(a) is str for a in args)):
                    candidate = Path(directory)
                    script = str(candidate / "scripts/run_remote_gateway.py")
                    if (candidate.parent == root
                            and _SHA.fullmatch(candidate.name)
                            and args.count(script) == 1
                            and not candidate.is_symlink()):
                        result["gateway_source"] = candidate.name
        except (OSError, ValueError, TypeError, KeyError, RuntimeError,
                PermissionError, subprocess.SubprocessError):
            pass
        return result

    def _cli(self, head, operation, *, phrase="", run_id=None, request_ref=None):
        if type(head) is not str or _SHA.fullmatch(head) is None:
            raise MobileReleaseDenied("EXACT_RELEASE_HEAD_REQUIRED")
        from scripts import m1_operator_release_cli as cli
        args = SimpleNamespace(
            operation=operation, expected_head=head,
            canon_revision=None, run_id=run_id, request_ref=request_ref)
        return cli.run(
            args, trusted_source_root=self.home / ".ai-foundation-tunnel-sources" / head,
            confirmer=lambda _description, challenge: (
                type(phrase) is str and
                secrets.compare_digest(phrase, challenge)))

    def observe(self, head):
        inspect = self._cli(head, "inspect")
        readiness = self._cli(head, "preflight")
        if (inspect.get("status") != "OBSERVED_NO_EFFECT"
                or readiness.get("status") != "OBSERVED_NO_EFFECT"
                or readiness.get("scope_ref") != inspect.get("scope_ref")):
            raise MobileReleaseDenied("OWNER_RELEASE_PREFLIGHT_UNVERIFIED")
        return {
            "head": head, "scope_ref": inspect["scope_ref"],
            "preflight_ok": readiness.get("preflight_ok") is True,
            "release_state": readiness.get("release_state"),
            "verified_incumbent_loaded":
                readiness.get("verified_incumbent_loaded") is True,
        }

    def pending(self, head, scope):
        from scripts import m1_operator_release_cli as cli
        source = self.home / ".ai-foundation-tunnel-sources" / head
        exact = cli._release_scope(source, head, self.home)
        if exact.scope_ref != scope:
            return None
        # Historical owner-main registries can contain multiple PREPARED
        # records. Always read this candidate's exact immutable ledger.
        gate = cli._guard_gate(self.home, readonly=True, scope=exact)
        record = gate.registry.get("m1-operator")
        if (record is None or record.status not in ("PREPARED", "VERIFIED")
                or record.release_scope_ref != scope
                or record.candidate_authority != "github-commit:" + head):
            return None
        run = record.release_run_id
        request = record.release_request_ref
        if (type(run) is not str or _RUN.fullmatch(run) is None
                or type(request) is not str or _SCOPE.fullmatch(request) is None):
            return None
        if record.status == "VERIFIED":
            return {"run_id": run, "request_ref": request, "state": "VERIFIED"}
        if gate.store.is_cancelled(run):
            return {"run_id": run, "request_ref": request, "state": "CANCELLED"}
        verified = gate.verify(exact, run, request, require_approved=False)
        if verified.get("ok") is not True or verified.get("scope_ref") != scope:
            return None
        return {"run_id": run, "request_ref": request,
                "state": "APPROVED" if verified.get("approved") is True else "PENDING"}

    def request(self, head, scope, phrase):
        observed = self.observe(head)
        if observed["scope_ref"] != scope or not observed["preflight_ok"]:
            raise MobileReleaseDenied("OWNER_RELEASE_PREFLIGHT_UNVERIFIED")
        return self._cli(head, "request", phrase=phrase)

    def approve(self, head, scope, run_id, request_ref):
        """Owner browser decision via the *existing* Guard decision API."""
        current = self.observe(head)
        item = self.pending(head, scope)
        if (current["scope_ref"] != scope or item is None
                or item["run_id"] != run_id or item["request_ref"] != request_ref
                or item["state"] != "PENDING"):
            raise MobileReleaseDenied("EXACT_PENDING_RELEASE_REQUIRED")
        from scripts import m1_operator_release_cli as cli
        from ai_foundation.guard import GuardCore
        from ai_foundation.operator_actions import OperatorActions
        from ai_foundation.store import SQLiteGuardStore
        guard_path, _ = cli._guard_path(self.home)
        store = SQLiteGuardStore(guard_path)
        actions = OperatorActions(GuardCore(store.runtime_state(), store=store))
        outcome = actions.approve_pending(run_id, request_ref)
        if outcome.ok is not True or outcome.status != "APPROVED":
            raise MobileReleaseDenied("EXACT_GUARD_APPROVAL_NOT_VERIFIED")
        return {"status": "GUARD_APPROVED", "service_mutations": 0}

    def apply(self, head, scope, run_id, request_ref, phrase):
        current = self.observe(head)
        item = self.pending(head, scope)
        if (current["scope_ref"] != scope or not current["preflight_ok"]
                or item is None or item["run_id"] != run_id
                or item["request_ref"] != request_ref
                or item["state"] != "APPROVED"):
            raise MobileReleaseDenied("EXACT_APPROVED_RELEASE_REQUIRED")
        outcome = self._cli(head, "apply", phrase=phrase,
                            run_id=run_id, request_ref=request_ref)
        if (outcome.get("status") != "VERIFIED"
                or outcome.get("scope_ref") != scope
                or outcome.get("guard_approved") is not True):
            raise MobileReleaseDenied("OPERATOR_RELEASE_READBACK_UNVERIFIED")
        return outcome


class MobileOwnerRelease:
    """Responsive owner release view; caller proves tailnet identity per request.

    The HMAC is only CSRF/freshness protection. It does not authenticate a
    device, create Guard approval, or grant privilege without WhoIs/Origin.
    """
    def __init__(self, secret, *, ops=None, now=time.time):
        if type(secret) is not str or len(secret) < 32:
            raise ValueError("MOBILE_RELEASE_SECRET_REQUIRED")
        self.secret = secret.encode()
        self.ops = OwnerReleaseOperations() if ops is None else ops
        self.now = now
        # Guard approval and launchd cutover are effectful. A concurrent
        # double tap must never start two validations / cutover transactions.
        self._effect_lock = threading.Lock()

    def _message(self, action, node_id, head, scope, run_id, request_ref, timestamp, nonce):
        fields = ("mobile-release-v1", action, node_id, head, scope,
                  run_id, request_ref, str(timestamp), nonce)
        return "\0".join(fields).encode()

    def token(self, action, peer, head, scope, run_id="", request_ref=""):
        if action not in _TOKEN_ACTIONS:
            raise MobileReleaseDenied("MOBILE_RELEASE_ACTION_INVALID")
        ts = int(self.now())
        nonce = secrets.token_hex(12)
        mac = hmac.new(
            self.secret,
            self._message(action, peer, head, scope, run_id, request_ref, ts, nonce),
            sha256).hexdigest()
        return f"{ts}.{nonce}.{mac}"

    def valid(self, token, action, peer, head, scope, run_id="", request_ref=""):
        if type(token) is not str or type(peer) is not str:
            return False
        m = _TOKEN.fullmatch(token)
        if m is None:
            return False
        ts = int(m[1])
        age = self.now() - ts
        if age < -10 or age > 300:
            return False
        mac = hmac.new(
            self.secret,
            self._message(action, peer, head, scope, run_id, request_ref, ts, m[2]),
            sha256).hexdigest()
        return hmac.compare_digest(mac, m[3])

    @staticmethod
    def _fields(form, expected):
        return (type(form) is dict and set(form) == expected
                and all(type(value) is list and len(value) == 1
                        and type(value[0]) is str for value in form.values()))

    def _document(self, inner):
        return (
            '<!doctype html><html lang="ja"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>AI-Foundation 本番切替</title>'
            '<style>body{font:16px system-ui;max-width:660px;margin:0 auto;'
            'padding:16px;line-height:1.6;background:#f7f8fb;color:#161c29}'
            'main{background:white;border:1px solid #d7dce7;border-radius:16px;'
            'padding:20px}h1{font-size:1.4rem}code{overflow-wrap:anywhere}'
            'input,button{font:inherit;min-height:48px;max-width:100%;box-sizing:border-box}'
            'input[type=text]{width:100%;padding:8px}button{padding:8px 16px}'
            'form{border-top:1px solid #d7dce7;padding-top:16px;margin-top:20px}'
            'label{display:block;margin:8px 0}p{overflow-wrap:anywhere}</style>'
            '<main><h1>AI-Foundation 本番切替</h1>'
            '<p><a href="/">ダッシュボードへ戻る</a></p>' + inner +
            '</main></html>')

    def _render_current_status(self, peer, notice):
        """Status-first UI: no Guard work and no implicit new release form."""
        try:
            status_fn = getattr(self.ops, "runtime_status", None)
            current = (status_fn() if callable(status_fn) else {
                "operator": "UNVERIFIED", "gateway": "UNVERIFIED",
                "gateway_source": "NOT_VERIFIED"})
            if type(current) is not dict:
                raise MobileReleaseDenied("CURRENT_RUNTIME_READBACK_INVALID")
            operator = current.get("operator")
            gateway = current.get("gateway")
            source = current.get("gateway_source")
            if operator not in ("API_RESPONSIVE", "API_UNAVAILABLE", "UNVERIFIED"):
                raise MobileReleaseDenied("OPERATOR_STATUS_UNTRUSTED")
            if gateway not in ("HTTPS_AND_UPSTREAM_RESPONSIVE",
                               "HTTPS_RESPONSIVE_UPSTREAM_UNAVAILABLE",
                               "UNVERIFIED"):
                raise MobileReleaseDenied("GATEWAY_STATUS_UNTRUSTED")
            labels = {
                "API_RESPONSIVE": "API応答を確認",
                "API_UNAVAILABLE": "API応答なし（要確認）",
                "UNVERIFIED": "稼働状態を確認できません",
                "HTTPS_AND_UPSTREAM_RESPONSIVE": "HTTPS応答・上流応答を確認",
                "HTTPS_RESPONSIVE_UPSTREAM_UNAVAILABLE":
                    "HTTPS応答あり／上流Operatorは応答なし",
            }
            body = ('<h2>現在のサービス状態</h2>'
                    '<p><strong>Operator：</strong>' +
                    escape(labels[operator]) + '</p>'
                    '<p><strong>Gateway：</strong>' +
                    escape(labels[gateway]) + '</p>')
            if type(source) is str and _SHA.fullmatch(source):
                body += ('<p><strong>Gateway起動定義のソース：</strong>'
                         '<code>' + escape(source) + '</code></p>')
            if notice:
                body += '<p><strong>' + escape(notice) + '</strong></p>'
            body += (
                '<p>この表示は本人確認済みのGET経路と、M1内の読取専用応答確認です。'
                'Guardのリリース完了記録、スマホからのPOST実行成功、'
                '新しい配備の許可を意味しません。</p>'
                '<p><strong>スマホPOST：</strong>未検証</p>'
                '<form method="post" action="/release/probe-post">' 
                '<input type="hidden" name="token" value="' +
                escape(self.token("probe-post", peer, "", ""), quote=True) + '">'
                '<label><input type="checkbox" name="confirmed" value="yes" required>'
                ' 本人確認付きHTTPS POST通信のみを検査します（Guard・サービス変更なし）</label>'
                '<button type="submit">POST疎通を検査</button></form>'
                '<p>新規の本番切替は、対象の40桁コミットを指定した'
                '<code>/release?sha=...</code>からのみ確認できます。'
                '既存の承認を使い回しません。</p>')
            return 200, self._document(body)
        except (OSError, ValueError, RuntimeError, PermissionError):
            return 200, self._document(
                '<h2>現在のサービス状態</h2>'
                '<p>現在の実機応答を照合できません。'
                'これは配備候補の欠落を示すものではありません。</p>'
                '<p>新規配備・承認操作はこの画面から実行しません。</p>')

    def render(self, peer, head="", notice=""):
        """Bare URL is read-only status; only an exact ?sha can plan release.

        Never infer a release target from CI staging, prior Guard receipts
        or the currently running service's source. The caller must explicitly
        pin a new SHA before any request/approve/apply form exists.
        """
        if not head:
            return self._render_current_status(peer, notice)
        try:
            if type(head) is not str or _SHA.fullmatch(head) is None:
                raise MobileReleaseDenied("EXACT_RELEASE_HEAD_REQUIRED")
            state = self.ops.observe(head)
            scope = state["scope_ref"]
            if type(scope) is not str or _SCOPE.fullmatch(scope) is None:
                raise MobileReleaseDenied("OWNER_RELEASE_SCOPE_UNVERIFIED")
            item = self.ops.pending(head, scope)
            body = ("<p><strong>対象コミット：</strong><code>" + escape(head) +
                    "</code></p><p><strong>承認スコープ：</strong><code>" +
                    escape(scope) + "</code></p>")
            if notice:
                body += "<p><strong>" + escape(notice) + "</strong></p>"
            if item is not None and item["state"] == "VERIFIED":
                return 200, self._document(body +
                    "<p>この申請はVERIFIED。承認は消費済みです。"
                    "再実行できません。最新の稼働状態は /release で確認してください。</p>")
            if not state["preflight_ok"]:
                return 409, self._document(body +
                    "<p>この候補の配備前条件が一致しません。新しい操作はできません。</p>"
                    "<p>既存のサービス稼働状況は /release から確認してください。</p>")
            if item is not None and item["state"] == "CANCELLED":
                return 409, self._document(body +
                    "<p>この申請はDENYまたは取消済みです。適用できません。</p>")
            if item is None:
                action, caption = "request", "1. Guard承認を申請"
                phrase, run, request = "REQUEST " + scope[:16], "", ""
                body += ("<p>新規申請は未登録です。現行リリースを"
                         "自動で再実行することはありません。</p>")
            else:
                run, request = item["run_id"], item["request_ref"]
                body += ("<p><strong>申請ID：</strong><code>" +
                         escape(run) + "</code></p>"
                         "<p><strong>承認参照：</strong><code>" +
                         escape(request) + "</code></p>")
                if item["state"] == "PENDING":
                    action, caption = "approve", "2. Guard承認"
                    phrase = "AUTHORIZE " + scope[:16]
                    body += "<p>保存済みの同一Guard申請を本人が承認します。</p>"
                elif item["state"] == "APPROVED":
                    action, caption = "apply", "3. 本番切替・読戻し"
                    phrase = "APPLY " + scope[:16]
                    body += ("<p>Guard承認済みです。切替前に実体を再照合し、"
                             "失敗時は既存のロールバックを使用します。</p>")
                else:
                    raise MobileReleaseDenied("OWNER_RELEASE_STATE_UNVERIFIED")
            body += (
                '<form method="post" action="/release/' + action + '">'
                '<input type="hidden" name="head" value="' + escape(head, quote=True) + '">'
                '<input type="hidden" name="scope" value="' + escape(scope, quote=True) + '">'
                '<input type="hidden" name="run_id" value="' + escape(run, quote=True) + '">'
                '<input type="hidden" name="request_ref" value="' + escape(request, quote=True) + '">'
                '<input type="hidden" name="token" value="' +
                escape(self.token(action, peer, head, scope, run, request), quote=True) + '">'
                '<h2>' + escape(caption) + '</h2>'
                '<label>確認文字列：<code>' + escape(phrase) + '</code></label>'
                '<input type="text" required name="confirmation" autocomplete="off" '
                'autocapitalize="off" spellcheck="false" maxlength="100" '
                'placeholder="上の文字列を入力">'
                '<label><input type="checkbox" name="confirmed" value="yes" required> '
                '対象コミットと操作を確認しました</label>'
                '<button type="submit">' + escape(caption) + '</button></form>')
            return 200, self._document(body)
        except (OSError, ValueError, RuntimeError, PermissionError):
            return 409, self._document(
                "<p>対象コミットの本番配備検査に失敗しました。"
                "現在のサービス状態は /release で確認してください。</p>")

    def verify_transport(self, peer, form):
        """Exercise the real owner/Origin/HMAC POST, without any Guard effect.

        Gateway already checked WhoIs, exact HTTPS Origin, content type,
        fixed payload length and non-cross-site Fetch metadata. This view
        adds a short-lived peer-bound token and explicit owner click. No
        durable approval/receipt, task mutation or service restart is issued.
        """
        if (not self._fields(form, {"token", "confirmed"})
                or form["confirmed"] != ["yes"]
                or not self.valid(form["token"][0], "probe-post", peer, "", "")):
            return 403, self._document(
                "<h2>POST通信の本人確認に失敗</h2>"
                "<p>ページを再表示して検査してください。Guardは変更していません。</p>")
        return 200, self._document(
            "<h2>スマホPOST通信を確認</h2>"
            "<p><strong>OWNER_POST_TRANSPORT_VERIFIED</strong></p>"
            "<p>本人認証・同一Origin・短時間トークンを通過しました。"
            "これは通信経路だけの検査であり、Guard承認・本番切替・"
            "変更操作の成功を意味しません。変更は0件です。</p>"
            '<p><a href="/release">現在のサービス状態へ戻る</a></p>')

    def submit(self, action, peer, form):
        if not self._effect_lock.acquire(blocking=False):
            return 409, self._document(
                "<p>申請・承認・適用を処理中です。連打せず状態を再読込してください。</p>")
        try:
            return self._submit_serialized(action, peer, form)
        finally:
            self._effect_lock.release()

    def _submit_serialized(self, action, peer, form):
        expected = {"head", "scope", "run_id", "request_ref",
                    "token", "confirmation", "confirmed"}
        if (action not in _ACTIONS or not self._fields(form, expected)):
            return 400, self._document("<p>入力形式が不正です。</p>")
        head, scope, run, request, token, phrase, confirmed = (
            form[k][0] for k in ("head", "scope", "run_id", "request_ref",
                                "token", "confirmation", "confirmed"))
        if (confirmed != "yes" or _SHA.fullmatch(head) is None
                or _SCOPE.fullmatch(scope) is None
                or not self.valid(token, action, peer, head, scope, run, request)):
            return 403, self._document("<p>操作の本人確認または有効期限が一致しません。</p>")
        if action == "request":
            expected_phrase = "REQUEST " + scope[:16]
            if run or request:
                return 409, self._document("<p>未使用の申請である必要があります。</p>")
        elif action == "approve":
            expected_phrase = "AUTHORIZE " + scope[:16]
        else:
            expected_phrase = "APPLY " + scope[:16]
        if (not secrets.compare_digest(phrase, expected_phrase)
                or (action != "request" and (
                    _RUN.fullmatch(run) is None or _SCOPE.fullmatch(request) is None))):
            return 403, self._document("<p>承認対象と確認文字列が一致しません。</p>")
        try:
            # Re-evaluate the immutable target and persisted release state
            # before even calling the original effectful Guard/launchd adapter.
            # The adapter independently rechecks too, but a stale mobile form
            # must never make a second invocation after verified cutover.
            observed = self.ops.observe(head)
            if observed.get("scope_ref") != scope:
                raise MobileReleaseDenied("RELEASE_SCOPE_CHANGED")
            current = self.ops.pending(head, scope)
            if action == "request":
                if current is not None or observed.get("preflight_ok") is not True:
                    raise MobileReleaseDenied("RELEASE_REQUEST_ALREADY_PREPARED")
            elif (current is None
                  or current.get("run_id") != run
                  or current.get("request_ref") != request
                  or current.get("state") != (
                      "PENDING" if action == "approve" else "APPROVED")):
                raise MobileReleaseDenied("MOBILE_RELEASE_STATE_CHANGED")
            if action == "request":
                result = self.ops.request(head, scope, phrase)
                ok = result.get("status") == "WAITING_HUMAN"
                note = "Guardへの承認申請を保存しました"
            elif action == "approve":
                result = self.ops.approve(head, scope, run, request)
                ok = result.get("status") == "GUARD_APPROVED"
                note = "Guard承認を保存しました"
            else:
                result = self.ops.apply(head, scope, run, request, phrase)
                ok = result.get("status") == "VERIFIED"
                note = "Operator本番切替とPID読戻しが完了しました"
            if not ok:
                return 409, self._document(
                    "<p>処理が完了した証拠がありません。再送せず現在の状態を確認してください。</p>")
            return self.render(peer, head, note)
        except (OSError, ValueError, RuntimeError, PermissionError):
            # A failed/uncertain cutover may have changed the real world.
            # Never retry the effect or claim no service mutation on failure.
            return 409, self._document(
                "<p>結果が未確定です。再送せず、配備台帳と起動プロセスを確認してください。</p>")
