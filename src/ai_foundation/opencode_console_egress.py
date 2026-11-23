"""One-shot outbound model fence for a future host-owned OpenCode CLI proxy.

This is a policy boundary, NOT a network sandbox or billing guarantee. The
trusted Operator must attach it to a proxy that is the *only* OS-reachable
upstream path from its private OpenCode CLI, after a separately approved
Guard release and actual owner-selected non-chargeable Console account.

Never pass a model-selected URL, provider credentials, prompts or raw response
into GitHub, CLI argv, task receipts or routine logs.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

UPSTREAM = "https://opencode.ai/inference/openai/v1/chat/completions"
FREE_MODEL_ID = "hy4-flash-free"
# The pinned OpenCode 2.2.5 public CLI canary emits this one built-in tool.
# A change requires a new focused public fixture review before egress.
_REVIEWED_TOOL_DIGEST = (
    "a4c76d1d1b63497608ee10808805c53a01ff5c5dbbfa61cd3757e7bcb690be33"
)
# Exact system envelope observed from official DSH -> real OpenCode 2.2.5
# ACP E2E, M1 CI #43034800479. This fingerprint permits ONLY the matching
# host-reviewed prompt and pinned tool schema (never a standalone grant).
_ACP_SYSTEM_SHA256 = (
    "2a9754b57f441eec91518c1c17784037975ba55e416ccd609c352bbfb38d0cd1"
)

_ALLOWED_FIELDS = frozenset({
    "model", "messages", "temperature", "stream", "stream_options",
    "max_tokens", "max_completion_tokens", "top_p", "tools", "tool_choice",
})
_MAX_INPUT = 65536
_MAX_OUTPUT = 262144


def _strict_json(blob):
    if type(blob) is not bytes or not 1 <= len(blob) <= _MAX_INPUT:
        raise PermissionError("OPENCODE_EGRESS_PAYLOAD_SIZE_DENIED")

    def pairs(items):
        result = {}
        for name, value in items:
            if name in result:
                raise ValueError("duplicate")
            result[name] = value
        return result

    try:
        return json.loads(blob.decode("utf-8"), object_pairs_hook=pairs)
    except (ValueError, UnicodeError):
        raise PermissionError("OPENCODE_EGRESS_MALFORMED_JSON") from None


@dataclass(frozen=True)
class ReviewedOutboundCodeScope:
    """Host-selected exact public task. Never created from a CLI response."""
    prompt: str
    model: str = FREE_MODEL_ID

    def __post_init__(self):
        if (type(self.prompt) is not str
                or not 1 <= len(self.prompt) <= 4096
                or type(self.model) is not str
                or self.model != FREE_MODEL_ID):
            raise ValueError("OPENCODE_REVIEWED_FREE_SCOPE_REQUIRED")

    @property
    def prompt_digest(self):
        return hashlib.sha256(self.prompt.encode()).hexdigest()


class OneShotOpenCodeModelFence:
    """Refuse extra/helper requests before any paid-model network dispatch.

    This check is additional to a kernel-enforced no-direct-egress CLI
    namespace. It cannot replace that OS boundary or the Console account's
    auto-charge-off verification.
    """

    def __init__(self, scope, *, upstream_sender):
        if (not isinstance(scope, ReviewedOutboundCodeScope)
                or not callable(upstream_sender)):
            raise ValueError("OPENCODE_HOST_SENDER_REQUIRED")
        self.scope = scope
        self._sender = upstream_sender
        self.attempted = False
        self.accepted = 0
        self.denied = 0

    def _check(self, *, method, url, raw):
        if method != "POST" or url != UPSTREAM:
            raise PermissionError("OPENCODE_EGRESS_ENDPOINT_DENIED")
        body = _strict_json(raw)
        if type(body) is not dict or not set(body).issubset(_ALLOWED_FIELDS):
            raise PermissionError("OPENCODE_EGRESS_FIELDS_DENIED")
        if body.get("model") != self.scope.model:
            raise PermissionError("OPENCODE_EGRESS_MODEL_DENIED")
        messages = body.get("messages")
        if (type(messages) is not list or len(messages) != 2
                or any(type(m) is not dict or set(m) != {"role", "content"}
                       for m in messages)
                or messages[0].get("role") != "system"
                or type(messages[0].get("content")) is not str
                or not 1 <= len(messages[0]["content"]) <= 4096):
            raise PermissionError("OPENCODE_EGRESS_UNREVIEWED_PROMPT")
        # The prior CLI path sends a quoted exact prompt. The independently
        # accepted DSH ACP path sends it unquoted and has a fixed 1439-char
        # system preface. Admit no mixed/unknown envelope or extra context.
        # The pinned standalone CLI public canary has a 1550-char system
        # preface. Refuse unrelated/unbounded system contexts even if the
        # reviewed user prompt matches; this is not a content attestation.
        cli = (len(messages[0]["content"]) == 1550
               and messages[1] == {"role": "user",
                                   "content": '"' + self.scope.prompt + '"'})
        acp = (messages[1] == {"role": "user", "content": self.scope.prompt}
               and len(messages[0]["content"]) == 1439
               and hashlib.sha256(
                   messages[0]["content"].encode("utf-8")
               ).hexdigest() == _ACP_SYSTEM_SHA256)
        if not (cli or acp):
            raise PermissionError("OPENCODE_EGRESS_UNREVIEWED_PROMPT")
        tools = body.get("tools")
        if (type(tools) is not list or len(tools) != 1
                or hashlib.sha256(json.dumps(
                    tools, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
                != _REVIEWED_TOOL_DIGEST):
            # Digest mismatch is denied; never broaden to arbitrary tools.
            raise PermissionError("OPENCODE_EGRESS_TOOLS_DENIED")
        if body.get("tool_choice") not in (None, "none", "auto"):
            raise PermissionError("OPENCODE_EGRESS_TOOLS_DENIED")
        if type(body.get("stream", False)) is not bool:
            raise PermissionError("OPENCODE_EGRESS_STREAM_INVALID")
        for name in ("max_tokens", "max_completion_tokens"):
            val = body.get(name)
            if val is not None and (type(val) is not int or not 1 <= val <= 4096):
                raise PermissionError("OPENCODE_EGRESS_TOKEN_LIMIT")
        for name in ("temperature", "top_p"):
            val = body.get(name)
            if val is not None and (type(val) not in (float, int)
                                    or not 0 <= val <= 1):
                raise PermissionError("OPENCODE_EGRESS_SAMPLE_LIMIT")
        if "stream_options" in body and body["stream_options"] != {
                "include_usage": True}:
            raise PermissionError("OPENCODE_EGRESS_STREAM_OPTIONS_DENIED")

    def send_once(self, *, method, url, raw):
        if self.attempted:
            self.denied += 1
            raise PermissionError("OPENCODE_EGRESS_ONCE_ONLY")
        self.attempted = True
        try:
            self._check(method=method, url=url, raw=raw)
        except PermissionError:
            self.denied += 1
            raise
        # An uncertain transport outcome must never be retried. The caller's
        # durable attempt ledger also marks it UNCERTAIN.
        result = self._sender(UPSTREAM, raw)
        if type(result) is not bytes or len(result) > _MAX_OUTPUT:
            raise RuntimeError("OPENCODE_EGRESS_RESPONSE_UNUSABLE")
        self.accepted += 1
        return result

    def receipt(self):
        return {"attempted": self.attempted, "accepted": self.accepted,
                "denied": self.denied, "model": FREE_MODEL_ID,
                "external_sender_verified": False}
