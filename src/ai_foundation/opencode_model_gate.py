"""Offline OpenCode V2 *model-level* gateway and fixed public CLI canary.

No upstream provider transport is implemented here. The gateway binds only to
loopback, checks every request's exact model and public payload, returns
synthetic OpenAI-compatible completion frames, then refuses duplicate/helper
requests. Its explicit lack of an upstream route is the safety property:
even a paid model chosen by OpenCode cannot cause an external model call.

Real OpenCode execution remains blocked until independent OS/network isolation
proves that the CLI's *only* outbound destination is the local gateway, and
the host validates a pinned V2 binary. Do not treat OpenCode's own model
selector/permissions or this gateway alone as a network firewall.
"""
from __future__ import annotations

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import threading

from .harness_public_canary import (
    PUBLIC_CANARY_PROMPT, PUBLIC_CANARY_SOURCE,
)

SERVICE_ID = "foundation-public-gate"
UPSTREAM_FREE_MODEL = "hy4-flash-free"
MODEL_ALIAS = UPSTREAM_FREE_MODEL
CONTAINER_MODEL = SERVICE_ID + "/" + MODEL_ALIAS
_MAX_BODY_BYTES = 8192
_ALLOWED_FIELDS = frozenset({
    "model", "messages", "stream", "temperature", "max_tokens",
    "max_completion_tokens", "stream_options", "tools",
})
_FREE_MODEL_PATTERN = re.compile(r"[a-z0-9][a-z0-9.-]{2,120}\Z")


# Fixed offline-only denial classes; never persist request bodies or paths.
GATE_DIAGNOSTIC_CODES = frozenset({
    "GATE_GET_MODELS_DENIED",
    "GATE_GET_UNSUPPORTED",
    "GATE_POST_ROUTE_UNSUPPORTED",
    "GATE_METHOD_UNSUPPORTED",
    "GATE_BODY_REJECTED",
    "GATE_JSON_INVALID",
    "GATE_REQUEST_FIELDS_UNSUPPORTED",
    "GATE_PAID_OR_DIFFERENT_MODEL_DENIED",
    "GATE_NONPUBLIC_PROMPT_DENIED",
    "GATE_STREAM_SHAPE_DENIED",
    "GATE_STREAM_OPTIONS_DENIED",
    "GATE_TOKEN_LIMIT_DENIED",
    "GATE_TEMPERATURE_INVALID",
    "GATE_ONE_PUBLIC_REQUEST_ONLY",
    "GATE_OTHER_DENIAL",
})


def _unique_json_object(pairs):
    """Reject parser ambiguity before any model-level authorization."""
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("GATE_DUPLICATE_JSON_KEY")
        obj[key] = value
    return obj


class ModelGateDenied(ValueError):
    """Never include the original potentially secret-bearing body in errors."""



