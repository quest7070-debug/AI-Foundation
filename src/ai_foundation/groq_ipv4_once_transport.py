"""Fixed public-fixture Groq transport over Mac curl IPv4.

Only the exact, compiled-in public text and pinned on_demand model can be sent.
The Keychain secret is handed to curl by stdin config, never process arguments,
a temporary file, a log, or a request made by Python urllib. No redirects or
curlrc; a single HTTPS POST with a hard timeout and bounded response.
"""
from __future__ import annotations

import json
import re
import subprocess

from .cloud_execution import CloudResponse
from .provider_catalog import spec

URL = "https://api.groq.com/openai/v1/chat/completions"
PUBLIC_TEST = "For this public test, output exactly the single word FOUNDATION_OK."
EXPECTED = "FOUNDATION_OK"
MAX_RESPONSE_BYTES = 65536


def fixture_payload(model):
    return {
        "model": model,
        "messages": [{"role": "user", "content": PUBLIC_TEST}],
        "max_completion_tokens": 16,
        "temperature": 0,
        "service_tier": "on_demand",
    }


class GroqIPv4OnceTransport:
    """Not a generic cloud transport; do not give it unreviewed model prompts."""

    def __init__(self, *, runner=subprocess.run):
        self.runner = runner

    def send(self, provider, secret, payload):
        pinned = spec("GROQ")
        if (provider != "GROQ" or pinned is None or pinned.endpoint != URL
                or payload != fixture_payload(pinned.model)):
            raise ValueError("GROQ_PUBLIC_FIXTURE_ONLY")
        if type(secret) is not str or re.fullmatch(
                r"gsk_[A-Za-z0-9_-]{16,}", secret) is None:
            raise ValueError("GROQ_KEY_UNAVAILABLE")
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
        # This public fixed fixture is not private. Only the key goes through
        # stdin, because argv and process listings may be externally visible.
        args = [
            "/usr/bin/curl", "-q", "--ipv4", "--silent", "--show-error",
            "--connect-timeout", "5", "--max-time", "12",
            "--max-filesize", str(MAX_RESPONSE_BYTES),
            "--proto", "=https",
            "--request", "POST",
            "--header", "Content-Type: application/json",
            "--header", "Accept: application/json",
            "--data-binary", body,
            "--output", "-", "--write-out", "\n%{http_code}",
            "--config", "-", URL,
        ]
        cfg = ('header = "Authorization: Bearer ' + secret + '"\n').encode()
        # No retries or redirect following. Suppress untrusted stderr/body in
        # outward exceptions, including failures where a request was sent.
        try:
            process = self.runner(
                args, input=cfg, capture_output=True, timeout=15, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError("GROQ_IPV4_TRANSPORT_UNCERTAIN") from None
        if process.returncode != 0:
            raise RuntimeError("GROQ_IPV4_TRANSPORT_UNCERTAIN")
        output = process.stdout
        if not isinstance(output, bytes) or len(output) > MAX_RESPONSE_BYTES + 16:
            raise RuntimeError("GROQ_IPV4_RESPONSE_UNUSABLE")
        response, separator, status = output.rpartition(b"\n")
        if len(response) > MAX_RESPONSE_BYTES:
            raise RuntimeError("GROQ_IPV4_RESPONSE_UNUSABLE")
        if not separator or status not in (
                b"200", b"400", b"401", b"403", b"404", b"408",
                b"409", b"413", b"422", b"429", b"500", b"502",
                b"503", b"504"):
            raise RuntimeError("GROQ_IPV4_RESPONSE_UNUSABLE")
        try:
            decoded = response.decode("utf-8")
        except UnicodeError:
            raise RuntimeError("GROQ_IPV4_RESPONSE_UNUSABLE") from None
        return CloudResponse(int(status), {}, decoded)
