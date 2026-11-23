"""Focused source-contract tests; never launch Docker or call a model."""
import json
import os
import subprocess
import sys
from types import SimpleNamespace

from scripts import m1_opencode_acp_initialize as p


def sample(protocol=1):
    body = {"jsonrpc": "2.0", "id": 1,
            "result": {"protocolVersion": protocol,
                       "agentCapabilities": {"loadSession": True},
                       "authMethods": []}}
    return (json.dumps(body) + "\n").encode()


def sample_session(sid="public-no-model-session"):
    body = {"jsonrpc": "2.0", "id": 2, "result": {"sessionId": sid}}
    return (json.dumps(body) + "\n").encode()


def test_session_reply_accepts_exactly_one_valid_session():
    assert p._session_reply(sample() + sample_session()) is True
    assert p._session_reply(sample()) is None
    assert p._session_reply(sample() + sample_session("")) is False
    assert p._session_reply(sample() + sample_session() + sample_session()) is False
    assert p._session_reply(sample() + b'{"jsonrpc":"2.0","id":2,"error":{"code":-1}}\n') is False


def test_session_diagnostics_never_emit_ids_or_error_text():
    raw = (sample() + b'{"jsonrpc":"2.0","id":2,"error":'
           b'{"code":-32603,"message":"private /workspace/token"}}\n')
    assert p._session_reply(raw) is False
    assert p._session_diagnostic(raw) == {
        "session_reply_seen": True, "session_error_code": -32603,
        "session_error_service": "UNCLASSIFIED",
        "session_error_name": "UNCLASSIFIED"}
    assert "private" not in str(p._session_diagnostic(raw))


def test_acp_error_data_service_is_bounded_and_never_exposes_payload():
    raw = (sample() + b'{"jsonrpc":"2.0","id":2,"error":'
           b'{"code":-32603,"data":{"service":"directory",'
           b'"file":"/Users/secret/path"}}}\n')
    assert p._session_diagnostic(raw)["session_error_service"] == "directory"
    assert p._session_diagnostic(raw)["session_error_name"] == "UNCLASSIFIED"
    assert "/Users/secret" not in str(p._session_diagnostic(raw))
    raw = (sample() + b'{"jsonrpc":"2.0","id":2,"error":'
           b'{"code":-32603,"data":{"service":"private-token"}}}\n')
    assert p._session_diagnostic(raw)["session_error_service"] == "UNCLASSIFIED"


def test_acp_error_name_is_only_known_upstream_enum():
    raw = (sample() + b'{"jsonrpc":"2.0","id":2,"error":'
           b'{"code":-32603,"data":{"errorName":"CatalogNotReady"}}}\n')
    assert p._session_diagnostic(raw)["session_error_name"] == "CatalogNotReady"
    raw = (sample() + b'{"jsonrpc":"2.0","id":2,"error":'
           b'{"code":-32603,"data":{"errorName":"my-secret-token"}}}\n')
    assert p._session_diagnostic(raw)["session_error_name"] == "UNCLASSIFIED"


def test_only_one_valid_initialize_counts():
    assert p.response_ok(sample())
    assert p.response_ok(b'{"jsonrpc":"2.0","method":"session/update","params":{}}\n' + sample())
    assert not p.response_ok(sample(protocol=2))
    assert not p.response_ok(sample() + sample())
    assert not p.response_ok(b'{"jsonrpc":"2.0","id":1,"error":{"code":-1}}\n')
    assert not p.response_ok(b"not-json\n")
    assert not p.response_ok(b"x" * 16385)


