"""Owner-local stdio MCP adapter to the already-loaded Operator.

The CLI exports only public-safe foundation_status by default. The same
stdio framing can be reused by an independently authenticated host which
injects an explicit, scoped AuthenticatedMcpHost and advertises bounded
approval tools. Client identity, metadata and arguments never grant scopes.
This file creates no owner delegation, listener, arbitrary write, model
route or HumanModel data export.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
from urllib import request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_foundation.mcp_host import AuthenticatedMcpHost, McpHostAuthorizer
from ai_foundation.operator_mcp_tools import WORKER_STATES, QUEUE_STATES, KLM_STATES

MODERN = "2026-07-28"
LEGACY = "2025-11-25"
VERSION_KEY = "io.modelcontextprotocol/protocolVersion"
CAPABILITIES_KEY = "io.modelcontextprotocol/clientCapabilities"
SERVER_INFO = {"name": "ai-foundation-operator-readonly", "version": "0.1.0"}
TOOLS = [{
    "name": "foundation_status",
    "description": "Read only aggregate current Operator and Guard health, no private records",
    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    "annotations": {"readOnlyHint": True, "destructiveHint": False,
                    "openWorldHint": False},
}]

# Opt-in only: the executable main() never advertises these. A trusted host
# must separately authenticate the principal, scope and exact run/decision.
BOUND_TOOLS = [
    {"name": "human_model_refresh",
     "description": "Revalidate host-bound HumanModel sources and consent, retiring stale records; does not rebuild views, call a model or grant approval",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}},
    {"name": "human_model_correct",
     "description": ("Append an exact host-authorized original-owner-source correction "
                     "to the existing HumanModel ledger; preserve prior evidence. "
                     "No caller-supplied text, owner claim, approval or task execution."),
     "inputSchema": {"type": "object",
                     "required": ["source_system", "record_id", "scope", "run_id", "corrects_evidence_sha256", "task_id", "generation_sha256", "answer_evidence_sha256"],
                     "properties": {
                         "source_system": {"type": "string", "enum": ["chat", "drive", "explicit-owner-input", "owner-event"]},
                         "record_id": {"type": "string", "minLength": 1, "maxLength": 256},
                         "scope": {"type": "string", "minLength": 1, "maxLength": 128},
                         "run_id": {"type": "string", "minLength": 1, "maxLength": 128},
                         "corrects_evidence_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                         "task_id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"},
                         "generation_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                         "answer_evidence_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"}},
                     "additionalProperties": False},
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}},
    {"name": "approval_requests",
     "description": "List only pending Guard requests delegated to this host principal",
     "inputSchema": {"type": "object", "properties": {},
                     "additionalProperties": False},
     "annotations": {"readOnlyHint": True, "openWorldHint": False}},
    {"name": "review_candidate",
     "description": "Check whether an exact scoped Guard request is still current",
     "inputSchema": {"type": "object", "required": ["run_id", "request_ref"],
                     "properties": {"run_id": {"type": "string"},
                                    "request_ref": {"type": "string",
                                                    "pattern": "^[a-f0-9]{64}$"}},
                     "additionalProperties": False},
     "annotations": {"readOnlyHint": True, "openWorldHint": False}},
    {"name": "human_model_answer",
     "description": ("Ask the host-bound HumanModel how the authenticated owner "
                     "might answer. Provisional simulation, never owner approval."),
     "inputSchema": {"type": "object",
                     "required": ["question", "scope"],
                     "properties": {"question": {"type": "string",
                                                "minLength": 1, "maxLength": 2048},
                                    "scope": {"type": "string", "minLength": 1,
                                              "maxLength": 128}},
                     "additionalProperties": False},
     "annotations": {"readOnlyHint": True, "destructiveHint": False,
                     "openWorldHint": False}},
    {"name": "development_admit",
     "description": "Admit an existing request only after exact owner-local source and fixed-test review; no code execution",
     "inputSchema": {"type": "object", "required": ["ticket_id"],
                     "properties": {"ticket_id": {"type": "string", "minLength": 1, "maxLength": 48,
                                                   "pattern": "^[a-z0-9][a-z0-9-]{0,47}$"}},
                     "additionalProperties": False},
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}},
    {"name": "development_continue",
     "description": ("Advance an exact owner-reviewed CODE request through existing "
                     "admission and one-shot local tests; Draft only with separately "
                     "owner-enabled delivery. Never approves reviews or merges main."),
     "inputSchema": {"type": "object", "required": ["ticket_id"],
                     "properties": {"ticket_id": {"type": "string", "minLength": 1,
                                                   "maxLength": 48,
                                                   "pattern": "^[a-z0-9][a-z0-9-]{0,47}$"}},
                     "additionalProperties": False},
     "annotations": {"readOnlyHint": False, "destructiveHint": False,
                     "openWorldHint": False}},
    {"name": "development_cycle",
     "description": ("Run at most one already admitted or exact owner-reviewed "
                     "CODE ticket via existing Guard, Work and host compute lease. "
                     "No review creation, no main merge, no extra model."),
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
     "annotations": {"readOnlyHint": False, "destructiveHint": False,
                     "openWorldHint": False}},
    {"name": "development_request",
     "description": "Persist a new development request for host review; does not execute code or grant approval",
     "inputSchema": {"type": "object", "required": ["ticket_id", "instruction"],
                     "properties": {"ticket_id": {"type": "string", "minLength": 1, "maxLength": 48,
                                                   "pattern": "^[a-z0-9][a-z0-9-]{0,47}$"},
                                    "instruction": {"type": "string", "minLength": 1, "maxLength": 4000}},
                     "additionalProperties": False},
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}},
    {"name": "development_list",
     "description": "List only host-authorized development ticket IDs and current states",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
     "annotations": {"readOnlyHint": True, "openWorldHint": False}},
    {"name": "development_status",
     "description": "Read one host-bound local development ticket state, no source or paths",
     "inputSchema": {"type": "object", "required": ["ticket_id"],
                     "properties": {"ticket_id": {"type": "string",
                                                   "minLength": 1, "maxLength": 128}},
                     "additionalProperties": False},
     "annotations": {"readOnlyHint": True, "openWorldHint": False}},
    {"name": "development_deliver",
     "description": ("Publish only an independently verified, owner-approved "
                     "local development ticket as one GitHub Draft PR"),
     "inputSchema": {"type": "object", "required": ["ticket_id"],
                     "properties": {"ticket_id": {"type": "string",
                                                   "minLength": 1, "maxLength": 128}},
                     "additionalProperties": False},
     "annotations": {"readOnlyHint": False, "destructiveHint": False,
                     "openWorldHint": False}},
    {"name": "development_run",
     "description": ("Execute one preauthorized local development ticket through "
                     "Foundation Guard, Harness and fixed tests without GitHub delivery"),
     "inputSchema": {"type": "object", "required": ["ticket_id"],
                     "properties": {"ticket_id": {"type": "string",
                                                   "minLength": 1, "maxLength": 128}},
                     "additionalProperties": False},
     "annotations": {"readOnlyHint": False, "destructiveHint": False,
                     "openWorldHint": False}},
    {"name": "submit_decision",
     "description": "Send an explicitly host-delegated exact Guard AUTHORIZE or DENY",
     "inputSchema": {"type": "object",
                     "required": ["run_id", "request_ref", "decision"],
                     "properties": {"run_id": {"type": "string"},
                                    "request_ref": {"type": "string",
                                                    "pattern": "^[a-f0-9]{64}$"},
                                    "decision": {"type": "string",
                                                 "enum": ["AUTHORIZE", "DENY"]}},
                     "additionalProperties": False},
     "annotations": {"readOnlyHint": False, "openWorldHint": False}},
]
_TOOL_ARGUMENTS = {
    "foundation_status": frozenset(),
    "approval_requests": frozenset(),
    "review_candidate": frozenset({"run_id", "request_ref"}),
    "submit_decision": frozenset({"run_id", "request_ref", "decision"}),
    "human_model_answer": frozenset({"question", "scope"}),
    "human_model_refresh": frozenset(),
    "human_model_correct": frozenset({"source_system", "record_id", "scope", "run_id",
                                      "corrects_evidence_sha256", "task_id",
                                      "generation_sha256", "answer_evidence_sha256"}),
    "development_list": frozenset(),
    "development_request": frozenset({"ticket_id", "instruction"}),
    "development_admit": frozenset({"ticket_id"}),
    "development_continue": frozenset({"ticket_id"}),
    "development_cycle": frozenset(),
    "development_status": frozenset({"ticket_id"}),
    "development_run": frozenset({"ticket_id"}),
    "development_deliver": frozenset({"ticket_id"}),
}
_TOOL_NAMES = frozenset(_TOOL_ARGUMENTS)


class OperatorAggregateProxy:
    """Fetch only the installed Operator's fixed loopback API and sanitize."""

    def human_payload(self):
        opener = request.build_opener(request.ProxyHandler({}))
        req = request.Request("http://127.0.0.1:8766/api/human", method="GET")
        with opener.open(req, timeout=4) as response:
            if response.status != 200:
                raise ValueError("Operator not available")
            raw = response.read(512 * 1024 + 1)
        if len(raw) > 512 * 1024:
            raise ValueError("unbounded Operator projection")
        row = json.loads(raw)
        if type(row) is not dict:
            raise ValueError("invalid Operator projection")
        state = row.get("state", "UNKNOWN")
        if type(state) is not str or state not in {
            "OK", "GOOD", "READY", "ACTIVE", "RUNNING", "WARNING",
            "ATTENTION", "NEEDS_ATTENTION", "DEGRADED", "FAILED",
            "ERROR", "STOPPED", "UNKNOWN", "WAITING_HUMAN", "UNCERTAIN", "RECOVERING",
        }:
            state = "UNKNOWN"
        notices = row.get("notices", [])
        services = row.get("services", [])
        if type(notices) is not list or len(notices) > 200:
            raise ValueError("invalid Operator notices")
        if type(services) is not list or len(services) > 100:
            raise ValueError("invalid Operator services")
        # Never pass details, exact approval references or private text
        # from the HTTP projection into the external MCP tool.
        safe_notices = []
        for item in notices:
            if type(item) is not dict:
                continue
            level = item.get("level")
            safe_notices.append({
                "level": level if type(level) is int and 1 <= level <= 5 else None,
                "status": "WAITING_HUMAN" if item.get("status") == "WAITING_HUMAN" else None,
                "approval_ref": "PRESENT" if type(item.get("approval_ref")) is str and
                re.fullmatch("[a-f0-9]{64}", item["approval_ref"]) else None,
            })
        safe_services = [
            {"ok": item.get("ok") if type(item.get("ok")) is bool else None}
            for item in services if type(item) is dict
        ]
        development = row.get("development")
        safe_development = {}
        if type(development) is dict:
            source = development.get("source")
            if type(source) is str and source in {
                    "CURRENT_GUARD_WORK_SNAPSHOT",
                    "CURRENT_GUARD_WORK_SNAPSHOT+M1_OWNER_RUNTIME"}:
                safe_development["source"] = source
                # Keep the SAME bounded current Guard/Work aggregates. Dropping
                # these made real zero counts indistinguishable from no evidence.
                for field, maximum in (
                    ("guard_actionable", 100), ("work_running", 1000000),
                    ("work_waiting_human", 1000000), ("work_failed", 1000000),
                    ("work_uncertain", 1000000)):
                    value = development.get(field)
                    if type(value) is int and 0 <= value <= maximum:
                        safe_development[field] = value
                # Existing CODE receipts are not an authenticated caller,
                # present source match, or a completed new development task.
                code = development.get("direct_mcp_status")
                if type(code) is str and code in {
                        "WORK_RECEIPTS_ONLY", "NO_WORK_RECEIPTS"}:
                    safe_development["direct_mcp_status"] = code
                    value = development.get("direct_mcp_verified_receipts")
                    if type(value) is int and 0 <= value <= 32:
                        safe_development["direct_mcp_verified_receipts"] = value
            if safe_development.get("source") == "CURRENT_GUARD_WORK_SNAPSHOT+M1_OWNER_RUNTIME":
                for field, allowed in (
                    ("local9b_worker", WORKER_STATES),
                    ("local9b_queue_state", QUEUE_STATES),
                    ("klm_status", KLM_STATES),
                ):
                    value = development.get(field)
                    if type(value) is str and value in allowed:
                        safe_development[field] = value
        runtime_health = row.get("runtime_health")
        if type(runtime_health) is not str or runtime_health not in {
                "READY", "DEGRADED", "RECOVERING", "UNVERIFIED"}:
            runtime_health = "UNVERIFIED"
        diagnostics = row.get("state_diagnostics")
        diagnostics = diagnostics if type(diagnostics) is dict else {}
        safe_diagnostics = {}
        for field in ("failed_work_window", "failed_effect_window",
                      "dismissed_failed_notices_window"):
            value = diagnostics.get(field)
            safe_diagnostics[field] = (
                value if type(value) is int and 0 <= value <= 100000 else None)
        return {"state": state, "runtime_health": runtime_health,
                "state_diagnostics": safe_diagnostics,
                "notices": safe_notices, "services": safe_services,
                "development": safe_development}


