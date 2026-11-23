"""Host-authenticated, transport-independent MCP tool boundary for Operator.

The MCP transport MUST supply an independently authenticated principal and an
authorizer owned by the trusted host. Never construct a principal from model
arguments, an HTTP owner header, a question body, or HumanModel data. The
adapter has no listener, credentials, model, shell, deployment or new DB.
"""
from __future__ import annotations

import re

_SUBJECT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_REF = re.compile(r"[a-f0-9]{64}\Z")
_SAFE_ACTIONS = frozenset({"purchase", "delete", "send_email", "production_deploy", "development_scope"})
# Public, finite observations from the trusted installed Operator. No
# connected-AI caller can supply them as metadata or gain approval from them.
WORKER_STATES = frozenset({"RUNNING", "RECONCILE_REQUIRED", "LAST_EXIT_NONZERO",
                           "SCHEDULED_IDLE", "UNKNOWN"})
QUEUE_STATES = frozenset({"RUNNING", "RECONCILE_REQUIRED", "WORKER_EXIT_NONZERO",
                          "QUEUED_NOT_RUNNING", "NO_QUEUED_TASK",
                          "LOCAL_WORK_CYCLE_OBSERVED", "SCHEDULED_CYCLE_BLOCKED",
                          "UNAVAILABLE", "UNKNOWN"})
KLM_STATES = frozenset({"CURRENT", "RESYNC_PARTIAL", "REPLAY_PARTIAL",
                        "RESCAN_REQUIRED", "NOT_DUE", "DRIVE_AUTH_REQUIRED",
                        "HOST_BINDING_BLOCKED", "POLL_FAILED",
                        "SYNC_ACTIVE_OR_RECONCILE_REQUIRED",
                        "CLOCK_RECONCILE_REQUIRED"})


def _observed(dev, field, states):
    value = dev.get(field)
    return value if type(value) is str and value in states else "UNVERIFIED"



