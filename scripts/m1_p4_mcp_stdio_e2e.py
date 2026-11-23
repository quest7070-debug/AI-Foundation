"""External-process MCP stdio E2E against the deployed local Operator.

This script itself is read only. It spawns a separate owner-local stdio MCP
process, performs the current 2026 protocol discovery/tool call, verifies a
forbidden approval tool cannot be invoked, and outputs only fixed status flags.
No remote public endpoint, OAuth credential, service modification or model.
"""
from __future__ import annotations
import json
from pathlib import Path
import subprocess
import sys

VERSION = "2026-07-28"
META = {
    "io.modelcontextprotocol/protocolVersion": VERSION,
    "io.modelcontextprotocol/clientCapabilities": {},
    "io.modelcontextprotocol/clientInfo": {"name": "foundation-external-mcp-smoke",
                                           "version": "1"},
}


def _request(id_, method, **params):
    return {"jsonrpc": "2.0", "id": id_, "method": method,
            "params": {**params, "_meta": dict(META)}}


def run():
    base = {"status": "BLOCKED", "transport": "owner-local-stdio",
            "protocol": VERSION, "operator_http_verified": False,
            "readonly_tool_verified": False, "write_authority_denied": False,
            "public_remote_mcp_verified": False,
            "service_mutations": 0, "model_calls": 0, "native_dispatches": 0}
    frames = [
        _request(1, "server/discover"),
        _request(2, "tools/list"),
        _request(3, "tools/call", name="foundation_status", arguments={}),
        _request(4, "tools/call", name="submit_decision",
                 arguments={"run_id": "untrusted", "request_ref": "f" * 64,
                            "decision": "AUTHORIZE"}),
    ]
    try:
        cmd = ["/opt/homebrew/bin/python3.12", "-B",
               str(Path(__file__).resolve().parent / "foundation_mcp_stdio.py")]
        child = subprocess.run(cmd, input="\n".join(json.dumps(x) for x in frames) + "\n",
                               capture_output=True, text=True,
                               check=False, timeout=20)
        if child.returncode != 0:
            return {**base, "reason": "MCP_STDIO_CHILD_UNAVAILABLE"}
        rows = [json.loads(x) for x in child.stdout.splitlines()]
        if (len(rows) != 4 or any(type(r) is not dict for r in rows) or
                any(r.get("jsonrpc") != "2.0" for r in rows) or
                any(type(r.get("id")) is not int for r in rows) or
                [r["id"] for r in rows] != [1, 2, 3, 4]):
            return {**base, "reason": "MCP_FRAMING_UNVERIFIED"}
        disc = rows[0].get("result", {})
        listed = rows[1].get("result")
        if (type(disc) is not dict or type(listed) is not dict or
                type(disc.get("supportedVersions")) is not list or
                type(listed.get("tools")) is not list or
                any(type(x) is not dict for x in listed["tools"])):
            return {**base, "reason": "MCP_DISCOVERY_UNVERIFIED"}
        names = [x.get("name") for x in listed["tools"]]
        if VERSION not in disc["supportedVersions"] or names != ["foundation_status"]:
            return {**base, "reason": "MCP_DISCOVERY_UNVERIFIED"}
        call = rows[2].get("result", {})
        if type(call) is not dict or call.get("isError") is not False or type(call.get("content")) is not list:
            return {**base, "reason": "OPERATOR_HTTP_UNAVAILABLE"}
        if (not call["content"] or type(call["content"][0]) is not dict or
                type(call["content"][0].get("text")) is not str):
            return {**base, "reason": "OPERATOR_AGGREGATE_UNVERIFIED"}
        aggregate = json.loads(call["content"][0]["text"])
        if (type(aggregate) is not dict or
                type(aggregate.get("services_ok")) is not int or
                aggregate["services_ok"] < 0 or
                type(aggregate.get("guard_pending")) is not int or
                aggregate["guard_pending"] < 0):
            return {**base, "reason": "OPERATOR_AGGREGATE_UNVERIFIED"}
        if type(rows[3].get("error")) is not dict or rows[3]["error"].get("code") != -32602:
            return {**base, "reason": "MCP_WRITE_SCOPE_NOT_DENIED"}
        return {**base, "status": "OBSERVED", "operator_http_verified": True,
                "readonly_tool_verified": True, "write_authority_denied": True}
    except (OSError, ValueError, TypeError, KeyError, IndexError,
            subprocess.TimeoutExpired, json.JSONDecodeError):
        return {**base, "reason": "MCP_EXTERNAL_CLIENT_UNAVAILABLE"}


if __name__ == "__main__":
    report = run()
    print(json.dumps(report, sort_keys=True))
    if report["status"] != "OBSERVED":
        raise SystemExit(1)
