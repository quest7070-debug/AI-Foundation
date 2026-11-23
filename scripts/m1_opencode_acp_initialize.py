#!/usr/bin/env python3
"""No-model ACP initialize and empty session/new in network-none OpenCode Docker.

This proves the OpenCode child stdio protocol, NOT DSH delegation/Guard admission.
No prompt, provider inference, account credentials, host mounts or network calls.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import shutil
import re
import subprocess
import sys
import selectors
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from m1_opencode_public_cli_once import OC_CANONICAL, _inspect, _scope_ok, _run

REPO = "quest7070-dev/AI-Foundation"
_MAX = 16_384
_INIT = json.dumps({
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": 1, "clientCapabilities": {},
               "clientInfo": {"name": "foundation-no-model", "version": "1"}},
}, separators=(",", ":")) + "\n"
_NEW = json.dumps({
    "jsonrpc": "2.0", "id": 2, "method": "session/new",
    "params": {"cwd": "/tmp", "mcpServers": []},
}, separators=(",", ":")) + "\n"


def _safe_child_error(raw: bytes) -> str:
    """Redact paths/tokens from *public-only, network-none* Docker stderr.

    The child receives an explicit empty HOME, no mounts, no credentials and
    only a synthetic model id. Never emit raw output, env or protocol bytes.
    """
    if len(raw) > 2048:
        raw = raw[-2048:]  # bounded tail from no-host-mount error logs
    value = raw.decode("ascii", errors="replace")
    value = re.sub(r"https?://\S+", "<url>", value)
    value = re.sub(r"(?:/[A-Za-z0-9_.:+~-]+){1,20}", "<path>", value)
    value = re.sub(r"[A-Za-z0-9_+=.-]{28,}", "<token>", value)
    value = re.sub(r"[^A-Za-z0-9 <>:=,.!_\n-]", "?", value)
    return " ".join(value.split())[:210]


def response_ok(raw: bytes) -> bool:
    if len(raw) > _MAX:
        return False
    try:
        lines = raw.decode("utf-8").splitlines()
        messages = [json.loads(line) for line in lines if line.strip()]
    except (ValueError, UnicodeError):
        return False
    replies = [x for x in messages if type(x) is dict and x.get("id") == 1]
    if len(replies) != 1:
        return False
    result = replies[0].get("result")
    return (type(result) is dict and result.get("protocolVersion") == 1
            and type(result.get("agentCapabilities")) is dict
            and type(result.get("authMethods")) is list)


def _session_reply(raw: bytes):
    """None: pending; False: invalid/rejected; True: one valid session."""
    if len(raw) > _MAX:
        return False
    try:
        msgs = [json.loads(line) for line in raw.decode("utf-8").splitlines()
                if line.strip()]
    except (ValueError, UnicodeError):
        return None  # incomplete final response may still be arriving
    replies = [x for x in msgs if type(x) is dict and x.get("id") == 2]
    if not replies:
        return None
    if len(replies) != 1 or not response_ok(raw):
        return False
    value = replies[0].get("result")
    sid = value.get("sessionId") if type(value) is dict else None
    return type(sid) is str and 0 < len(sid) <= 256


def _session_diagnostic(raw: bytes) -> dict:
    """Protocol error code only; never expose session ID, payload, or details."""
    if len(raw) > _MAX:
        return {"session_reply_seen": False}
    try:
        messages = [json.loads(line) for line in raw.decode("utf-8").splitlines()
                    if line.strip()]
    except (ValueError, UnicodeError):
        return {"session_reply_seen": False}
    responses = [x for x in messages if type(x) is dict and x.get("id") == 2]
    if len(responses) != 1:
        return {"session_reply_seen": bool(responses)}
    error = responses[0].get("error")
    code = error.get("code") if type(error) is dict else None
    data = error.get("data") if type(error) is dict else None
    service = data.get("service") if type(data) is dict else None
    kind = data.get("errorName") if type(data) is dict else None
    # Match the pinned upstream v2.2.5 ACPError mapping. Only finite public
    # error classes leave the isolated child; never emit raw error data.
    services = ("directory", "session", "config", "provider", "project")
    kinds = ("CatalogNotReady", "ServerUnavailable", "CatalogLoadError",
             "ServiceUnavailableError", "TypeError", "DatabaseError", "Error")
    return {"session_reply_seen": True,
            "session_error_code": code if type(code) is int
                                   and -32768 <= code <= 32767 else None,
            "session_error_service": service if type(service) is str
                                    and service in services else "UNCLASSIFIED",
            "session_error_name": kind if type(kind) is str
                                  and kind in kinds else "UNCLASSIFIED"}


def _stream_initialize(cmd, env, *, timeout=25):
    """Keep the ACP stdin open through its response, then stop only this child.

    subprocess.run(input=...) closes stdin immediately; an ACP server may exit
    on EOF before flushing a reply. This process is an owned, model-disabled
    --network=none Docker canary, never an existing model/server process.
    """
    child = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, env=env, bufsize=0)
    out, err = bytearray(), bytearray()
    sent_new = False
    try:
        child.stdin.write(_INIT.encode())
        child.stdin.flush()
        deadline = time.monotonic() + timeout
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ, out)
            selector.register(child.stderr, selectors.EVENT_READ, err)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                ready = selector.select(remaining)
                if not ready:
                    break
                for key, _ in ready:
                    data = os.read(key.fileobj.fileno(), 4096)
                    if not data:
                        selector.unregister(key.fileobj)
                    else:
                        key.data.extend(data)
                if len(out) > _MAX or len(err) > _MAX:
                    break
                if not sent_new and response_ok(out):
                    child.stdin.write(_NEW.encode())
                    child.stdin.flush()
                    sent_new = True
                if sent_new and _session_reply(out) is not None:
                    break
        return subprocess.CompletedProcess(cmd, child.poll(), bytes(out), bytes(err))
    finally:
        child.stdin.close()
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=2)
        child.stdout.close()
        child.stderr.close()


def inspect() -> dict:
    status = {"status": "HOLD_NOT_PROVEN", "model_calls": 0,
              "provider_network": "NONE", "dsh_delegation_proven": False,
              "execution_authorized": False}
    if not _scope_ok():
        return {**status, "status": "HOLD_WRONG_OWNER_M1_PR"}
    docker = shutil.which("docker")
    if docker not in ("/opt/homebrew/bin/docker", "/usr/local/bin/docker"):
        return {**status, "status": "HOLD_DOCKER_UNAVAILABLE"}
    if os.getenv("DOCKER_CONTEXT") or os.getenv("DOCKER_HOST"):
        return {**status, "status": "HOLD_DOCKER_OVERRIDE"}
    # Never pull an image just for this probe; the prior pinned CLI acceptance
    # already owns cache/download verification and startup.
    try:
        if subprocess.run([docker, "context", "show"], capture_output=True,
                          text=True, timeout=6).stdout.strip() != "desktop-linux":
            return {**status, "status": "HOLD_DOCKER_CONTEXT"}
        item = _inspect(docker, OC_CANONICAL)
        if not item or item.get("Os") != "linux" or item.get("Architecture") != "arm64":
            return {**status, "status": "HOLD_PINNED_IMAGE_NOT_CACHED"}
        # Docker Desktop's verified Unix socket is used ONLY by the host
        # client. A scrubbed HOME does not inherit Docker's context. Never
        # pass/mount the socket into the network-none container.
        endpoint = _run([docker, "context", "inspect", "desktop-linux",
                         '--format={{(index .Endpoints "docker").Host}}'], timeout=6)
        if not endpoint or not re.fullmatch(r"unix:///[A-Za-z0-9_./-]{8,300}", endpoint):
            return {**status, "status": "HOLD_UNVERIFIED_DOCKER_SOCKET"}
        # Pin to OpenCode v2.2.5's own subprocess ACP test contract:
        # a metadata-only provider catalog, not a Free/paid account route.
        # No session/prompt is sent; loopback :1 has no listener, and Docker
        # remains --network=none. Nothing is installed or deployed.
        child_config = json.dumps({
            "update": "disable",
            "model": "test/test-model",
            "providers": {
                "test": {
                    "name": "Test",
                    "package": "aisdk:@ai-sdk/openai-compatible",
                    "settings": {"apiKey": "test-key",
                                 "baseURL": "http://127.0.0.1:1/v1"},
                    "models": {
                        "test-model": {
                            "name": "Test Model",
                            "capabilities": {
                                "tools": True,
                                "input": ["text", "image"],
                                "output": ["text"],
                            },
                            "cost": {"input": 0, "output": 0},
                            "limit": {"context": 100000, "output": 10000},
                            "variants": [{"id": "low"}, {"id": "high"}],
                        }
                    },
                }
            },
            "plugins": [], "mcp": {},
            "permissions": [{"action": "*", "resource": "*", "effect": "deny"}],
            "policies": [
                {"action": "provider.use", "resource": "*", "effect": "deny"},
                {"action": "provider.use", "resource": "test", "effect": "allow"},
                {"action": "tool.use", "resource": "*", "effect": "deny"},
            ],
        }, separators=(",", ":"))
        env = {"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
               "HOME": "/tmp", "DOCKER_HOST": endpoint}
        cmd = [
            docker, "run", "--rm", "-i", "--pull=never", "--network=none",
            "--platform=linux/arm64", "--read-only", "--user=65534:65534",
            "--cap-drop=ALL", "--security-opt=no-new-privileges",
            # Reuse the proven pinned CLI fixture's resource envelope.
            "--pids-limit=64", "--memory=768m", "--cpus=1", "--ipc=none",
            "--tmpfs=/tmp:rw,nosuid,nodev,size=128m", "--workdir=/tmp",
            "--env=HOME=/tmp", "--env=XDG_CONFIG_HOME=/tmp/config",
            "--env=XDG_STATE_HOME=/tmp/state",
            "--env=XDG_DATA_HOME=/tmp/data",
            "--env=XDG_CACHE_HOME=/tmp/cache",
            "--env=OPENCODE_PURE=1",
            "--env=OPENCODE_DISABLE_PROJECT_CONFIG=1",
            "--env=OPENCODE_DISABLE_EXTERNAL_SKILLS=1",
            "--env=OPENCODE_DISABLE_AUTOUPDATE=1",
            # Mirror the upstream v2.2.5 isolated ACP test's no-fetch,
            # no-watcher, private DB invariants; never relax network-none.
            "--env=OPENCODE_DISABLE_MODELS_FETCH=true",
            "--env=OPENCODE_DISABLE_FILEWATCHER=true",
            "--env=OPENCODE_DB=/tmp/opencode.db",
            "--env=OPENCODE_CONFIG_CONTENT=" + child_config,
            "--entrypoint=/usr/local/bin/opencode",
            OC_CANONICAL, "acp",
        ]
        cp = _stream_initialize(cmd, env)
    except (OSError, subprocess.SubprocessError):
        return {**status, "status": "HOLD_PROBE_PROCESS_UNAVAILABLE"}
    if cp.returncode not in (None, 0) or len(cp.stderr) > _MAX or not response_ok(cp.stdout):
        # Do not print stdout/stderr/protocol payloads. Bounded scalar
        # diagnostics are enough to distinguish exit/resource/protocol errors.
        return {**status, "status": "HOLD_ACP_INITIALIZE_UNVERIFIED",
                "exit_code": cp.returncode if type(cp.returncode) is int else None,
                "stdout_bytes": len(cp.stdout),
                "stderr_bytes": len(cp.stderr),
                "error_hint": _safe_child_error(cp.stderr),
                "response_valid": response_ok(cp.stdout)}
    if _session_reply(cp.stdout) is not True:
        return {**status, "status": "HOLD_ACP_SESSION_UNVERIFIED",
                "protocol_version": 1, "initialize_valid": True,
                "session_valid": False, "no_prompt": True,
                "stdout_bytes": len(cp.stdout), "stderr_bytes": len(cp.stderr),
                **_session_diagnostic(cp.stdout)}
    return {**status, "status": "ACP_SESSION_VERIFIED_NETWORK_NONE",
            "protocol_version": 1, "session_valid": True,
            "no_prompt": True}


def main() -> None:
    result = inspect()
    print("M1_OPENCODE_ACP=" + json.dumps(result, sort_keys=True), flush=True)
    if name := os.getenv("GITHUB_STEP_SUMMARY"):
        with open(name, "a", encoding="utf-8") as out:
            out.write("\n### OpenCode ACP initialize (network-none)\n\n"
                      + json.dumps(result, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
