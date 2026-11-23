"""Groq IPv4 one-shot transport: exact public fixture, no argv secret or retry."""
import json
from types import SimpleNamespace

import pytest

from ai_foundation.groq_ipv4_once_transport import (
    GroqIPv4OnceTransport, URL, fixture_payload, MAX_RESPONSE_BYTES)
from ai_foundation.provider_catalog import spec


MODEL = spec("GROQ").model
KEY = "gsk_" + "A" * 24


def recording_runner(*, status=200, body=b'{"choices":[{"message":{"content":"FOUNDATION_OK"}}]}',
                     returncode=0):
    calls = []
    def run(args, **kw):
        calls.append((tuple(args), kw))
        return SimpleNamespace(returncode=returncode,
                               stdout=body + b"\n" + str(status).encode(),
                               stderr=b"private-message")
    return calls, run


def test_exact_pinned_public_post_only_and_secret_stdin():
    calls, runner = recording_runner()
    answer = GroqIPv4OnceTransport(runner=runner).send(
        "GROQ", KEY, fixture_payload(MODEL))
    assert answer.status == 200
    assert json.loads(answer.body)["choices"][0]["message"]["content"] == "FOUNDATION_OK"
    assert len(calls) == 1
    argv, kw = calls[0]
    assert argv[:2] == ("/usr/bin/curl", "-q")
    assert "--ipv4" in argv and "--max-filesize" in argv
    assert "--proto" in argv and "=https" in argv
    assert argv[-1] == URL
    assert "--data-binary" in argv and "--config" in argv
    assert "--location" not in argv and "--retry" not in argv
    assert "--noproxy" not in argv
    assert not any(KEY in arg for arg in argv)
    assert KEY.encode() in kw["input"]
    assert kw["capture_output"] and not kw["check"]
    assert kw["timeout"] == 15
    assert KEY not in repr(answer)


def test_private_or_unpinned_payload_cannot_reach_curl():
    calls, runner = recording_runner()
    transport = GroqIPv4OnceTransport(runner=runner)
    for payload in (
        {"model": MODEL, "messages": [{"role": "user", "content": "HumanModel"}]},
        fixture_payload("some-future-model"),
        {**fixture_payload(MODEL), "tools": [{"type": "web_search"}]},
        {**fixture_payload(MODEL), "service_tier": "auto"},
    ):
        with pytest.raises(ValueError, match="GROQ_PUBLIC_FIXTURE_ONLY"):
            transport.send("GROQ", KEY, payload)
    with pytest.raises(ValueError, match="GROQ_PUBLIC_FIXTURE_ONLY"):
        transport.send("NOT_GROQ", KEY, fixture_payload(MODEL))
    with pytest.raises(ValueError, match="GROQ_KEY_UNAVAILABLE"):
        transport.send("GROQ", "invalid", fixture_payload(MODEL))
    assert calls == []


def test_non_200_http_is_structured_and_body_unlogged():
    calls, runner = recording_runner(status=429, body=b'{"error":{"message":"private"}}')
    result = GroqIPv4OnceTransport(runner=runner).send(
        "GROQ", KEY, fixture_payload(MODEL))
    assert result.status == 429
    assert len(calls) == 1


def test_ambiguous_or_large_response_fails_without_echo_and_without_retry():
    for status, body, rc in (
        (200, b"x" * (MAX_RESPONSE_BYTES + 10), 0),
        (200, b"hello", 56),
        (200, b"unframed", 0),
    ):
        calls, runner = recording_runner(status=status, body=body, returncode=rc)
        if body == b"unframed":
            def runner_no_frame(args, **kw):
                calls.append((tuple(args), kw))
                return SimpleNamespace(returncode=0, stdout=b"unframed", stderr=b"private")
            runner = runner_no_frame
        with pytest.raises(RuntimeError, match="GROQ_IPV4_"):
            GroqIPv4OnceTransport(runner=runner).send(
                "GROQ", KEY, fixture_payload(MODEL))
        assert len(calls) == 1
