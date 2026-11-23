"""Offline tests of native OpenCode stdio boundary. Never call Console."""
from dataclasses import replace
import http.client
import io
import json
import threading
import time
from urllib.error import HTTPError

import pytest

from ai_foundation.next_service_preflight import OpenCodeReviewEvidence
from ai_foundation.opencode_live_stdio import (
    _MAX_FRAME, _StdioGateway, _read_frame, _write_frame,
    NoRedirect, PinnedStdioOpenCodeHostPort, console_sender,
)
from ai_foundation.opencode_harness_service import OPENCODE_MODEL

IMAGE = "sha256:" + "a" * 64
SHA = "b" * 64


def reviewed():
    return OpenCodeReviewEvidence(
        model=OPENCODE_MODEL,
        observed_at=time.time(),
        official_model_revision_sha256="c" * 64,
        free_model_priced_zero=True,
        actual_account_free=True,
        no_payment_method=False,
        no_prepaid_balance=False,
        auto_recharge_off=True,
        go_extra_usage_off=True,
        paid_fallback_off=True,
        background_model_free_only=True,
        isolated_binary_verified=True,
        private_server_verified=True,
        no_shared_auth_or_project=True,
        native_sandbox_verified=True,
        exact_model_network_enforcement_verified=True,
        workspace_zero_budget_verified=True,
    )


def test_frame_round_trip_without_newline_or_json_guess():
    b = io.BytesIO()
    _write_frame(b, b"R", b'{"model":"hy4-flash-free"}')
    b.seek(0)
    assert _read_frame(b) == (b"R", b'{"model":"hy4-flash-free"}')
    for kind, blob in ((b"?", b"hello"), (b"P", b"x" * (_MAX_FRAME + 1))):
        with pytest.raises(ValueError, match="FRAME_DENIED"):
            _write_frame(io.BytesIO(), kind, blob)


@pytest.mark.parametrize("blob", [
    b"", b"R", b"R\x00\x00\x00\x05abc",
    b"R\xff\xff\xff\xff",
])
def test_truncated_or_unbounded_host_frames_denied(blob):
    with pytest.raises(ValueError, match="FRAME_"):
        _read_frame(io.BytesIO(blob))


def test_release_gate_required_even_with_zero_budget_review():
    kwargs = dict(image_id=IMAGE, binary_sha256=SHA,
                  docker_binary="/usr/local/bin/docker",
                  review=reviewed(), api_key_supplier=lambda: "test-only-key")
    with pytest.raises(PermissionError, match="RELEASE_NOT_APPROVED"):
        PinnedStdioOpenCodeHostPort(**kwargs)
    with pytest.raises(PermissionError):
        PinnedStdioOpenCodeHostPort(**dict(
            kwargs, review=replace(reviewed(), workspace_zero_budget_verified=False)))
    with pytest.raises(PermissionError):
        PinnedStdioOpenCodeHostPort(**dict(
            kwargs, review=replace(reviewed(), auto_recharge_off=False)),
            release_gate_permitted=True)
    with pytest.raises(PermissionError):
        PinnedStdioOpenCodeHostPort(**dict(kwargs, image_id="latest"),
                                   release_gate_permitted=True)
    with pytest.raises(PermissionError):
        PinnedStdioOpenCodeHostPort(**dict(kwargs, docker_binary="/bin/sh"),
                                   release_gate_permitted=True)


def test_live_port_is_not_default_registered():
    from ai_foundation.harness_provider_adapter import default_harness_services
    assert default_harness_services().providers() == ("GROQ",)


def test_console_host_sender_no_redirect_proxy_or_retry(monkeypatch):
    import ai_foundation.opencode_live_stdio as live
    calls = []
    class Reply:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self, n):
            assert n == _MAX_FRAME + 1
            return b'data: [DONE]\n\n'
    class Opener:
        def open(self, req, *, timeout):
            calls.append((req, timeout))
            assert timeout == 30
            return Reply()
    def build(*handlers):
        assert any(type(h) is live.urllib.request.ProxyHandler
                   and h.proxies == {} for h in handlers)
        assert any(type(h) is NoRedirect for h in handlers)
        return Opener()
    monkeypatch.setattr(live.urllib.request, "build_opener", build)
    sender = console_sender(lambda: "only-on-host-test-key")
    assert sender(live.UPSTREAM, b'{"model":"hy4-flash-free"}') == b'data: [DONE]\n\n'
    assert len(calls) == 1
    assert calls[0][0].get_header("Authorization") == "Bearer only-on-host-test-key"
    assert NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.invalid") is None
    with pytest.raises(PermissionError, match="NOT_ALLOWED"):
        sender("https://evil.invalid", b"{}")
    assert len(calls) == 1


def test_cli_loopback_server_denies_all_non_model_methods():
    server = _StdioGateway()
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        for method, path in (("GET", "/v1/models"),
                             ("POST", "/other"),
                             ("DELETE", "/v1/chat/completions")):
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
            conn.request(method, path, body=b"{}")
            resp = conn.getresponse()
            assert resp.status in (403, 405)
            assert resp.read() == b'{"error":"DENIED"}'
            conn.close()
        assert server.accepted == 0
        assert server.denied == 3
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def test_sender_missing_or_invalid_secret_never_dispatches(monkeypatch):
    import ai_foundation.opencode_live_stdio as live
    def forbidden(*args):
        raise AssertionError("unexpected outbound request")
    monkeypatch.setattr(live.urllib.request, "build_opener", forbidden)
    for supplier in (None, lambda: "", lambda: "bad\nheader"):
        if supplier is None:
            with pytest.raises(ValueError, match="SUPPLIER"):
                console_sender(supplier)
            continue
        with pytest.raises(PermissionError, match="CREDENTIAL_UNAVAILABLE"):
            console_sender(supplier)(live.UPSTREAM, b"{}")


@pytest.mark.parametrize("http_status, expected", [
    (402, "OPENCODE_UPSTREAM_NO_CREDITS"),
    (403, "OPENCODE_FREE_ONLY_CLIENT_DENIED"),
    (429, "OPENCODE_WORKSPACE_BUDGET_OR_RATE_DENIED"),
    (401, "OPENCODE_UPSTREAM_HTTP_DENIED"),
    (503, "OPENCODE_UPSTREAM_HTTP_DENIED"),
])
def test_console_http_denials_are_terminal_without_paid_fallback(
        monkeypatch, http_status, expected):
    import ai_foundation.opencode_live_stdio as live
    attempts = []
    class FakeOpener:
        def open(self, req, *, timeout):
            attempts.append((req.full_url, timeout))
            raise HTTPError(req.full_url, http_status, "denied", {}, None)
    monkeypatch.setattr(
        live.urllib.request, "build_opener",
        lambda *handlers: FakeOpener())
    sender = console_sender(lambda: "host-only-test-key")
    with pytest.raises(PermissionError, match=expected):
        sender(live.UPSTREAM, b'{"model":"hy4-flash-free"}')
    assert attempts == [(live.UPSTREAM, 30)]
