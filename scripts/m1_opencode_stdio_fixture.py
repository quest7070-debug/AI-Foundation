"""Native M1-only public synthetic stdio transport acceptance.

The exact pinned OpenCode CLI runs in Docker --network=none. The host provides
only a generated public response: no Console key, API, billing, Operator,
release switch, 9B worker or external provider connection is involved.
"""
from __future__ import annotations

import asyncio
import json

from ai_foundation.harness_public_canary import (
    PUBLIC_CANARY_PROMPT, PUBLIC_CANARY_SOURCE, independent_public_canary_review,
)
from ai_foundation.opencode_live_stdio import PinnedStdioOpenCodeHostPort
from ai_foundation.opencode_console_egress import FREE_MODEL_ID


def accept_stdio_fixture(*, image_id, binary_sha256, docker_binary):
    calls = []

    def synthetic_sender(url, raw):
        if calls:
            raise PermissionError("STDIO_FIXTURE_SECOND_OUTBOUND")
        calls.append(True)
        body = json.loads(raw)
        chunk = {
            "id": "foundation-public-stdio-fixture",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": FREE_MODEL_ID,
            "choices": [{
                "index": 0,
                "delta": {"role": "assistant", "content": PUBLIC_CANARY_SOURCE},
                "finish_reason": "stop",
            }],
        }
        if body.get("stream") is True:
            return ("data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n").encode()
        return json.dumps({
            "id": chunk["id"], "object": "chat.completion",
            "created": 0, "model": FREE_MODEL_ID,
            "choices": [{"index": 0, "message": {
                "role": "assistant", "content": PUBLIC_CANARY_SOURCE},
                "finish_reason": "stop"}],
        }).encode()

    # This fixture intentionally bypasses the production constructor to avoid
    # claiming that billing, owner selection or Guard release are verified.
    # Its sender has NO networking or credential access. Production callers
    # must use the normal constructor and real trusted host approval.
    port = object.__new__(PinnedStdioOpenCodeHostPort)
    port.image_id = image_id
    port.binary_sha256 = binary_sha256
    port.docker_binary = docker_binary
    port.send = synthetic_sender

    try:
        source = asyncio.run(port._run_once(PUBLIC_CANARY_PROMPT, 65))
        accepted = (calls == [True] and
                    independent_public_canary_review(PUBLIC_CANARY_PROMPT, source))
        return {"status": ("VERIFIED_NATIVE_STDIO_PUBLIC_SYNTHETIC"
                           if accepted else "STDIO_NATIVE_SOURCE_REJECTED"),
                "attempted": True, "accepted": bool(accepted),
                "host_synthetic_sends": len(calls),
                "external_provider_calls": 0,
                "billing_attested": False,
                "release_permitted": False}
    except (OSError, ValueError, RuntimeError, PermissionError,
            asyncio.TimeoutError, asyncio.IncompleteReadError) as exc:
        return {"status": "STDIO_NATIVE_NOT_ACCEPTED",
                "attempted": True, "accepted": False,
                "error_class": type(exc).__name__,
                "host_synthetic_sends": len(calls),
                "external_provider_calls": 0,
                "billing_attested": False,
                "release_permitted": False}
