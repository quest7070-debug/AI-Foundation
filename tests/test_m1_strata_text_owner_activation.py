"""Fixed owner activation; synthetic no-network tests, no real M1 changes."""
from types import SimpleNamespace
import pytest
from scripts import m1_strata_text_owner_activation as a


def _event(sha):
    return {"action": "opened", "sender": {"login": a.OWNER},
            "repository": {"full_name": a.REPO},
            "issue": {"number": 17, "state": "open",
                      "user": {"login": a.OWNER},
                      "title": a.PREFIX + sha,
                      "body": "<!-- foundation-strata-text-activation:v1:" +
                              sha + " -->"}}


def _env(sha):
    return {"GITHUB_REPOSITORY": a.REPO, "GITHUB_WORKFLOW": a.WORKFLOW,
            "GITHUB_EVENT_NAME": "issues", "GITHUB_ACTOR": a.OWNER,
            "GITHUB_SHA": sha}


def test_strata_text_activation_only_accepts_exact_owner_issued_main():
    sha = "a" * 40
    event, env = _event(sha), _env(sha)
    assert a.identity(event, env) == 17
    live = dict(event["issue"])
    assert a.identity(event, env, live) == 17
    live["body"] = "tampered"
    with pytest.raises(a.Denied):
        a.identity(event, env, live)
    with pytest.raises(a.Denied):
        a.identity(event, {**env, "GITHUB_ACTOR": "untrusted"})
    with pytest.raises(a.Denied):
        a.identity({**event, "issue": {**event["issue"], "number": True}}, env)


def test_activation_upgrades_exact_endpoint_without_model_or_operator_restart(monkeypatch):
    events = []
    class Host:
        def _registered(self): return True
        def _pid_owned(self): return True
    monkeypatch.setattr(a, "owner_live_source", lambda: Host())
    monkeypatch.setattr(a, "installed_config",
                        lambda: (None, SimpleNamespace(), "fixture-root"))
    def setup(root, *, port, expand_text_roles, apply=False):
        assert root == "fixture-root" and port == 18080 and expand_text_roles
        events.append(apply)
        if apply:
            return "TEXT_ROLES_EXPANDED"
        return "READY_TO_EXPAND_TEXT" if len(events) == 1 else "ALREADY_TEXT_ENABLED"
    monkeypatch.setattr(a, "configure_strata", setup)
    result = a.activate()
    assert result == {"status": "CONFIGURED_RESTART_REQUIRED",
                      "config_changed": True, "model_calls": 0,
                      "service_mutations": 0, "private_egress": False}
    assert events == [False, True, False]


def test_activation_refuses_unreviewed_endpoint_before_write(monkeypatch):
    calls = []
    monkeypatch.setattr(a, "owner_live_source", lambda: object())
    monkeypatch.setattr(a, "installed_config",
                        lambda: (None, SimpleNamespace(), "fixture-root"))
    def setup(root, *, port, expand_text_roles, apply=False):
        calls.append(apply)
        return "EXISTING_ENDPOINT_REVIEW_REQUIRED"
    monkeypatch.setattr(a, "configure_strata", setup)
    with pytest.raises(a.Denied, match="STRATA_EXISTING_CONFIG_REVIEW_REQUIRED"):
        a.activate()
    assert calls == [False]


def test_verify_issue_is_distinct_from_activation_and_cannot_select_a_prompt():
    sha = "b" * 40
    event, env = _event(sha), _env(sha)
    event["issue"]["title"] = a.VERIFY_PREFIX + sha
    event["issue"]["body"] = "<!-- foundation-strata-text-verify:v1:" + sha + " -->"
    assert a.identity(event, env, verify=True) == 17
    with pytest.raises(a.Denied):
        a.identity(event, env)
    event["issue"]["body"] += " malicious instruction"
    with pytest.raises(a.Denied):
        a.identity(event, env, verify=True)


