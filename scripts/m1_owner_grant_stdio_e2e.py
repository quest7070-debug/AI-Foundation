"""External-process M1 canary: synthetic fixture grant + exact Guard MCP.

Starts ONLY the fixture subprocess. All writable state is an isolated
TemporaryDirectory, not the live Operator data root or production Guard.
"""
from __future__ import annotations

import json
from pathlib import Path
import os
import select
import subprocess
import sys

from m1_development_bridge import require_m1

MODERN = "2026-07-28"
META = {"io.modelcontextprotocol/protocolVersion": MODERN,
        "io.modelcontextprotocol/clientCapabilities": {},
        "io.modelcontextprotocol/clientInfo": {
            "name": "untrusted-external-mcp-client", "version": "1"}}


def exercise():
    require_m1()
    if os.getuid() != 501 or os.geteuid() != os.getuid():
        raise RuntimeError("M1_OWNER_SESSION_REQUIRED")
    child = Path(__file__).resolve().parent / "m1_owner_grant_host_canary.py"
    proc = subprocess.Popen(
        ["/opt/homebrew/bin/python3.12", "-B", str(child)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1, close_fds=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    count = 0

    def call(method, params=None, *, client_name=None):
        nonlocal count
        count += 1
        payload = dict(params or {})
        payload["_meta"] = dict(META)
        if client_name is not None:
            payload["_meta"]["io.modelcontextprotocol/clientInfo"] = {
                "name": client_name, "version": "1"}
        frame = {"jsonrpc": "2.0", "id": count, "method": method, "params": payload}
        proc.stdin.write(json.dumps(frame, separators=(",", ":")) + "\n")
        proc.stdin.flush()
        ready, _, _ = select.select([proc.stdout], [], [], 10)
        if not ready:
            raise RuntimeError("MCP_CANARY_CHILD_TIMEOUT")
        line = proc.stdout.readline()
        if not line or len(line) > 32768:
            raise RuntimeError("MCP_CANARY_BAD_FRAME")
        response = json.loads(line)
        if response.get("id") != count:
            raise RuntimeError("MCP_CANARY_ID_MISMATCH")
        return response

    def tool(name, args=None, *, client_name=None):
        response = call("tools/call", {"name": name, "arguments": args or {}},
                        client_name=client_name)
        if "error" in response:
            return {"jsonrpc_error": response["error"]["code"]}
        result = response["result"]
        value = json.loads(result["content"][0]["text"]) if not result["isError"] else None
        return {"is_error": result["isError"], "value": value}

    try:
        protocol = call("server/discover")
        if MODERN not in protocol["result"]["supportedVersions"]:
            raise RuntimeError("MCP_CANARY_DISCOVERY_FAILED")
        names = [x["name"] for x in call("tools/list")["result"]["tools"]]
        if names != ["foundation_status", "approval_requests",
                     "review_candidate", "submit_decision"]:
            raise RuntimeError("MCP_CANARY_TOOLS_NOT_SCOPED")
        state = tool("foundation_status")
        if (state["is_error"] or state["value"].get("state") != "READY"):
            raise RuntimeError("MCP_OWNER_GRANT_STATUS_UNAVAILABLE")
        rows = tool("approval_requests")["value"]
        if ([row["run_id"] for row in rows] != [
                "m1-canary-approve", "m1-canary-deny"]
                and sorted(row["run_id"] for row in rows) !=
                    ["m1-canary-approve", "m1-canary-deny"]):
            raise RuntimeError("MCP_CANARY_FOREIGN_REQUEST_EXPOSED")
        refs = {row["run_id"]: row["request_ref"] for row in rows}
        for run in ("m1-canary-approve", "m1-canary-deny"):
            if len(refs[run]) != 64:
                raise RuntimeError("MCP_CANARY_REF_NOT_CURRENT")
            checked = tool("review_candidate", {"run_id": run,
                                                "request_ref": refs[run]})
            if checked["is_error"] or checked["value"]["current"] is not True:
                raise RuntimeError("MCP_CANARY_REVIEW_CAS_FAILED")
        run = "m1-canary-approve"
        a = {"run_id": run, "request_ref": refs[run], "decision": "AUTHORIZE"}
        approved = tool("submit_decision", a)
        if approved["is_error"] or approved["value"] != {"ok": True, "status": "APPROVED"}:
            raise RuntimeError("MCP_CANARY_EXACT_AUTHORIZE_FAILED")
        replay = tool("submit_decision", a)
        if replay.get("is_error") is not True:
            raise RuntimeError("MCP_CANARY_REPLAY_NOT_DENIED")
        run = "m1-canary-deny"
        denied = tool("submit_decision", {
            "run_id": run, "request_ref": refs[run], "decision": "DENY"})
        if denied["is_error"] or denied["value"] != {"ok": True, "status": "CANCELLED"}:
            raise RuntimeError("MCP_CANARY_EXACT_DENY_FAILED")
        foreign = tool("submit_decision", {
            "run_id": "m1-canary-other", "request_ref": "f" * 64,
            "decision": "AUTHORIZE"}, client_name="trusted-owner")
        if foreign["is_error"] is not True:
            raise RuntimeError("MCP_CANARY_FOREIGN_WRITE_GRANTED")
        wrong_decision = tool("submit_decision", {
            "run_id": run, "request_ref": refs[run], "decision": "AUTHORIZE"})
        if wrong_decision["is_error"] is not True:
            raise RuntimeError("MCP_CANARY_UNGRANTED_DECISION_ACCEPTED")
        extra = tool("submit_decision", {**a, "owner": True})
        if extra != {"jsonrpc_error": -32602}:
            raise RuntimeError("MCP_CANARY_ARG_SPOOF_ACCEPTED")
        proc.stdin.close()
        if proc.wait(timeout=10) != 0:
            raise RuntimeError("MCP_CANARY_GUARD_NOT_VERIFIED")
        if proc.stderr.read().strip() != "M1_OWNER_GRANT_CANARY=VERIFIED":
            raise RuntimeError("MCP_CANARY_PRIVATE_RECEIPT_MISSING")
        return {"status": "VERIFIED", "scope": "ephemeral-synthetic-only",
                "transport": "owner-local-stdio", "owner_ui_delegation": False,
                "exact_grant_consumed": True,
                "guard_authorize": True, "guard_deny": True,
                "stale_replay_denied": True, "foreign_scope_denied": True,
                "production_guard_writes": 0, "model_calls": 0, "native_effects": 0}
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=4)


if __name__ == "__main__":
    try:
        print(json.dumps(exercise(), sort_keys=True))
    except Exception:
        print('{"status":"FAILED","reason":"M1_OWNER_GRANT_CANARY_NOT_VERIFIED"}')
        raise SystemExit(1)
