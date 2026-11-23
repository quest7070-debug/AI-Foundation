"""Authenticated MCP host integration boundary.

This wraps the existing bounded OperatorMcpTools with an explicit, host-owned
principal/session binding. It does not start a listener, expose a shell, read
private HumanModel content, or authorize actions from model/user arguments.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from dataclasses import dataclass

from .operator_mcp_tools import OperatorMcpTools

_PRINCIPAL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}\Z")
_ALLOWED = {
    "foundation_status", "approval_requests", "review_candidate",
    "submit_decision:AUTHORIZE", "submit_decision:DENY",
    "human_model_status", "human_model_collect",
    "human_model_revoke", "human_model_refresh",
    "human_model_answer", "human_model_correct",
    "development_run", "development_status", "development_deliver", "development_list",
    "development_request", "development_admit", "development_continue", "development_cycle",
}


@dataclass(frozen=True)
class McpHostPrincipal:
    principal_id: str
    session_id: str
    scopes: frozenset[str]
    issued_at: float
    expires_at: float

    def __post_init__(self):
        if not isinstance(self.principal_id, str) or not _PRINCIPAL.fullmatch(self.principal_id):
            raise ValueError("invalid principal_id")
        if not isinstance(self.session_id, str) or not self.session_id:
            raise ValueError("invalid session_id")
        scopes = frozenset(s for s in (self.scopes or ()) if s in _ALLOWED)
        object.__setattr__(self, "scopes", scopes)
        for name in ("issued_at", "expires_at"):
            value = float(getattr(self, name))
            object.__setattr__(self, name, value)
        if self.expires_at <= self.issued_at:
            raise ValueError("principal expired")


class McpHostAuthorizer:
    """Host-owned session authorization. Tokens are compared in constant time."""

    def __init__(self, sessions=None, *, now=time.time, owner_authorize=None):
        # This callback must come from the trusted host's independently
        # authenticated owner/run delegation store, never from model or MCP
        # arguments. Without one, approval metadata and writes are unavailable.
        if owner_authorize is not None and not callable(owner_authorize):
            raise ValueError("trusted owner authorizer must be callable")
        self._sessions = dict(sessions or {})
        self._now = now
        self._owner_authorize = owner_authorize

    def register(self, principal, token):
        if not isinstance(principal, McpHostPrincipal):
            raise ValueError("principal required")
        if not isinstance(token, str) or not 32 <= len(token) <= 2048:
            raise ValueError("invalid host session token")
        if not principal.issued_at <= self._now() < principal.expires_at:
            raise ValueError("host principal not active")
        if principal.session_id in self._sessions:
            raise ValueError("host session already registered")
        self._sessions[principal.session_id] = (principal, token)

    def authenticate(self, session_id, token):
        row = self._sessions.get(session_id)
        if row is None or not isinstance(token, str):
            return None
        principal, expected = row
        if not hmac.compare_digest(expected, token):
            return None
        if not principal.issued_at <= self._now() < principal.expires_at:
            return None
        return principal

    def authorize(self, principal, tool, run_id=""):
        if not isinstance(principal, McpHostPrincipal):
            return False
        row = self._sessions.get(principal.session_id)
        if (row is None or row[0] is not principal
                or not principal.issued_at <= self._now() < principal.expires_at
                or tool not in principal.scopes or tool not in _ALLOWED):
            return False
        # Aggregate status contains no owner-specific request references.
        if tool == "foundation_status":
            return True
        # A session grant alone never licenses reading or deciding another
        # owner's exact pending Guard request.
        if self._owner_authorize is None:
            return False
        try:
            return self._owner_authorize(principal, tool, run_id) is True
        except Exception:
            return False


class AuthenticatedMcpHost:
    """Transport-agnostic authenticated host integration for bounded Operator tools."""

    def __init__(self, operator, authorizer, *, claim_owner_decision=None,
                 human_model_port=None, development_port=None):
        self.authorizer = authorizer
        self.tools = OperatorMcpTools(
            operator, authorize=authorizer.authorize,
            claim_owner_decision=claim_owner_decision)
        # No host-provided owner source port => these tools are unavailable.
        # Optional port uses the existing authenticated session, Guard and
        # original HumanModel ledger; never a second server/approval store.
        self.human_model_port = human_model_port
        self.development_port = development_port
        if development_port is not None:
            actions = getattr(operator, "actions", None)
            if (actions is None or getattr(actions, "guard", None) is not development_port.guard
                    or not callable(getattr(development_port, "run", None))
                    or not callable(getattr(development_port, "status", None))):
                raise ValueError("SAME_OPERATOR_GUARD_DEVELOPMENT_PORT_REQUIRED")
        if human_model_port is not None:
            actions = getattr(operator, "actions", None)
            if (actions is None or
                    getattr(actions, "guard", None) is not human_model_port.consent.guard or
                    not callable(getattr(actions, "bind_cancel_observer", None)) or
                    not callable(getattr(human_model_port, "on_guard_cancelled", None))):
                raise ValueError("SAME_OPERATOR_GUARD_OWNER_PORT_REQUIRED")
            # The same Operator UI and existing MCP denial path now forward
            # durable Guard cancellation to the exact owner-side view.
            actions.bind_cancel_observer(human_model_port.on_guard_cancelled)

    @staticmethod
    def issue_principal(principal_id, scopes, *, ttl_seconds=900, now=time.time):
        issued = float(now())
        return McpHostPrincipal(
            principal_id=principal_id,
            session_id="mcp-" + secrets.token_hex(16),
            scopes=frozenset(scopes),
            issued_at=issued,
            expires_at=issued + max(60, int(ttl_seconds)),
        ), secrets.token_urlsafe(32)

    def dispatch(self, session_id, token, tool, arguments=None):
        principal = self.authorizer.authenticate(session_id, token)
        if principal is None:
            raise PermissionError("host-authenticated MCP principal required")
        args = {} if arguments is None else arguments
        if not isinstance(args, dict):
            raise ValueError("arguments must be an object")
        expected = {
            "foundation_status": frozenset(),
            "approval_requests": frozenset(),
            "review_candidate": frozenset({"run_id", "request_ref"}),
            "submit_decision": frozenset({"run_id", "request_ref", "decision"}),
            "human_model_status": frozenset(),
            "human_model_collect": frozenset({"source_system", "record_id", "scope", "run_id"}),
            "human_model_revoke": frozenset({"run_id"}),
            "human_model_refresh": frozenset(),
            "human_model_answer": frozenset({"question", "scope"}),
            "human_model_correct": frozenset({"source_system", "record_id", "scope", "run_id",
                                               "corrects_evidence_sha256", "task_id",
                                               "generation_sha256", "answer_evidence_sha256"}),
            "development_list": frozenset(),
            "development_request": frozenset({"ticket_id", "instruction"}),
            "development_admit": frozenset({"ticket_id"}),
            "development_continue": frozenset({"ticket_id"}),
            "development_cycle": frozenset(),
            "development_run": frozenset({"ticket_id"}),
            "development_status": frozenset({"ticket_id"}),
            "development_deliver": frozenset({"ticket_id"}),
        }
        if tool not in expected or frozenset(args) != expected[tool]:
            raise ValueError("unsupported tool or arguments")
        try:
            if tool.startswith("development_"):
                port = self.development_port
                if tool == "development_admit":
                    ticket_id = args["ticket_id"]
                    if (port is None or not getattr(port, "can_admit", False)
                            or type(ticket_id) is not str
                            or self.authorizer.authorize(principal, tool, ticket_id) is not True):
                        raise PermissionError("host reviewed development admission not authorized")
                    return port.admit(principal, ticket_id)
                if tool == "development_continue":
                    ticket_id = args["ticket_id"]
                    # A single call may perform admission and execution only
                    # when the same host-authenticated principal already has
                    # BOTH explicit authorities plus this continuation scope.
                    if (port is None or not getattr(port, "can_admit", False)
                            or not callable(getattr(port, "continue_reviewed", None))
                            or type(ticket_id) is not str
                            or not all(self.authorizer.authorize(
                                principal, name, ticket_id) is True
                                for name in ("development_continue", "development_admit",
                                             "development_run"))):
                        raise PermissionError("host reviewed continuation not authorized")
                    outcome = port.continue_reviewed(principal, ticket_id)
                    # Automatic delivery is Draft-only and ONLY when the
                    # original owner manifest independently permits delivery
                    # AND the current principal has the separate delivery scope.
                    if (outcome.get("state") == "VERIFIED_LOCAL"
                            and not outcome.get("github_published")
                            and "delivery_state" not in outcome
                            and self.authorizer.authorize(
                                principal, "development_deliver", ticket_id) is True):
                        return port.deliver(principal, ticket_id)
                    return outcome
                if tool == "development_cycle":
                    # One current-host-authorized development ticket per call:
                    # no list-scope shortcut to arbitrary execution.
                    if (port is None or not callable(getattr(port, "cycle_one", None))
                            or not all(self.authorizer.authorize(principal, scope) is True
                                       for scope in ("development_cycle", "development_list"))):
                        raise PermissionError("host autonomous development cycle not authorized")
                    def allowed(ticket):
                        return all(self.authorizer.authorize(principal, scope, ticket) is True
                                   for scope in ("development_status", "development_run"))
                    def pending(ticket):
                        return all(self.authorizer.authorize(principal, scope, ticket) is True
                                   for scope in ("development_admit", "development_continue"))
                    # One host-bound cycle also completes already tested
                    # CODE work when the existing separate Draft grant permits.
                    # No fresh permission, review, second model or test run.
                    def delivery(ticket):
                        return (self.authorizer.authorize(
                            principal, "development_deliver", ticket) is True
                            and port.authorize_delivery(principal, ticket) is True)
                    result = port.cycle_one(
                        principal, authorize_status=allowed,
                        authorize_pending=pending, authorize_delivery=delivery)
                    ticket = result.get("ticket_id")
                    if (result.get("state") == "VERIFIED_LOCAL"
                            and not result.get("github_published")
                            and "delivery_state" not in result
                            and type(ticket) is str and delivery(ticket)):
                        return port.deliver(principal, ticket)
                    return result
                if tool == "development_request":
                    if (port is None or not callable(getattr(port, "request", None))
                            or self.authorizer.authorize(principal, tool) is not True):
                        raise PermissionError("host development request not authorized")
                    return port.request(principal, **args)
                if tool == "development_list":
                    if (port is None
                            or not callable(getattr(port, "list_tickets", None))
                            or self.authorizer.authorize(principal, tool) is not True):
                        raise PermissionError("host development inventory not authorized")
                    return port.list_tickets(principal, authorize_status=lambda ticket:
                        self.authorizer.authorize(principal, "development_status", ticket))
                ticket_id = args["ticket_id"]
                if (port is None or type(ticket_id) is not str
                        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", ticket_id)
                        or self.authorizer.authorize(principal, tool, ticket_id) is not True):
                    raise PermissionError("host development scope not authorized")
                if tool == "development_run":
                    return port.run(principal, ticket_id)
                if tool == "development_deliver":
                    return port.deliver(principal, ticket_id)
                return port.status(principal, ticket_id)
            if tool.startswith("human_model_"):
                port = self.human_model_port
                if port is None or self.authorizer.authorize(
                        principal, tool, args.get("run_id", "")) is not True:
                    raise PermissionError("host owner HumanModel scope not authorized")
                if tool == "human_model_status":
                    return port.status(principal)
                if tool == "human_model_collect":
                    return port.collect(principal, **args)
                if tool == "human_model_correct":
                    if getattr(port, "can_correct", False) is not True:
                        raise PermissionError("host owner correction not connected")
                    return port.correct(principal, **args)
                if tool == "human_model_revoke":
                    return port.revoked(principal, run_id=args["run_id"])
                if tool == "human_model_refresh":
                    return port.refresh(principal)
                if tool == "human_model_answer":
                    return port.answer(principal, **args)
            if tool == "foundation_status":
                return self.tools.foundation_status(principal)
            if tool == "approval_requests":
                return self.tools.approval_requests(principal)
            if tool == "review_candidate":
                return self.tools.review_candidate(principal, args.get("run_id"), args.get("request_ref"))
            if tool == "submit_decision":
                return self.tools.submit_decision(
                    principal, args.get("run_id"), args.get("request_ref"), args.get("decision"))
        except PermissionError:
            raise
        except (TypeError, ValueError, KeyError) as exc:
            raise ValueError(str(exc)) from exc
        raise ValueError("unsupported MCP tool")

    def tool_catalog(self):
        result = {
            "foundation_status": {"writes": False},
            "approval_requests": {"writes": False},
            "review_candidate": {"writes": False},
            "submit_decision": {"writes": True, "decisions": ["AUTHORIZE", "DENY"]},
        }
        if self.development_port is not None:
            result.update({
                "development_list": {"writes": False, "local_only": True,
                                     "requires_host_bound_ticket": True},
                "development_run": {"writes": True, "local_only": True,
                                    "requires_host_bound_ticket": True},
                "development_status": {"writes": False, "local_only": True,
                                       "requires_host_bound_ticket": True},
                "development_deliver": {"writes": True, "draft_only": True,
                                        "requires_owner_delivery_opt_in": True},
            })
        if self.development_port is not None and callable(getattr(self.development_port, "request", None)):
            result["development_request"] = {"writes": True, "requires_host_review": True,
                                             "executes_code": False}
        if self.development_port is not None and getattr(self.development_port, "can_admit", False):
            result["development_admit"] = {"writes": True, "requires_host_review": True,
                                           "executes_code": False}
            result["development_continue"] = {"writes": True, "local_only": True,
                                               "requires_host_review": True,
                                               "requires_existing_admit_and_run_scopes": True,
                                               "draft_only_when_separately_owner_enabled": True}
            result["development_cycle"] = {"writes": True, "local_only": True,
                                            "max_executions": 1,
                                            "requires_exact_ticket_authorization": True,
                                            "requires_existing_owner_review": True,
                                            "draft_only_when_separately_owner_enabled": True}
        if self.human_model_port is not None:
            result.update({
                "human_model_status": {"writes": False},
                "human_model_collect": {"writes": True, "requires_approved_source": True},
                "human_model_revoke": {"writes": True, "requires_guard_cancellation": True},
                "human_model_refresh": {"writes": True, "requires_owner_source": True},
                **({"human_model_correct": {"writes": True,
                     "requires_authenticated_original_source": True,
                     "requires_exact_correction_authority": True,
                     "preserves_original_evidence": True}}
                   if getattr(self.human_model_port, "can_correct", False) is True else {}),
                **({"human_model_answer": {"writes": False,
                     "requires_authenticated_owner": True}}
                   if self.human_model_port.answer_agent_factory is not None else {}),
            })
        return result