def _new_readonly_host(operator):
    # The authentication decision belongs to the OS owner which launched this
    # single-user stdio process. Model-provided clientInfo is NOT an identity.
    authorizer = McpHostAuthorizer()
    principal, token = AuthenticatedMcpHost.issue_principal(
        "macos-owner-local", ("foundation_status",), ttl_seconds=300)
    authorizer.register(principal, token)
    return AuthenticatedMcpHost(operator, authorizer), principal.session_id, token


class MCPStdio:
    def __init__(self, host, session_id, token, *, exposed_tools=("foundation_status",),
                 readonly_host_refresh=None):
        # This is a trusted *constructor* setting, never a client argument.
        # Actual authorization is independently rechecked by the host for
        # every exact run and every decision; scope alone cannot approve.
        if (not isinstance(exposed_tools, (tuple, list, frozenset))
                or not exposed_tools or not set(exposed_tools) <= _TOOL_NAMES
                or "foundation_status" not in exposed_tools):
            raise ValueError("invalid host-bound MCP tool exposure")
        self.exposed_tools = frozenset(exposed_tools)
        # The permanent owner stdio tunnel may outlive its 300-second local
        # proof-of-owner principal. Only the fixed public-safe read-only tool
        # can ask the trusted launcher to reissue a new short-lived principal.
        # A caller cannot pass this factory in MCP arguments or clientInfo.
        if (readonly_host_refresh is not None and
                (self.exposed_tools != frozenset({"foundation_status"})
                 or not callable(readonly_host_refresh))):
            raise ValueError("readonly renewal requires a fixed status-only host")
        self._readonly_host_refresh = readonly_host_refresh
        self.host = host
        self.session_id = session_id
        self.token = token
        self.legacy_initialized = False
        self.legacy_ready = False

    @staticmethod
    def _error(code, message):
        return {"code": code, "message": message}

    @staticmethod
    def _meta(message):
        params = message.get("params", {})
        if type(params) is not dict:
            return None
        extra = params.get("_meta", {})
        return extra if type(extra) is dict else None

    def dispatch(self, msg):
        if type(msg) is not dict or msg.get("jsonrpc") != "2.0":
            return {"jsonrpc": "2.0", "id": None,
                    "error": self._error(-32600, "Invalid JSON-RPC request")}
        method = msg.get("method")
        id_ = msg.get("id")
        if type(method) is not str:
            return {"jsonrpc": "2.0", "id": None,
                    "error": self._error(-32600, "Invalid method")}
        if "id" in msg and (type(id_) not in (int, str) or isinstance(id_, bool)):
            return {"jsonrpc": "2.0", "id": None,
                    "error": self._error(-32600, "Invalid request ID")}
        if method == "notifications/initialized" and "id" not in msg:
            if self.legacy_initialized:
                self.legacy_ready = True
            return None
        if "id" not in msg:
            return None
        params = msg.get("params", {})
        if type(params) is not dict:
            return {"jsonrpc": "2.0", "id": id_,
                    "error": self._error(-32602, "Invalid parameters")}
        metadata = self._meta(msg)
        modern = (metadata is not None and metadata.get(VERSION_KEY) == MODERN
                  and type(metadata.get(CAPABILITIES_KEY)) is dict)
        is_legacy = self.legacy_ready or method == "initialize"
        if method == "initialize":
            if modern:
                return {"jsonrpc": "2.0", "id": id_,
                        "error": self._error(-32602, "Wrong MCP lifecycle")}
            self.legacy_initialized = True
            return {"jsonrpc": "2.0", "id": id_,
                    "result": {"protocolVersion": LEGACY, "capabilities": {"tools": {}},
                               "serverInfo": SERVER_INFO}}
        if not modern and not is_legacy:
            return {"jsonrpc": "2.0", "id": id_,
                    "error": self._error(-32602, "MCP protocol metadata required")}
        if method == "server/discover" and modern:
            result = {"supportedVersions": [MODERN], "capabilities": {"tools": {}},
                      "serverInfo": SERVER_INFO, "ttlMs": 0, "cacheScope": "private"}
        elif method == "tools/list":
            result = {"tools": [x for x in TOOLS + BOUND_TOOLS
                                if x["name"] in self.exposed_tools]}
            if modern:
                result.update({"ttlMs": 0, "cacheScope": "private"})
        elif method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments", {})
            if (type(name) is not str or name not in self.exposed_tools
                    or type(arguments) is not dict
                    or frozenset(arguments) != _TOOL_ARGUMENTS[name]):
                return {"jsonrpc": "2.0", "id": id_,
                        "error": self._error(-32602, "Tool or arguments not permitted")}
            # The model never supplies the principal or session. The trusted
            # AuthenticatedMcpHost validates session + exact per-run authority,
            # and the current Guard performs the final nonce/CAS transition.
            try:
                # Renewal happens after strict tool and argument validation.
                # Never mint an authorization for a caller-supplied tool,
                # approval, HumanModel request or development action.
                if (self._readonly_host_refresh is not None
                        and name == "foundation_status"
                        and self.host.authorizer.authenticate(
                            self.session_id, self.token) is None):
                    replacement = self._readonly_host_refresh()
                    if (type(replacement) is not tuple
                            or len(replacement) != 3):
                        raise ValueError("invalid trusted readonly renewal")
                    self.host, self.session_id, self.token = replacement
                output = self.host.dispatch(
                    self.session_id, self.token, name, arguments)
                result = {"content": [{"type": "text",
                                      "text": json.dumps(output, sort_keys=True)}],
                          "isError": False}
            except Exception:
                result = {"content": [{"type": "text",
                                      "text": "Local Operator or MCP authority unavailable"
                                              if name == "foundation_status" else
                                              "MCP scope or current Guard request rejected"}],
                          "isError": True}
        else:
            return {"jsonrpc": "2.0", "id": id_,
                    "error": self._error(-32601, "Method not supported")}
        if modern:
            # MCP 2026-07-28 results are explicitly complete and identify the
            # server per response; older clients keep the legacy result shape.
            result["resultType"] = "complete"
            result["_meta"] = {"io.modelcontextprotocol/serverInfo": SERVER_INFO}
        return {"jsonrpc": "2.0", "id": id_, "result": result}


def serve_stdio(service, *, source=None, sink=None):
    inp = sys.stdin.buffer if source is None else source
    out = sys.stdout if sink is None else sink
    for line in inp:
        if len(line) > 16384:
            break
        try:
            message = json.loads(line)
            reply = service.dispatch(message)
        except (TypeError, ValueError, UnicodeDecodeError):
            reply = {"jsonrpc": "2.0", "id": None,
                     "error": MCPStdio._error(-32700, "Invalid JSON")}
        if reply is not None:
            out.write(json.dumps(reply, separators=(",", ":")) + "\n")
            out.flush()


def main():
    from m1_development_bridge import require_m1
    require_m1()
    if os.getuid() != 501 or os.geteuid() != os.getuid():
        raise SystemExit("M1 owner session required")
    host, session_id, token = _new_readonly_host(OperatorAggregateProxy())
    # Tunnel stdio children may stay alive for days; refresh ONLY the fixed
    # no-effect local owner status principal on expiry, not the tunnel key.
    serve_stdio(MCPStdio(
        host, session_id, token,
        readonly_host_refresh=lambda: _new_readonly_host(OperatorAggregateProxy())))


if __name__ == "__main__":
    main()
