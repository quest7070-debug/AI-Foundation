"""No-network unit tests for OpenCode Console's exact-model host egress fence."""
import hashlib
import json

import pytest

import ai_foundation.opencode_console_egress as subject
from ai_foundation.opencode_console_egress import (
    UPSTREAM, FREE_MODEL_ID, ReviewedOutboundCodeScope, OneShotOpenCodeModelFence,
)

PUBLIC = "Write a public Python add(x, y) function with no imports or tools."
TOOLS = [{"type": "function", "function": {"name": "reviewed_builtin",
                                      "description": "public",
                                      "parameters": {"type": "object",
                                                     "properties": {}}}}]


def body(**edits):
    content = {
        "model": FREE_MODEL_ID,
        "messages": [
            {"role": "system", "content": "S" * 1550},
            {"role": "user", "content": '"' + PUBLIC + '"'},
        ],
        "stream": True,
        "tools": TOOLS,
        "max_completion_tokens": 256,
    }
    content.update(edits)
    return json.dumps(content).encode()


def gateway(monkeypatch):
    pin = hashlib.sha256(json.dumps(
        TOOLS, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
    monkeypatch.setattr(subject, "_REVIEWED_TOOL_DIGEST", pin)
    calls = []
    fence = OneShotOpenCodeModelFence(
        ReviewedOutboundCodeScope(PUBLIC),
        upstream_sender=lambda url, data: calls.append((url, data)) or b'{"choices":[]}')
    return fence, calls


def test_exact_reviewed_cli_request_is_single_shot(monkeypatch):
    fence, calls = gateway(monkeypatch)
    response = fence.send_once(method="POST", url=UPSTREAM, raw=body())
    assert response == b'{"choices":[]}'
    assert calls == [(UPSTREAM, body())]
    with pytest.raises(PermissionError, match="ONCE_ONLY"):
        fence.send_once(method="POST", url=UPSTREAM, raw=body())
    assert len(calls) == 1
    assert fence.receipt() == {
        "attempted": True, "accepted": 1, "denied": 1,
        "model": FREE_MODEL_ID, "external_sender_verified": False,
    }


@pytest.mark.parametrize("changes", [
    {"model": "glm-5.3-flash"},
    {"model": "opencode/auto"},
    {"model": "gpt-6-astra"},
    {"fallback_models": ["glm-5.3-flash"]},
    {"tools": [{"type": "shell", "name": "bash"}]},
    {"messages": [{"role": "user", "content": "private"}]},
    {"messages": [{"role": "system", "content": "unknown"},
                  {"role": "user", "content": "private"}]},
    {"tool_choice": {"type": "function", "function": {"name": "bash"}}},
    {"max_completion_tokens": 999999},
    {"stream_options": {"include_usage": False}},
    {"temperature": True},
])
def test_paid_or_unreviewed_requests_never_reach_network(monkeypatch, changes):
    fence, calls = gateway(monkeypatch)
    with pytest.raises(PermissionError):
        fence.send_once(method="POST", url=UPSTREAM, raw=body(**changes))
    assert calls == []
    assert fence.receipt()["denied"] == 1


def test_endpoint_and_duplicate_json_bodies_denied_without_egress(monkeypatch):
    fence, calls = gateway(monkeypatch)
    with pytest.raises(PermissionError, match="ENDPOINT_DENIED"):
        fence.send_once(method="POST", url="https://other.example", raw=body())
    assert calls == []
    fence, calls = gateway(monkeypatch)
    with pytest.raises(PermissionError, match="MALFORMED_JSON"):
        fence.send_once(method="POST", url=UPSTREAM,
                        raw=b'{"model":"hy4-flash-free","model":"paid"}')
    assert calls == []
    fence, calls = gateway(monkeypatch)
    with pytest.raises(PermissionError, match="ENDPOINT_DENIED"):
        fence.send_once(method="GET", url=UPSTREAM, raw=body())
    assert calls == []


def test_response_size_violation_is_uncertain_and_never_retried(monkeypatch):
    pin = hashlib.sha256(json.dumps(
        TOOLS, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
    monkeypatch.setattr(subject, "_REVIEWED_TOOL_DIGEST", pin)
    calls = []
    fence = OneShotOpenCodeModelFence(
        ReviewedOutboundCodeScope(PUBLIC),
        upstream_sender=lambda url, raw: calls.append(True) or b'x' * 262145)
    with pytest.raises(RuntimeError, match="RESPONSE_UNUSABLE"):
        fence.send_once(method="POST", url=UPSTREAM, raw=body())
    assert calls == [True]
    assert fence.receipt()["accepted"] == 0
    with pytest.raises(PermissionError, match="ONCE_ONLY"):
        fence.send_once(method="POST", url=UPSTREAM, raw=body())
    assert calls == [True]


def test_fence_does_not_claim_billing_or_native_network_attestation():
    with pytest.raises(ValueError, match="REVIEWED_FREE_SCOPE"):
        ReviewedOutboundCodeScope(PUBLIC, model="gpt-6-astra")
    with pytest.raises(ValueError, match="REVIEWED_FREE_SCOPE"):
        ReviewedOutboundCodeScope("")
    fence = OneShotOpenCodeModelFence(
        ReviewedOutboundCodeScope(PUBLIC),
        upstream_sender=lambda url, raw: b"")
    assert fence.receipt()["external_sender_verified"] is False
    assert fence.receipt()["accepted"] == 0


def test_offline_verified_acp_envelope_reuses_one_shot_host_fence(monkeypatch):
    # A synthetic stand-in exercises the exact-pinned ACP digest path.
    # There is NO network/Console call and the true digest is never weakened.
    system = "x" * 1439
    monkeypatch.setattr(subject, "_ACP_SYSTEM_SHA256",
                        hashlib.sha256(system.encode()).hexdigest())
    fence, calls = gateway(monkeypatch)
    raw = body(messages=[
        {"role": "system", "content": system},
        {"role": "user", "content": PUBLIC},
    ])
    assert fence.send_once(method="POST", url=UPSTREAM, raw=raw) == b'{"choices":[]}'
    assert len(calls) == 1
    with pytest.raises(PermissionError, match="ONCE_ONLY"):
        fence.send_once(method="POST", url=UPSTREAM, raw=raw)
    assert len(calls) == 1


@pytest.mark.parametrize("extra", [
    {"model": "gpt-6-astra"},
    {"messages": [{"role": "system", "content": "y" * 1439},
                  {"role": "user", "content": PUBLIC}]},
    {"messages": [{"role": "system", "content": "x" * 1439},
                  {"role": "user", "content": PUBLIC + " private"}]},
    {"messages": [{"role": "system", "content": "x" * 1439},
                  {"role": "user", "content": PUBLIC},
                  {"role": "user", "content": "other"}]},
    {"tools": [{"type": "function", "function": {"name": "unreviewed"}}]},
])
def test_acp_mismatched_envelope_cannot_reach_host_sender(monkeypatch, extra):
    system = "x" * 1439
    monkeypatch.setattr(subject, "_ACP_SYSTEM_SHA256",
                        hashlib.sha256(system.encode()).hexdigest())
    fence, calls = gateway(monkeypatch)
    original = json.loads(body(messages=[
        {"role": "system", "content": system},
        {"role": "user", "content": PUBLIC},
    ]))
    original.update(extra)
    with pytest.raises(PermissionError):
        fence.send_once(method="POST", url=UPSTREAM,
                        raw=json.dumps(original).encode())
    assert calls == []


def test_cli_unreviewed_system_length_never_reaches_sender(monkeypatch):
    # No additional trust comes from a correctly quoted user prompt.
    for system in ("unknown", "x" * 1549, "x" * 1551):
        fence, calls = gateway(monkeypatch)
        with pytest.raises(PermissionError, match="UNREVIEWED_PROMPT"):
            fence.send_once(method="POST", url=UPSTREAM,
                            raw=body(messages=[
                                {"role": "system", "content": system},
                                {"role": "user", "content": '"' + PUBLIC + '"'},
                            ]))
        assert calls == []
        assert fence.receipt()["attempted"] is True
