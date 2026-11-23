"""Groq one-shot IPv4 check stays GET-only and never exposes Keychain secret."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

path = Path(__file__).resolve().parents[1] / "scripts/groq_ipv4_keychain_check.py"
spec = importlib.util.spec_from_file_location("groq_ipv4_keychain_check", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def run_with_status(status, rc=0):
    calls = []
    def fake_run(argv, **kwargs):
        calls.append((tuple(argv), kwargs))
        return SimpleNamespace(returncode=rc, stdout=status, stderr="private failure")
    return calls, fake_run


def test_ipv4_model_get_only_and_credential_never_in_argv():
    calls, runner = run_with_status("200")
    key = "gsk_" + "A" * 28
    result = module.check_ipv4(key, runner=runner)
    assert result == {
        "status": "GROQ_KEY_ACCEPTED_IPV4", "http_status": 200,
        "inference_calls": 0, "billing_verified": False}
    assert len(calls) == 1
    argv, opts = calls[0]
    assert argv[0] == "/usr/bin/curl" and argv[1] == "-q"
    assert "--ipv4" in argv and "--proto" in argv
    assert argv[-1] == module.URL
    assert "--config" in argv and "-" in argv
    assert "--location" not in argv and "--data" not in argv
    assert not any(key in arg for arg in argv)
    assert key in opts["input"]
    assert opts["capture_output"] is True and opts["check"] is False
    assert key not in repr(result) and "private failure" not in repr(result)


def test_unauthorized_statuses_do_not_grant_approval():
    for status, expected in [
        ("401", "GROQ_KEY_REJECTED_IPV4"),
        ("403", "GROQ_KEY_FORBIDDEN_IPV4"),
        ("429", "GROQ_RATE_LIMITED_IPV4"),
        ("503", "GROQ_UNEXPECTED_HTTP_STATUS"),
    ]:
        calls, runner = run_with_status(status)
        result = module.check_ipv4("gsk_" + "B" * 28, runner=runner)
        assert result["status"] == expected
        assert not result["billing_verified"] and result["inference_calls"] == 0
        assert len(calls) == 1


def test_reject_malformed_key_before_any_transport():
    calls, runner = run_with_status("200")
    for key in ("gsk_short", "Bearer ABC", 'gsk_' + "A" * 24 + '"', ""):
        assert module.check_ipv4(key, runner=runner)["status"] == "INVALID_KEY_FORMAT"
    assert calls == []


def test_000_and_transport_errors_are_not_reported_as_auth_failures():
    calls, runner = run_with_status("000")
    result = module.check_ipv4("gsk_" + "C" * 24, runner=runner)
    assert result["status"] == "IPV4_NETWORK_ERROR"
    assert result["http_status"] is None

    calls, runner = run_with_status("403", rc=56)
    result = module.check_ipv4("gsk_" + "C" * 24, runner=runner)
    assert result["status"] == "IPV4_NETWORK_ERROR"
    assert result["http_status"] is None