def _public_request_shape(body):
    """Only schema counts and recognized public-fixture presence, never text."""
    if type(body) is not dict:
        return {"body_type": "NOT_OBJECT"}
    messages = body.get("messages")
    shape = {"body_type": "OBJECT",
             "unsupported_fields": min(len(set(body) - _ALLOWED_FIELDS), 30),
             "has_tools": "tools" in body,
             "has_tool_choice": "tool_choice" in body,
             "has_metadata": "metadata" in body,
             "has_response_format": "response_format" in body,
             "has_system": "system" in body,
             "message_count": len(messages) if type(messages) is list and len(messages) <= 64 else None,
             "message_roles": [],
             "public_prompt_present": False,
             "public_prompt_in_user": False,
             "user_content_length": None,
             "user_prefix_tags": [], "user_suffix_tags": [],
             "user_trimmed_exact": False,
             "system_fingerprint": None,
             "system_length": None,
             "tools_fingerprint": None,
             "tools_count": None,
             "user_content_type": "ABSENT"}
    if type(messages) is list and len(messages) <= 64:
        for message in messages:
            if type(message) is not dict:
                shape["message_roles"].append("NON_OBJECT")
                continue
            role = message.get("role")
            shape["message_roles"].append(
                role if role in ("system", "user", "assistant", "tool") else "UNKNOWN")
            if role == "system" and type(message.get("content")) is str:
                text = message["content"]
                shape["system_length"] = min(len(text), 65535)
                shape["system_fingerprint"] = hashlib.sha256(text.encode()).hexdigest()
            if role == "user":
                content = message.get("content")
                if type(content) is str:
                    shape["user_content_type"] = "STRING"
                    shape["user_trimmed_exact"] = content.strip() == PUBLIC_CANARY_PROMPT
                    shape["user_content_length"] = min(len(content), 65535)
                    shape["public_prompt_in_user"] = PUBLIC_CANARY_PROMPT in content
                    if shape["public_prompt_in_user"]:
                        idx = content.find(PUBLIC_CANARY_PROMPT)
                        left = content[:idx]
                        right = content[idx + len(PUBLIC_CANARY_PROMPT):]
                        marks = {"\\n": "LF", "\\r": "CR", " ": "SPACE",
                                 '"': "QUOTE", "'": "APOSTROPHE",
                                 "`": "BACKTICK", "\\t": "TAB"}
                        def tags(value):
                            return ([marks.get(x, "OTHER") for x in value]
                                    if len(value) <= 4 else ["LONG"])
                        shape["user_prefix_tags"] = tags(left)
                        shape["user_suffix_tags"] = tags(right)
                    if content == PUBLIC_CANARY_PROMPT:
                        shape["public_prompt_present"] = True
                elif type(content) is list:
                    shape["user_content_type"] = "PARTS"
                    for part in content[:16]:
                        if (type(part) is dict and part.get("type") == "text"
                                and part.get("text") == PUBLIC_CANARY_PROMPT):
                            shape["public_prompt_present"] = True
                else:
                    shape["user_content_type"] = "OTHER"
    tools = body.get("tools")
    if type(tools) is list and len(tools) <= 64:
        shape["tools_count"] = len(tools)
        shape["tools_fingerprint"] = hashlib.sha256(json.dumps(
            tools, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
    return shape


class OfflineOpenCodeModelGate:
    """One offline public completion, invariant over arbitrary client metadata."""

    def __init__(self, *, model=UPSTREAM_FREE_MODEL):
        if type(model) is not str or model != UPSTREAM_FREE_MODEL:
            raise ValueError("OPENCODE_PUBLIC_MODEL_PIN_REQUIRED")
        self.model = model
        self._lock = threading.Lock()
        self._used = False
        self.accepted = 0
        self.denied = 0
        self.denial_reasons = {}
        self.denied_shapes = []
        self.hashes = []

    def record_denial(self, reason="GATE_OTHER_DENIAL"):
        code = reason if reason in GATE_DIAGNOSTIC_CODES else "GATE_OTHER_DENIAL"
        with self._lock:
            self.denied += 1
            self.denial_reasons[code] = self.denial_reasons.get(code, 0) + 1

    def validate(self, body):
        if type(body) is not dict or not set(body).issubset(_ALLOWED_FIELDS):
            raise ModelGateDenied("GATE_REQUEST_FIELDS_UNSUPPORTED")
        if body.get("model") != self.model:
            raise ModelGateDenied("GATE_PAID_OR_DIFFERENT_MODEL_DENIED")
        messages = body.get("messages")
        plain = (type(messages) is list and len(messages) == 1
                 and type(messages[0]) is dict
                 and messages[0] == {"role": "user",
                                     "content": PUBLIC_CANARY_PROMPT})
        # The reviewed OpenCode 2.2.5 ARM64 binary sends the same public
        # user request quoted, with a system preface and one built-in tool
        # schema. This compatibility path is confined to that exact shape.
        # The system preface contains ephemeral runtime metadata, so it
        # cannot be pinned by a literal SHA. The user prompt and tool schema
        # are strictly pinned, and the kernel sandbox has no host mounts.
        reviewed_tools = (
            "a4c76d1d1b63497608ee10808805c53a01ff5c5dbbfa61cd3757e7bcb690be33")
        # Real DSH→OpenCode 2.2.5 ACP: exactly the observed immutable
        # system preface, unquoted public prompt, and one reviewed tool.
        # No substring, prefix, extra message or variable context.
        # M1 CI #43034800479 (request-shape-only receipt).
        acp = (type(messages) is list and len(messages) == 2
               and all(type(x) is dict and set(x) == {"role", "content"}
                       for x in messages)
               and messages[0]["role"] == "system"
               and type(messages[0]["content"]) is str
               and len(messages[0]["content"]) == 1439
               and hashlib.sha256(
                   messages[0]["content"].encode("utf-8")
               ).hexdigest() ==
               "2a9754b57f441eec91518c1c17784037975ba55e416ccd609c352bbfb38d0cd1"
               and messages[1] == {"role": "user",
                                   "content": PUBLIC_CANARY_PROMPT}
               and type(body.get("tools")) is list
               and len(body["tools"]) == 1
               and hashlib.sha256(json.dumps(
                   body["tools"], sort_keys=True,
                   ensure_ascii=True).encode()).hexdigest() ==
               "a4c76d1d1b63497608ee10808805c53a01ff5c5dbbfa61cd3757e7bcb690be33")
        sdk = (type(messages) is list and len(messages) == 2
               and all(type(x) is dict and set(x) == {"role", "content"}
                       for x in messages)
               and messages[0]["role"] == "system"
               and type(messages[0]["content"]) is str
               and len(messages[0]["content"]) == 1550
               and messages[1] == {"role": "user",
                                   "content": '"' + PUBLIC_CANARY_PROMPT + '"'}
               and type(body.get("tools")) is list
               and len(body["tools"]) == 1
               and hashlib.sha256(json.dumps(
                   body["tools"], sort_keys=True,
                   ensure_ascii=True).encode()).hexdigest() == reviewed_tools)
        if not (plain and "tools" not in body or sdk or acp):
            raise ModelGateDenied("GATE_NONPUBLIC_PROMPT_DENIED")
        if type(body.get("stream", False)) is not bool:
            raise ModelGateDenied("GATE_STREAM_SHAPE_DENIED")
        if "stream_options" in body and body["stream_options"] != {
                "include_usage": True}:
            raise ModelGateDenied("GATE_STREAM_OPTIONS_DENIED")
        for key in ("max_tokens", "max_completion_tokens"):
            if key in body and (
                    type(body[key]) is not int or not 1 <= body[key] <= 256):
                raise ModelGateDenied("GATE_TOKEN_LIMIT_DENIED")
        if "temperature" in body and (
                type(body["temperature"]) not in (int, float)
                or not 0 <= body["temperature"] <= 1):
            raise ModelGateDenied("GATE_TEMPERATURE_INVALID")
        return json.dumps(body, sort_keys=True, ensure_ascii=True)

    def accept(self, body):
        try:
            fingerprint = hashlib.sha256(self.validate(body).encode()).hexdigest()
        except ModelGateDenied as exc:
            self.record_denial(str(exc))
            if len(self.denied_shapes) < 4:
                self.denied_shapes.append(_public_request_shape(body))
            raise
        with self._lock:
            if self._used:
                self.denied += 1
                code = "GATE_ONE_PUBLIC_REQUEST_ONLY"
                self.denial_reasons[code] = self.denial_reasons.get(code, 0) + 1
                raise ModelGateDenied(code)
            self._used = True
            self.accepted += 1
            self.hashes.append(fingerprint)
        return {
            "id": "chatcmpl-foundation-public-only",
            "object": "chat.completion",
            "created": 0,
            "model": self.model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant",
                            "content": PUBLIC_CANARY_SOURCE},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 0,
                      "completion_tokens": 0,
                      "total_tokens": 0},
        }


