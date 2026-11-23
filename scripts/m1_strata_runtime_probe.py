"""Read-only same-owner M1 -> MainPC Strata CODE endpoint probe.

This performs at most one authenticated GET /v1/models through the existing,
owner-configured local endpoint discovery. No chat/completion, model wake,
service changes, GitHub writes, remote private-source transfer or paid API.
A successful workflow is a diagnostic receipt, NOT code execution evidence.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import re
import subprocess

from m1_selfdev_release_preflight import ROOT, scoped_event

REQUIRED_BINDING = "local:mainpc-strata:code-agent"
REQUIRED_MODEL = "qwen3.8-flash-next-coder-iq1_m"
SAFE_REASONS = frozenset({
    "HTTP_401", "HTTP_403", "HTTP_429", "HTTP_500", "HTTP_502",
    "HTTP_503", "HTTP_504", "TimeoutError", "URLError",
    "ConnectionRefusedError", "NO_AUTHORIZED_MODEL",
})


def classify_configured_endpoints(endpoints):
    """Use the exact current host selection rather than historical receipts."""
    matches = [
        (discovery, execution)
        for prefix, discovery, execution in endpoints
        if prefix == "local:mainpc-strata"
        and getattr(execution, "models", {}).get("code-agent") == REQUIRED_MODEL
    ]
    if len(matches) != 1:
        return {"status": "STRATA_NOT_CURRENTLY_SELECTABLE",
                "reason": "EXACT_CONFIG_OR_OWNER_KEY_UNAVAILABLE",
                "strata_code_online": False, "model_calls": 0}
    discovery, _ = matches[0]
    # The existing adapter performs a bounded authenticated GET /v1/models.
    # Missing/expired auth, sleeping PC or network errors are observations,
    # never a reason to issue a chat completion or to wake the machine.
    try:
        candidates = discovery.candidates()
    except (OSError, RuntimeError, ValueError, TypeError):
        return {"status": "STRATA_NOT_CURRENTLY_SELECTABLE",
                "reason": "MODEL_DISCOVERY_UNVERIFIED",
                "strata_code_online": False, "model_calls": 0}
    ready = [c for c in candidates
             if c.binding == REQUIRED_BINDING and c.health == "ONLINE"
             and c.active is True and c.same_host is False
             and "CODE" in c.capabilities and c.model == REQUIRED_MODEL]
    if len(ready) == 1:
        return {"status": "STRATA_CODE_DISCOVERED",
                "reason": "NONE", "strata_code_online": True,
                "model_calls": 0}
    reasons = [c.reason for c in candidates
               if c.health == "UNAVAILABLE" and c.reason in SAFE_REASONS]
    return {"status": "STRATA_NOT_CURRENTLY_SELECTABLE",
            "reason": reasons[0] if len(reasons) == 1 else "NO_CODE_MODEL_OBSERVED",
            "strata_code_online": False, "model_calls": 0}


def owner_probe(event, env, current_sha, *, system, machine, uid, euid,
                endpoint_loader):
    if not scoped_event(event, env=env, current_sha=current_sha):
        return {"status": "BLOCKED", "reason": "EXACT_OWNER_PR_HEAD_REQUIRED",
                "strata_code_online": False, "model_calls": 0}
    if system != "Darwin" or machine not in ("arm64", "aarch64") or uid != euid or uid != 501:
        return {"status": "BLOCKED", "reason": "OWNER_M1_REQUIRED",
                "strata_code_online": False, "model_calls": 0}
    try:
        result = classify_configured_endpoints(endpoint_loader())
    except (OSError, ValueError, RuntimeError, TypeError, PermissionError):
        result = {"status": "STRATA_NOT_CURRENTLY_SELECTABLE",
                  "reason": "OWNER_CONFIG_UNVERIFIED",
                  "strata_code_online": False, "model_calls": 0}
    return {**result, "source_sha": current_sha,
            "remote_code_execution_proven": False,
            "owner_review_created": False,
            "model_calls": 0, "service_mutations": 0}


def main():
    from m1_direct_development import installed_config
    from ai_foundation.local_endpoint_config import load_local_endpoints
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        sha = subprocess.run(
            ["/usr/bin/git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True, timeout=5).stdout.strip()

        def endpoints():
            _, config, root = installed_config()
            path = root / "local-compute" / "endpoints.json"
            if not path.is_file() or path.is_symlink():
                raise ValueError("OWNER_ENDPOINT_CONFIG_UNVERIFIED")
            return load_local_endpoints(path)

        row = owner_probe(
            event, os.environ, sha, system=platform.system(),
            machine=platform.machine(), uid=os.getuid(), euid=os.geteuid(),
            endpoint_loader=endpoints)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        row = {"status": "BLOCKED", "reason": "OWNER_PROBE_UNVERIFIED",
               "strata_code_online": False, "model_calls": 0,
               "service_mutations": 0}
    print(json.dumps(row, sort_keys=True))
    # Offline MainPC is a valid diagnostic outcome, not a failed workflow.
    return 1 if row["status"] == "BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
