"""Synthetic, one-shot MCP Guard compatibility test on an isolated owner M1.

No Operator approval request is created or delegated from a browser.
Only an ephemeral fixture can issue these test grants; the real owner must
AUTHORIZE or DENY on the original Operator notification screen.
Never touches installed Operator/Guard/Work or any live approval.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from m1_development_bridge import require_m1
from foundation_mcp_stdio import serve_stdio
from m1_owner_delegated_mcp_stdio import build_owner_mcp
from ai_foundation.guard import GuardCore
from ai_foundation.mcp_owner_grants import McpOwnerGrants
from ai_foundation.operator_actions import OperatorActions
from ai_foundation.operator_server import OperatorApplication
from ai_foundation.productization import FoundationConfig
from ai_foundation.store import SQLiteGuardStore


class Aggregate:
    def human_payload(self):
        return {"state": "READY", "notices": [], "services": []}


def main():
    require_m1()
    if os.getuid() != 501 or os.geteuid() != os.getuid():
        raise SystemExit("M1_OWNER_SESSION_REQUIRED")

    # Every authorization is a fixture owned by THIS child process. It is not
    # a live Operator UI action and cannot identify a production Guard request.
    with tempfile.TemporaryDirectory(prefix="foundation-guard-mcp-fixture-") as temp:
        root = Path(temp).resolve()
        os.chmod(root, 0o700)
        config = FoundationConfig(str(root))
        store = SQLiteGuardStore(root / config.guard_db)
        guard = GuardCore(store.runtime_state(), store=store)
        grants = McpOwnerGrants(store, initialize=True)
        tasks = (
            ("m1-canary-approve", "production_deploy", "effect-a", "AUTHORIZE"),
            ("m1-canary-deny", "delete", "effect-b", "DENY"),
            ("m1-canary-other", "send_email", "effect-c", None),
        )
        for run, action, effect, _ in tasks:
            if not store.request_approval(run, action, "fixture-only",
                                          "canon-fixture", effect):
                raise RuntimeError("FIXTURE_APPROVAL_CREATE_DENIED")

        app = OperatorApplication(config, OperatorActions(guard),
                                  csrf_token="fixture-never-live")
        approvals = app.snapshot().as_dict()["attention"]
        refs = {row["run_id"]: row["approval_ref"] for row in approvals
                if row.get("kind") == "approval"}
        for run, _, _, decision in tasks:
            if decision is None:
                continue
            if not grants.issue(run, refs[run], decision):
                raise RuntimeError("FIXTURE_GRANT_DENIED")

        if (store.is_approved("m1-canary-approve")
                or store.is_cancelled("m1-canary-deny")):
            raise RuntimeError("FIXTURE_GRANT_MUST_NOT_DECIDE")
        serve_stdio(build_owner_mcp(store, aggregate=Aggregate()))
        if (not store.is_approved("m1-canary-approve")
                or not store.is_cancelled("m1-canary-deny")
                or store.is_approved("m1-canary-other")
                or store.is_cancelled("m1-canary-other")
                or store.has_pending("m1-canary-approve")
                or store.has_pending("m1-canary-deny")
                or not store.has_pending("m1-canary-other")):
            raise RuntimeError("FIXTURE_GUARD_CAS_FAILED")
        sys.stderr.write("M1_OWNER_GRANT_CANARY=VERIFIED\n")


if __name__ == "__main__":
    main()