def opencode_v2_isolated_config(gateway_port):
    """Reviewed V2-only config. No provider credentials or OS authority."""
    if type(gateway_port) is not int or not 1 <= gateway_port <= 65535:
        raise ValueError("GATE_PORT_REQUIRED")
    # OpenCode 2.x official runtime schema, not the legacy singular key.
    # All credentials and upstream providers are absent. Kernel network-none
    # is authoritative and the only endpoint is the loopback synthetic gate.
    return {
        "$schema": "https://opencode.ai/config.json",
        "model": CONTAINER_MODEL,
        "agents": {"title": {"disabled": True}},
        "providers": {
            SERVICE_ID: {
                "name": "Foundation offline public code fixture",
                "package": "@opencode/ai/providers/openai-compatible",
                "settings": {
                    "baseURL": "http://127.0.0.1:" + str(gateway_port) + "/v1",
                },
                "models": {
                    MODEL_ALIAS: {
                        "modelID": UPSTREAM_FREE_MODEL,
                        "name": "Offline public model gate",
                        "limit": {"context": 4096, "output": 256},
                    },
                },
            },
        },
        "permissions": [
            {"action": "*", "resource": "*", "effect": "deny"},
        ],
        "policies": [
            {"action": "provider.use", "resource": "*", "effect": "deny"},
            {"action": "provider.use", "resource": SERVICE_ID, "effect": "allow"},
        ],
        "plugins": [],
        "mcp": {},
        "warming": False,
        "compaction": {"auto": False},
    }