class OperatorMcpTools:
    """Four bounded tools backed by the SAME current Operator and Guard.

    `authorize` is a host-owned callback: (principal, tool, run_id) -> bool.
    It must bind the principal to an authenticated MCP session and explicitly
    delegate each write. This class never accepts self-asserted authorization.
    """

    def __init__(self, operator, *, authorize, claim_owner_decision=None):
        if not callable(authorize):
            raise ValueError("authenticated host authorizer required")
        if claim_owner_decision is not None and not callable(claim_owner_decision):
            raise ValueError("invalid trusted owner decision claim")
        self._operator = operator
        self._authorize = authorize
        # Existing host tests may exercise their own scoped authorizer. The
        # installed write-enabled host MUST provide an owner-issued claim.
        self._claim_owner_decision = claim_owner_decision

    def _require(self, principal, tool, run_id=""):
        if principal is None:
            raise PermissionError("host-authenticated MCP principal required")
        try:
            allowed = self._authorize(principal, tool, run_id)
        except Exception:
            allowed = False
        if allowed is not True:
            raise PermissionError("MCP scope not authorized")

    def _pending(self):
        # Read the current Guard-backed Operator projection; it is bounded to
        # the existing 100-row window. No new approval state is maintained.
        rows = self._operator.snapshot().as_dict().get("attention", ())
        return {
            row["run_id"]: row
            for row in rows
            if row.get("kind") == "approval"
            and isinstance(row.get("run_id"), str)
        }

    @staticmethod
    def _unverified_operator_status(reason):
        """Bounded public no-evidence receipt, never an invented 0/healthy state.

        The live Operator HTTP projection is a source of truth, not an
        authentication authority. Its disappearance must not remove the
        independently authenticated MCP owner's ability to see a degraded
        status. Every counter stays null until original evidence returns.
        """
        if reason not in {"OPERATOR_HTTP_UNAVAILABLE",
                          "OPERATOR_PROJECTION_UNVERIFIED"}:
            raise ValueError("invalid Operator evidence class")
        return {
            "state": "UNKNOWN",
            "runtime_health": "UNVERIFIED",
            "operator_observation": reason,
            "failed_effect_history": None,
            "dismissed_failed_notices": None,
            "notice_levels": {str(level): None for level in range(1, 6)},
            "services_ok": None,
            "services_unavailable": None,
            "services_down": None,
            "services_unverified": None,
            "guard_pending": None,
            "work_failed": None,
            "work_uncertain": None,
            "worker_runtime": "UNVERIFIED",
            "worker_queue": "UNVERIFIED",
            "klm_runtime": "UNVERIFIED",
            "direct_mcp_work": "UNVERIFIED",
            "direct_mcp_verified_receipts": None,
            "code_review_required": None,
            "code_admitted_requests": None,
            "code_failed_local_attempts": None,
            "approved_humanmodel_view": _observed(
                development, "approved_humanmodel_view",
                {"UNVERIFIED", "AVAILABLE", "BLOCKED", "STALE"}),
        }

    def foundation_status(self, principal):
        """Return truthfully bounded Operator evidence after MCP authorization.

        A healthy owner's development-list transport does not imply that
        /api/human is responsive. A genuine HTTP failure becomes a fixed,
        no-evidence read-only receipt; none of the status counters is forged
        as zero. Principal and Guard authorization errors remain rejected.
        """
        self._require(principal, "foundation_status")
        try:
            view = self._operator.human_payload()
        except PermissionError:
            # Do not disguise an internal authority denial as connectivity.
            raise
        except (OSError, TimeoutError):
            return self._unverified_operator_status("OPERATOR_HTTP_UNAVAILABLE")
        except (ValueError, TypeError):
            return self._unverified_operator_status(
                "OPERATOR_PROJECTION_UNVERIFIED")
        if (type(view) is not dict
                or type(view.get("notices")) not in (tuple, list)
                or len(view["notices"]) > 200
                or any(type(x) is not dict for x in view["notices"])
                or type(view.get("services")) not in (tuple, list)
                or len(view["services"]) > 100
                or any(type(x) is not dict for x in view["services"])):
            return self._unverified_operator_status(
                "OPERATOR_PROJECTION_UNVERIFIED")

        notices = view["notices"]
        services = view["services"]
        development = view.get("development")
        development = development if type(development) is dict else {}
        source = development.get("source")
        guard_bound = source in {
            "CURRENT_GUARD_WORK_SNAPSHOT",
            "CURRENT_GUARD_WORK_SNAPSHOT+M1_OWNER_RUNTIME",
        }
        worker_bound = source == "CURRENT_GUARD_WORK_SNAPSHOT+M1_OWNER_RUNTIME"

        def observed_count(field, maximum=1000000):
            value = development.get(field)
            return (value if guard_bound and type(value) is int
                    and 0 <= value <= maximum else None)

        observed_pending = observed_count("guard_actionable", 100)
        runtime_health = view.get("runtime_health")
        if type(runtime_health) is not str or runtime_health not in {
                "READY", "DEGRADED", "RECOVERING", "UNVERIFIED"}:
            runtime_health = "UNVERIFIED"
        diagnostics = view.get("state_diagnostics")
        diagnostics = diagnostics if type(diagnostics) is dict else {}

        def failure_count(name):
            value = diagnostics.get(name)
            return value if type(value) is int and 0 <= value <= 100000 else None

        return {
            "state": view.get("state", "UNKNOWN"),
            "runtime_health": runtime_health,
            "operator_observation": "CURRENT_OPERATOR_API",
            "failed_effect_history": failure_count("failed_effect_window"),
            "dismissed_failed_notices": failure_count(
                "dismissed_failed_notices_window"),
            "notice_levels": {
                str(level): sum(n.get("level") == level for n in notices)
                for level in range(1, 6)
            },
            "services_ok": sum(s.get("ok") is True for s in services),
            # Keep the historical unavailable count for extant clients.
            "services_unavailable": sum(s.get("ok") is not True
                                        for s in services),
            "services_down": sum(s.get("ok") is False for s in services),
            "services_unverified": sum(type(s.get("ok")) is not bool
                                       for s in services),
            "guard_pending": (observed_pending if observed_pending is not None
                              else sum(n.get("status") == "WAITING_HUMAN"
                                       and bool(n.get("approval_ref"))
                                       for n in notices)),
            "work_failed": observed_count("work_failed"),
            "work_uncertain": observed_count("work_uncertain"),
            "code_review_required": observed_count("code_review_required"),
            "code_admitted_requests": observed_count("code_admitted_requests"),
            "code_failed_local_attempts": observed_count("code_failed_local_attempts"),
            "worker_runtime": (
                _observed(development, "local9b_worker", WORKER_STATES)
                if worker_bound else "UNVERIFIED"),
            "worker_queue": (
                _observed(development, "local9b_queue_state", QUEUE_STATES)
                if worker_bound else "UNVERIFIED"),
            "klm_runtime": _observed(development, "klm_status", KLM_STATES),
            "direct_mcp_work": (
                development.get("direct_mcp_status")
                if development.get("direct_mcp_status") in {
                    "WORK_RECEIPTS_ONLY", "NO_WORK_RECEIPTS"}
                else "UNVERIFIED"),
            "direct_mcp_verified_receipts": (
                development.get("direct_mcp_verified_receipts")
                if type(development.get("direct_mcp_verified_receipts")) is int
                else None),
            "approved_humanmodel_view": _observed(
                development, "approved_humanmodel_view",
                {"UNVERIFIED", "AVAILABLE", "BLOCKED", "STALE"}),
        }

    def approval_requests(self, principal):
        self._require(principal, "approval_requests")
        results = []
        for run, row in self._pending().items():
            # Listing permission is not a grant to enumerate other owners'
            # pending actions. Check each exact run against the trusted host
            # delegation, just as review/decision already do.
            try:
                self._require(principal, "approval_requests", run)
            except PermissionError:
                continue
            ref = row.get("approval_ref", "")
            results.append({
                "run_id": run,
                "action": row.get("action") if row.get("action") in _SAFE_ACTIONS else "other",
                "request_ref": ref if isinstance(ref, str) and _REF.fullmatch(ref) else "",
                "actionable": bool(isinstance(ref, str) and _REF.fullmatch(ref)),
            })
        return tuple(results)

    def review_candidate(self, principal, run_id, request_ref):
        self._require(principal, "review_candidate", run_id)
        current = self._is_current(run_id, request_ref)
        return {"run_id": run_id, "current": current,
                "requires_explicit_authority": True, "authorized": False}

    def _is_current(self, run_id, request_ref):
        if (not isinstance(run_id, str) or not _SUBJECT.fullmatch(run_id)
                or not isinstance(request_ref, str) or not _REF.fullmatch(request_ref)):
            return False
        row = self._pending().get(run_id)
        return bool(row and row.get("approval_ref") == request_ref)

    def submit_decision(self, principal, run_id, request_ref, decision):
        # A read grant is never a decision grant. Authorize by exact run and
        # decision, not only by general MCP connection.
        tool = {"AUTHORIZE": "submit_decision:AUTHORIZE",
                "DENY": "submit_decision:DENY"}.get(decision)
        if tool is None:
            raise ValueError("only AUTHORIZE or DENY supported")
        self._require(principal, tool, run_id)
        if not self._is_current(run_id, request_ref):
            return {"ok": False, "status": "STALE_OR_UNBOUND_APPROVAL"}
        guard = getattr(self._operator.actions, "guard", None)
        store = getattr(guard, "store", None)
        # Never invoke OperatorApplication.act's legacy in-memory fallback.
        if (store is None or not hasattr(store, "approve_pending")
                or not hasattr(store, "cancel_pending")):
            return {"ok": False, "status": "DURABLE_GUARD_UNAVAILABLE"}
        if self._claim_owner_decision is not None:
            try:
                consumed = self._claim_owner_decision(
                    principal, run_id, request_ref, decision)
            except Exception:
                consumed = False
            if consumed is not True:
                return {"ok": False, "status": "OWNER_DELEGATION_MISSING_OR_CONSUMED"}
        result = self._operator.act(
            "approve" if decision == "AUTHORIZE" else "cancel",
            run_id, request_ref,
        )
        return {"ok": bool(result.ok), "status": result.status}