def test_public_text_probe_selects_exact_pinned_strata_with_one_synthetic_call(
        monkeypatch):
    from ai_foundation.local_compute_registry import LocalComputeCandidate
    from ai_foundation import native_credentials, openai_local_adapter
    calls = []
    monkeypatch.setattr(a.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(a.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(a.os, "getuid", lambda: 501)
    monkeypatch.setattr(a.os, "geteuid", lambda: 501)
    monkeypatch.setattr(a, "installed_config",
                        lambda: (None, SimpleNamespace(), "owner-fixture"))
    monkeypatch.setattr(a, "configure_strata", lambda *args, **kwargs: "ALREADY_TEXT_ENABLED")
    class Credentials:
        def load(self, name):
            assert name == "local:mainpc-strata:api-key"
            return "synthetic-key-123456"
    monkeypatch.setattr(native_credentials, "MacOSNativeCredentialStore", Credentials)
    class Discovery:
        def __init__(self, base, **kwargs):
            assert base == "http://10.0.1.1:18080"
        def __call__(self):
            return [LocalComputeCandidate("local:mainpc-strata:code-agent",
                health="ONLINE", capabilities=("CODE", "CHAT"),
                model="qwen3.8-flash-next-coder-iq1_m",
                slot="code-agent", same_host=False)]
    class Execution:
        def __init__(self, base, **kw):
            assert base == "http://10.0.1.1:18080"
        def chat_payload(self, payload, *, model=None):
            calls.append((model, payload))
            return {"choices": [{"message": {
                "content": "MainPC drafts the public changes; M1 verifies the results."
            }, "finish_reason": "stop"}]}
    monkeypatch.setattr(openai_local_adapter, "OpenAILocalDiscovery", Discovery)
    monkeypatch.setattr(openai_local_adapter, "OpenAILocalExecution", Execution)
    result = a.public_chat_probe_child()
    assert result["status"] == "LIVE_PUBLIC_TEXT_ANSWER"
    assert result["model_calls"] == 1
    assert result["private_owner_records_read"] == 0
    assert len(calls) == 1 and calls[0][0] == "code-agent"
    assert "public changes" in calls[0][1]["messages"][0]["content"]
    assert calls[0][1].get("tools") is None


def test_bounded_public_chat_probe_never_inherits_github_token(monkeypatch):
    import json
    import subprocess
    monkeypatch.setattr(a, "owner_live_source", lambda: object())
    monkeypatch.setattr(a, "installed_config",
                        lambda: (None, SimpleNamespace(), "owner-fixture"))
    monkeypatch.setattr(a, "configure_strata", lambda *args, **kwargs: "ALREADY_CONFIGURED")
    monkeypatch.setenv("GITHUB_TOKEN", "SYNTHETIC_OWNER_PRIVATE_TOKEN")
    fake = {"status": "LIVE_PUBLIC_TEXT_ANSWER", "model_calls": 1,
            "latency_ms": 12, "answer_chars": 51,
            "execution_binding": "local:mainpc-strata:code-agent",
            "private_owner_records_read": 0}
    def run(argv, **kwargs):
        assert "--public-chat-probe-child" in argv
        assert "GITHUB_TOKEN" not in kwargs["env"]
        assert kwargs["timeout"] == 110
        return subprocess.CompletedProcess(argv, 0, json.dumps(fake), "")
    monkeypatch.setattr(a.subprocess, "run", run)
    assert a.public_chat_probe_bounded() == fake


def test_standalone_bootstrap_without_pythonpath_or_repository_working_directory(tmp_path):
    import os
    from pathlib import Path
    import subprocess
    import sys
    env = {key: os.environ[key] for key in ("PATH", "HOME", "SYSTEMROOT")
           if key in os.environ}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-B", str(Path(a.__file__).resolve()), "--unsupported-mode"],
        cwd=tmp_path, env=env, text=True, capture_output=True, timeout=10,
        check=False,
    )
    assert result.returncode == 1
    assert result.stderr.strip() == "UNSUPPORTED_MODE"
    assert result.stdout == ""

def test_public_text_offline_discovery_emits_fixed_http_code_without_inference(monkeypatch):
    from ai_foundation.local_compute_registry import LocalComputeCandidate
    from ai_foundation import native_credentials, openai_local_adapter
    requests = []
    monkeypatch.setattr(a.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(a.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(a.os, "getuid", lambda: 501)
    monkeypatch.setattr(a.os, "geteuid", lambda: 501)
    monkeypatch.setattr(a, "installed_config", lambda: (None, SimpleNamespace(), "owner"))
    monkeypatch.setattr(a, "configure_strata", lambda *args, **kwargs: "ALREADY_CONFIGURED")
    class Credential:
        def load(self, name): return "synthetic-key-123456789"
    class OfflineDiscovery:
        def __init__(self, base, **kw): pass
        def __call__(self):
            requests.append("discovery")
            return (LocalComputeCandidate(
                binding="local:mainpc-strata", health="UNAVAILABLE",
                reason="HTTP_401", capabilities=()),)
    class NoInference:
        def __init__(self, *args, **kwargs):
            raise AssertionError("No model call permitted after authentication failure")
    monkeypatch.setattr(native_credentials, "MacOSNativeCredentialStore", Credential)
    monkeypatch.setattr(openai_local_adapter, "OpenAILocalDiscovery", OfflineDiscovery)
    monkeypatch.setattr(openai_local_adapter, "OpenAILocalExecution", NoInference)
    assert a.public_chat_probe_child() == {
        "status": "BLOCKED", "reason": "DISCOVERY_HTTP_401", "model_calls": 0}
    assert requests == ["discovery"]


def test_simulated_mainpc_absence_uses_only_pinned_9b(monkeypatch):
    from ai_foundation import shared_ollama9b_adapter
    from ai_foundation.local_compute_registry import LocalComputeCandidate
    calls = []
    class NineOnly:
        def __init__(self, *args, **kwargs): pass
        def __call__(self):
            return (LocalComputeCandidate(
                "local:ollama-shared9b:general", health="ONLINE",
                capabilities=("CHAT",), slot="general",
                model="qwen3.5:9b", same_host=True),)
    class NineExecution:
        def __init__(self, *args, **kwargs): pass
        def chat(self, prompt, model=None):
            calls.append((prompt, model))
            return "M1 pinned 9B continues working independently."
    monkeypatch.setattr(shared_ollama9b_adapter, "SharedOllama9BDiscovery", NineOnly)
    monkeypatch.setattr(shared_ollama9b_adapter, "SharedOllama9BExecution", NineExecution)
    result = a._m1_offline_and_privacy_probe()
    assert result == {"offline_fallback":"M1_LIVE_ANSWER",
                      "m1_model_calls":1,"private_route":"M1_ONLY_CONFIRMED",
                      "offline_mode":"REMOTE_EXCLUDED"}
    assert len(calls) == 1 and calls[0][1] == "general"
    class NineOffline(NineOnly):
        def __call__(self): return ()
    monkeypatch.setattr(shared_ollama9b_adapter, "SharedOllama9BDiscovery", NineOffline)
    result = a._m1_offline_and_privacy_probe()
    assert result["offline_fallback"] == "M1_NO_ONLINE_CHAT"
    assert result["m1_model_calls"] == 0
    assert result["private_route"] == "REMOTE_DENIED_M1_UNAVAILABLE"
    assert len(calls) == 1


def test_m1_ollama_resident_classifies_only_fixed_public_families(monkeypatch):
    from ai_foundation import shared_ollama9b_adapter
    from ai_foundation.klm_9b_handler import MODEL, MODEL_DIGEST
    models = []
    monkeypatch.setattr(shared_ollama9b_adapter, "_local_json",
                        lambda opener, path: models)
    assert a._m1_ollama_resident_class() == "EMPTY"
    models.append({"name": "unrecognized-competitor", "digest": "untrusted-synthetic"})
    assert a._m1_ollama_resident_class() == "OTHER_RESIDENT"
    models[:] = [{"name": MODEL, "digest": MODEL_DIGEST}]
    assert a._m1_ollama_resident_class() == "PINNED_9B_ONLY"
    models.append({"name": "owner-private-project-model"})
    assert a._m1_ollama_resident_class() == "MIXED_WITH_PINNED_9B"
    models[:] = [{"name": "owner-private-project-model"}]
    assert a._m1_ollama_resident_class() == "OTHER_RESIDENT"
    def unavailable(opener, path):
        raise OSError("private inventory unavailable")
    monkeypatch.setattr(shared_ollama9b_adapter, "_local_json", unavailable)
    assert a._m1_ollama_resident_class() == "UNVERIFIED"


def test_bounded_public_chat_probe_rejects_nonstring_residency_without_crashing(monkeypatch):
    import json
    import subprocess
    monkeypatch.setattr(a, "owner_live_source", lambda: object())
    monkeypatch.setattr(a, "installed_config",
                        lambda: (None, SimpleNamespace(), "owner-fixture"))
    monkeypatch.setattr(a, "configure_strata",
                        lambda *args, **kwargs: "ALREADY_CONFIGURED")
    for malformed in ([], {"private_model": "must-not-escape"}, None, 123):
        fake = {"status": "BLOCKED", "reason": "DISCOVERY_HTTP_401",
                "model_calls": 0, "ollama_residency": malformed}
        monkeypatch.setattr(a.subprocess, "run", lambda argv, **kwargs:
                            subprocess.CompletedProcess(argv, 2, json.dumps(fake), ""))
        assert a.public_chat_probe_bounded() == {
            "status": "BLOCKED", "reason": "CHILD_RECEIPT_UNVERIFIED",
            "model_calls": "UNCERTAIN"}