def test_no_model_probe_is_network_none_and_no_host_mount(monkeypatch):
    monkeypatch.setattr(p, "_scope_ok", lambda: True)
    monkeypatch.setattr(p.shutil, "which", lambda name: "/opt/homebrew/bin/docker")
    monkeypatch.setattr(p, "_inspect", lambda docker, ref: {"Os": "linux", "Architecture": "arm64"})
    calls = []
    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        if argv[-2:] == ["context", "show"]:
            return SimpleNamespace(stdout="desktop-linux\n", returncode=0)
        if argv[1:4] == ["context", "inspect", "desktop-linux"]:
            return SimpleNamespace(stdout=b"unix:///Users/test/.docker/run/docker.sock\n",
                                   returncode=0)
        raise AssertionError("unexpected host subprocess")
    monkeypatch.setattr(p.subprocess, "run", fake_run)
    def fake_stream(argv, env):
        calls.append((argv, {"env": env}))
        assert env["DOCKER_HOST"] == "unix:///Users/test/.docker/run/docker.sock"
        assert "--network=none" in argv
        assert "-i" in argv  # Keep ACP stdin open until initialize reply.
        assert "--pull=never" in argv and "--read-only" in argv
        assert not any(arg in ("-v", "--volume", "--mount", "--privileged")
                       or arg.startswith(("--volume=", "--mount=", "-v/"))
                       for arg in argv)
        assert argv[-1:] == ["acp"]
        assert "--pure" not in argv
        assert "--env=OPENCODE_PURE=1" in argv
        assert "--env=OPENCODE_DISABLE_MODELS_FETCH=true" in argv
        assert "--env=OPENCODE_DISABLE_FILEWATCHER=true" in argv
        assert "--env=OPENCODE_DB=/tmp/opencode.db" in argv
        cfg = next(v for v in argv
                   if v.startswith("--env=OPENCODE_CONFIG_CONTENT="))
        cfg = json.loads(cfg.removeprefix("--env=OPENCODE_CONFIG_CONTENT="))
        assert cfg["model"] == "test/test-model"
        assert cfg["providers"]["test"]["settings"]["baseURL"] == "http://127.0.0.1:1/v1"
        assert cfg["providers"]["test"]["settings"]["apiKey"] == "test-key"
        assert cfg["plugins"] == [] and cfg["mcp"] == {}
        assert cfg["policies"][0] == {
            "action": "provider.use", "resource": "*", "effect": "deny"}
        assert cfg["policies"][1] == {
            "action": "provider.use", "resource": "test", "effect": "allow"}
        assert cfg["permissions"] == [
            {"action": "*", "resource": "*", "effect": "deny"}]
        assert b'"method":"initialize"' in p._INIT.encode()
        assert b"session/prompt" not in (p._INIT + p._NEW).encode()
        assert json.loads(p._NEW)["params"] == {"cwd": "/tmp", "mcpServers": []}
        assert all(not name.startswith(("OPENAI_", "GROQ_", "ANTHROPIC_"))
                   for name in env)
        return subprocess.CompletedProcess(argv, None, sample() + sample_session(), b"")
    monkeypatch.setattr(p, "_stream_initialize", fake_stream)
    report = p.inspect()
    assert report["status"] == "ACP_SESSION_VERIFIED_NETWORK_NONE"
    assert report["session_valid"] is True
    assert report["no_prompt"] is True
    assert report["model_calls"] == 0
    assert report["execution_authorized"] is False
    assert report["dsh_delegation_proven"] is False
    assert len(calls) == 3


def test_wrong_host_or_missing_image_never_starts_child(monkeypatch):
    monkeypatch.setattr(p, "_scope_ok", lambda: False)
    monkeypatch.setattr(p.subprocess, "run", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("effect")))
    assert p.inspect()["status"] == "HOLD_WRONG_OWNER_M1_PR"
    monkeypatch.setattr(p, "_scope_ok", lambda: True)
    monkeypatch.setattr(p.shutil, "which", lambda name: "/opt/homebrew/bin/docker")
    monkeypatch.setattr(p.subprocess, "run", lambda *_a, **_k: SimpleNamespace(stdout="desktop-linux\n"))
    monkeypatch.setattr(p, "_inspect", lambda *_a: None)
    assert p.inspect()["status"] == "HOLD_PINNED_IMAGE_NOT_CACHED"

def test_streaming_acp_retains_stdin_until_session_response():
    # One local Python fixture, no Docker, model, account, or network.
    child_code = (
        "import json,sys\n"
        "req1=json.loads(sys.stdin.readline())\n"
        "assert req1['method']=='initialize'\n"
        "reply={'jsonrpc':'2.0','id':1,'result':"
        "{'protocolVersion':1,'agentCapabilities':{},'authMethods':[]}}\n"
        "sys.stdout.write(json.dumps(reply)+'\\n');sys.stdout.flush()\n"
        "req2=json.loads(sys.stdin.readline())\n"
        "assert req2['method']=='session/new'\n"
        "assert req2['params']=={'cwd':'/tmp','mcpServers':[]}\n"
        "reply={'jsonrpc':'2.0','id':2,'result':{'sessionId':'public-session'}}\n"
        "sys.stdout.write(json.dumps(reply)+'\\n');sys.stdout.flush()\n"
        "sys.stdin.readline()\n"
    )
    result = p._stream_initialize(
        [sys.executable, "-u", "-c", child_code],
        {"PATH": os.environ.get("PATH", "")}, timeout=4)
    assert result.returncode in (None, 0)
    assert p.response_ok(result.stdout)
    assert p._session_reply(result.stdout) is True