class OpenCodeFixtureServer(ThreadingHTTPServer):
    """Loopback-only fixture. No hidden upstream forwarding method."""

    allow_reuse_address = False
    daemon_threads = True

    def __init__(self, gate, *, port=0):
        self.gate = gate
        super().__init__(("127.0.0.1", port), _Handler)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        # Never log body, headers or environment, including possible secrets.
        pass

    def _response(self, status, data, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)
        self.close_connection = True

    def do_GET(self):
        if self.path == "/__fixture/status":
            # No raw source/prompt/credentials; Docker host reads through
            # the namespace without publishing a port to the host.
            gate = self.server.gate
            with gate._lock:
                report = {"accepted": gate.accepted,
                          "denied": gate.denied,
                          "fixture_only": True, "external_calls": 0}
            self._response(200, json.dumps(report).encode())
            return
        self.server.gate.record_denial("GATE_GET_MODELS_DENIED" if self.path == "/v1/models" else "GATE_GET_UNSUPPORTED")
        self._response(404, b'{"error":"NOT_AVAILABLE"}')

    def _unsupported_method(self):
        self.server.gate.record_denial("GATE_METHOD_UNSUPPORTED")
        self._response(405, b'{"error":"METHOD_NOT_ALLOWED"}')

    do_HEAD = _unsupported_method
    do_PUT = _unsupported_method
    do_PATCH = _unsupported_method
    do_DELETE = _unsupported_method
    do_OPTIONS = _unsupported_method

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self.server.gate.record_denial("GATE_POST_ROUTE_UNSUPPORTED")
            self._response(404, b'{"error":"NOT_AVAILABLE"}')
            return
        length = self.headers.get("Content-Length")
        if (not length or not length.isascii() or not length.isdecimal()
                or not 0 < int(length) <= _MAX_BODY_BYTES
                or self.headers.get("Transfer-Encoding")
                or self.headers.get("Content-Encoding")):
            self.server.gate.record_denial("GATE_BODY_REJECTED")
            self._response(413, b'{"error":"GATE_BODY_REJECTED"}')
            return
        try:
            body = json.loads(self.rfile.read(int(length)),
                              object_pairs_hook=_unique_json_object)
        except (ValueError, UnicodeError):
            self.server.gate.record_denial("GATE_JSON_INVALID")
            self._response(400, b'{"error":"GATE_JSON_INVALID"}')
            return
        try:
            answer = self.server.gate.accept(body)
        except ModelGateDenied as exc:
            self._response(403, json.dumps(
                {"error": str(exc)}).encode())
            return
        if body.get("stream", False):
            # OpenAI-compatible SSE, still synthetic/no upstream request.
            chunk = {
                "id": answer["id"], "object": "chat.completion.chunk",
                "created": 0, "model": answer["model"],
                "choices": [{
                    "index": 0,
                    "delta": {"role": "assistant",
                              "content": PUBLIC_CANARY_SOURCE},
                    "finish_reason": "stop",
                }],
            }
            payload = ("data: " + json.dumps(chunk)
                       + "\n\ndata: [DONE]\n\n").encode()
            self._response(200, payload, "text/event-stream")
        else:
            self._response(200, json.dumps(answer).encode())


def run_fixture_gate_for_test(callback):
    """Bounded test helper, not a background service."""
    gate = OfflineOpenCodeModelGate()
    server = OpenCodeFixtureServer(gate)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        return callback(server.server_port, gate)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
