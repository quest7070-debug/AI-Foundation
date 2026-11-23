"""M1-only ephemeral host canary: real SQLite Guard, never production DB.

This is NOT an owner delegation service. Explicit fixed grants belong only to
new temporary synthetic Guard requests, never to live Operator state.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from m1_development_bridge import require_m1
from foundation_mcp_stdio import MCPStdio, serve_stdio
from ai_foundation.core import GuardState
from ai_foundation.guard import GuardCore
from ai_foundation.mcp_host import AuthenticatedMcpHost, McpHostAuthorizer
from ai_foundation.operator_actions import OperatorActions
from ai_foundation.operator_server import OperatorApplication
from ai_foundation.primary_review_events import PrimaryReviewTransitions, primary_review_notices
from ai_foundation.productization import FoundationConfig
from ai_foundation.store import SQLiteGuardStore
from ai_foundation.durable_work import SQLiteWorkStore
from ai_foundation.orchestration import WorkStatus

APPROVE = "m1-canary-approve"
DENY = "m1-canary-deny"
OTHER = "m1-canary-other"


def _owner_scope(principal, tool, run_id):
    if principal.principal_id != "m1-fixture-owner":
        return False
    if tool == "approval_requests":
        return run_id in ("", APPROVE, DENY)
    if tool == "review_candidate":
        return run_id in (APPROVE, DENY)
    if tool == "submit_decision:AUTHORIZE":
        return run_id == APPROVE
    if tool == "submit_decision:DENY":
        return run_id == DENY
    return False


def main():
    require_m1()
    if os.getuid() != 501 or os.geteuid() != os.getuid():
        raise SystemExit("M1_OWNER_SESSION_REQUIRED")
    with tempfile.TemporaryDirectory(prefix="foundation-mcp-guard-fixture-") as temporary:
        root = Path(temporary).resolve()
        os.chmod(root, 0o700)
        config = FoundationConfig(str(root))
        store = SQLiteGuardStore(root / config.guard_db)
        guard = GuardCore(store.runtime_state(), store=store)
        for run, action, effect in (
            (APPROVE, "production_deploy", "canary-effect-a"),
            (DENY, "delete", "canary-effect-b"),
            (OTHER, "send_email", "canary-effect-c"),
        ):
            store.request_approval(run, action, "synthetic-fixture-only", "fixture-revision", effect)
        work_path = root / config.work_db
        work = SQLiteWorkStore(work_path)
        work.ensure("m1-canary-question", ("review",))
        work.set("m1-canary-question", 0, WorkStatus.WAITING_HUMAN)
        events = PrimaryReviewTransitions(work_path)
        generation = hashlib.sha256(b"m1-scoped-stdio-fixture-generation").hexdigest()
        if not events.started("m1-canary-question", generation):
            raise RuntimeError("CANARY_START_NOT_DURABLE")
        if not events.resolved("m1-canary-question", generation, "NO_MATCHING_EVIDENCE"):
            raise RuntimeError("CANARY_RESULT_NOT_DURABLE")
        app = OperatorApplication(config, OperatorActions(guard),
                                  operational_notices=lambda: primary_review_notices(work_path))
        authorizer = McpHostAuthorizer(owner_authorize=_owner_scope)
        granted = {"foundation_status", "approval_requests", "review_candidate",
                   "submit_decision:AUTHORIZE", "submit_decision:DENY"}
        principal, token = AuthenticatedMcpHost.issue_principal("m1-fixture-owner", granted)
        authorizer.register(principal, token)
        server = MCPStdio(AuthenticatedMcpHost(app, authorizer), principal.session_id, token,
                          exposed_tools=("foundation_status", "approval_requests",
                                         "review_candidate", "submit_decision"))
        serve_stdio(server)
        if (not store.is_approved(APPROVE) or not store.is_cancelled(DENY)
                or store.is_approved(OTHER) or store.is_cancelled(OTHER)
                or store.has_pending(APPROVE) or store.has_pending(DENY)
                or not store.has_pending(OTHER)):
            raise RuntimeError("CANARY_GUARD_FINAL_READBACK_FAILED")
        notices = primary_review_notices(work_path)
        if (sum(x.status == "PRIMARY_REVIEW_STARTED" for x in notices) != 1
                or sum(x.status == "PRIMARY_REVIEW_RESOLVED" for x in notices) != 1
                or sum(x.status == "OWNER_REVIEW_REQUIRED" for x in notices) != 1):
            raise RuntimeError("CANARY_LV2_LV4_READBACK_FAILED")
        sys.stderr.write("M1_SCOPED_CANARY_GUARD=VERIFIED\n")


if __name__ == "__main__":
    main()
