#!/usr/bin/env python3
"""Production acceptance proof for canonical human DISMISS and DENY actions.

One canonical Guard approval is used for both proofs:
preflight -> WAITING_HUMAN -> dismiss presentation only -> restart/readback ->
deny authority -> restart/readback.

No direct SQL, manufactured work row, fake notice, or external effect execution.
"""
import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from ai_foundation.core import CanonContract, Decision, TaskPlan
from ai_foundation.guard import GuardCore
from ai_foundation.productization import load_config
from ai_foundation.store import SQLiteGuardStore

BASE = "http://127.0.0.1:8766"


def get_human():
    with urllib.request.urlopen(BASE + "/api/human", timeout=5) as response:
        return json.load(response)


def get_csrf():
    with urllib.request.urlopen(BASE + "/", timeout=5) as response:
        page = response.read().decode()
    match = re.search(r'name=csrf value="([^"]+)"', page)
    if match is None:
        raise RuntimeError("Operator CSRF token not found")
    return match.group(1)


def post(path):
    body = urllib.parse.urlencode(
        {"csrf": get_csrf(), "return_to": "/api/human"}
    ).encode()
    request = urllib.request.Request(BASE + path, data=body, method="POST")
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status


def restart_operator():
    subprocess.run(
        [
            "launchctl",
            "kickstart",
            "-k",
            f"gui/{os.getuid()}/dev.quest7070.ai-foundation.operator",
        ],
        check=True,
    )
    for _ in range(40):
        try:
            get_human()
            return
        except Exception:
            time.sleep(0.25)
    raise RuntimeError("Operator did not recover after restart")


def visible_notice(subject, status):
    return next(
        (
            row
            for row in get_human().get("notices", [])
            if row.get("subject") == subject and row.get("status") == status
        ),
        None,
    )


def rebuilt_guard(db):
    store = SQLiteGuardStore(db)
    return GuardCore(store.runtime_state(), store=store)


def main(config_path):
    config = load_config(config_path)
    db = Path(config.data_dir) / config.guard_db
    run_id = "w12-" + uuid.uuid4().hex
    plan = TaskPlan(
        run_id,
        "send_email",
        "w12-nonexecuted-target",
        text="W12 approval-boundary acceptance probe; external effect must not execute",
        canon_revision="w12-audit",
    )
    canon = CanonContract("w12-audit", "w12-audit")

    try:
        guard = rebuilt_guard(db)

        # Canonical producer only. preflight requests approval but executes no effect.
        if guard.preflight(plan, canon) is not Decision.WAITING_HUMAN:
            raise RuntimeError("Guard did not enter WAITING_HUMAN")

        if visible_notice(run_id, "WAITING_HUMAN") is None:
            raise RuntimeError("canonical approval notice is not visible")

        # DISMISS: presentation state only.
        if post(
            "/notification/dismiss/" + urllib.parse.quote(run_id, safe="")
        ) != 200:
            raise RuntimeError("DISMISS HTTP action failed")

        if visible_notice(run_id, "WAITING_HUMAN") is not None:
            raise RuntimeError("DISMISS did not hide current notice")

        # Independent authoritative readback: approval must still be pending.
        if rebuilt_guard(db).preflight(plan, canon) is not Decision.WAITING_HUMAN:
            raise RuntimeError("DISMISS mutated authoritative approval state")

        restart_operator()

        if visible_notice(run_id, "WAITING_HUMAN") is not None:
            raise RuntimeError("DISMISS did not survive Operator restart")
        if rebuilt_guard(db).preflight(plan, canon) is not Decision.WAITING_HUMAN:
            raise RuntimeError("approval state changed across DISMISS restart")

        # DENY: authoritative cancel boundary.
        if post("/action/cancel/" + urllib.parse.quote(run_id, safe="")) != 200:
            raise RuntimeError("DENY HTTP action failed")

        if rebuilt_guard(db).preflight(plan, canon) is not Decision.DENY:
            raise RuntimeError("DENY did not persist in authoritative Guard state")

        restart_operator()

        if rebuilt_guard(db).preflight(plan, canon) is not Decision.DENY:
            raise RuntimeError("DENY did not survive Operator restart")
        if visible_notice(run_id, "WAITING_HUMAN") is not None:
            raise RuntimeError("resolved approval became visible after restart")

        print(
            json.dumps(
                {
                    "status": "PASS",
                    "producer": "Guard.preflight",
                    "external_effect_executed": False,
                    "dismiss": "DURABLE_PRESENTATION_ONLY",
                    "dismiss_restart_readback": True,
                    "deny": "DURABLE_AUTHORITY",
                    "deny_restart_readback": True,
                },
                separators=(",", ":"),
            )
        )
    finally:
        # Canonical idempotent cleanup of this audit-owned approval/cancellation.
        try:
            rebuilt_guard(db).cancel(run_id)
        except Exception:
            pass


if __name__ == "__main__":
    import sys

    main(sys.argv[1])
