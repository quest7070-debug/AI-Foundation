"""Read-only owner-M1 preflight for the unified autonomous CODE Draft.

This never stages, admits, approves, launches, restarts or installs anything.
A passing probe means only that this exact PR source was inspected on the
owner's M1. It does not imply active MCP tool exposure or production cutover.
"""
from __future__ import annotations

import ast
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILES = (
    "src/ai_foundation/development_requests.py",
    "src/ai_foundation/guard.py",
    "src/ai_foundation/human_operations.py",
    "scripts/m1_development_scope_delegation.py",
    "scripts/local9b_autodev_worker.py",
    "scripts/m1_runtime_status_probe.py",
    "scripts/m1_github_owner_local9b_release.py",
    "tests/test_m1_github_owner_local9b_release.py",
    "src/ai_foundation/long_term_health.py",
    "scripts/local9b_failure_candidates.py",
    "scripts/local9b_task_recipe.py",
    "tests/test_local9b_task_selection.py",
    "tests/test_human_operations.py",
    "tests/test_m1_development_scope_delegation.py",
    # Exact changed CODE execution/readback and replaced notification behavior.
    "src/ai_foundation/development_host.py",
    "tests/test_mcp_direct_local_development.py",
    "src/ai_foundation/notification_boundary.py",
    "tests/test_notification_boundary.py",
    "src/ai_foundation/mcp_host.py",
    "src/ai_foundation/operator_mcp_tools.py",
    "tests/test_operator_mcp_tools.py",
    "tests/test_foundation_mcp_stdio.py",
    "scripts/foundation_mcp_stdio.py",
    "scripts/m1_owner_delegated_mcp_stdio.py",
    "scripts/m1_guarded_tunnel_refresh.py",
    "scripts/m1_operator_status_probe.py",
    "scripts/m1_development_ticket_factory.py",
    # Current self-development CODE manifest's actual owner read/write paths.
    # Byte-compare staged source only; never read private ticket contents.
    "scripts/m1_direct_development.py",
    "scripts/m1_reviewed_strata_ticket.py",
    "scripts/m1_strata_owner_ticket_admission.py",
    "scripts/m1_strata_ticket_overview.py",
    "src/ai_foundation/operator_server.py",
    "src/ai_foundation/preflight.py",
    "src/ai_foundation/operator.py",
    "tests/test_preflight.py",
    "src/ai_foundation/klm_status.py",
    "tests/test_klm_status.py",
    "tests/test_operator_server.py",
    "src/ai_foundation/human_renderer.py",
    "tests/test_human_renderer.py",
    "tests/test_mcp_owner_grants.py",
    "scripts/m1_owner_grant_host_canary.py",
    "scripts/m1_owner_grant_stdio_e2e.py",
    "tests/test_operator_reconcile_restart_http.py",
    "scripts/m1_development_owner_review.py",
    "scripts/m1_development_review_candidate.py",
    "tests/test_m1_development_owner_review.py",
    "tests/test_m1_development_review_candidate.py",
    "tests/test_m1_operator_release_cli.py",
    "src/ai_foundation/development_review_renderer.py",
    "src/ai_foundation/klm_review_renderer.py",
    # The installed mobile owner gateway is a separate runtime. Verify the
    # exact release CLI and Tailnet ingress bytes at immutable staging too.
    "scripts/m1_operator_release_cli.py",
    "scripts/m1_operator_release_canon.py",
    "tests/test_m1_operator_release_canon.py",
    "scripts/m1_mobile_owner_release.py",
    "scripts/m1_mobile_gateway_bootstrap.py",
    "scripts/m1_mobile_gateway_successor.py",
    "scripts/m1_owner_production_recovery.py",
    "scripts/m1_selfdev_release_preflight.py",
    "scripts/remote_gateway.py",
    "tests/test_remote_gateway.py",
    "scripts/run_remote_gateway.py",
    "scripts/operator_server.py",
    "tests/test_operator_server_installed_import_root.py",
    "src/ai_foundation/gateway_csrf.py",
    # The complete new self-development hot path and its few focused tests.
    "tests/test_development_requests.py",
    "tests/test_m1_direct_development_factory.py",
    "tests/test_operator_development_state.py",
    "tests/test_operator_klm_owner_review.py",
    # The exact owner authorization gate's regression suite.
    "tests/test_m1_guarded_tunnel_refresh.py",
)
PR_NUMBER = 1419
PR_BRANCH = "feat/owner-klm-review-code-withdrawal-20261117"
FOLLOWUP_PR_NUMBER = 1502
FOLLOWUP_BRANCH = "fix/owner-mobile-gateway-actions-20261119"
# The reviewed/applied source release is frozen. A follow-up is accepted only
# while based on that exact predecessor, never a moving or unrelated branch.
FOLLOWUP_BASE_SHA = "685e6880e02f906792a28c492041f2d15b84f8d7"
MOBILE_PR_NUMBER = 1503
MOBILE_BRANCH = "feat/mobile-owner-release-no-terminal-20261119"
# Do not mutate the existing prepared #1502 release. Source-only CI for this
# successor is permitted only when its base is the exact frozen #1502 commit.
MOBILE_BASE_SHA = "425e6d4a0dfe80eb50b9d18554286682fba57c3f"
CODE_CAPACITY_PR_NUMBER = 1505
CODE_CAPACITY_BRANCH = "fix/owner-code-manifest-capacity-20261120"
# G8 verified by the owner's existing Guard, but not an authorization for
# this follow-up. This gate only permits read-only immutable source staging.
CODE_CAPACITY_BASE_SHA = "739a823c57ed6dbc1ca48e30c01ab7fbe2918d9d"
POST_CUTOVER_PR_NUMBER = 1506
POST_CUTOVER_BRANCH = "fix/postcutover-gateway-upstream-readback-20261120"
# Exact stacked source parent only, not a Guard approval or install permit.
POST_CUTOVER_BASE_SHA = "358885c1793911f467d1adbb963922d9622bfd45"
P0_OPERATOR_PR_NUMBER = 1507
P0_OPERATOR_BRANCH = "fix/p0-mcp-operator-status-failclosed-20261121"
# The existing physical Gateway remains at this owner-approved exact source.
# Merely stage and read this Operator successor; no Guard or launchd effects.
P0_OPERATOR_BASE_SHA = "15815926d09ef15d9b804603bfb99ae7c3f24c6e"
OWNER_REVIEW_PR_NUMBER = 1509
OWNER_REVIEW_BRANCH = "fix/p0-review-source-unification-20261121"
OWNER_REVIEW_BASE_SHA = "92e9a7e643cfd028047cccb70d3f3b338b8cd79d"
RUNTIME_IMPORT_PR_NUMBER = 1510
RUNTIME_IMPORT_BRANCH = "fix/p0-operator-review-runtime-import-root-20261121"
RUNTIME_IMPORT_BASE_SHA = "1b231058ee6d15c97419ed63140ef8a125c9d536"
SELFDEV_WHOLE_PR_NUMBER = 1514
SELFDEV_WHOLE_BRANCH = "fix/p0-selfdev-fastlane-single-acceptance-20261121"
SELFDEV_WHOLE_BASE_SHA = "d4ef51c2dbbe957eb5ed55b6897bd4a43d29110f"
REPO = "quest7070-dev/AI-Foundation"
OWNER = "quest7070-debug"


def scoped_event(event, *, env, current_sha):
    """Accept only exact trusted owner PR+frozen parent for read-only staging.

    Adding the #1506 post-cutover readback fix does not authorize any Guard
    request, service mutation, runner promotion or Android POST claim.
    """
    pr = event.get("pull_request") if type(event) is dict else None
    if type(pr) is not dict:
        return False
    head = pr.get("head") if type(pr.get("head")) is dict else {}
    base = pr.get("base") if type(pr.get("base")) is dict else {}
    user = pr.get("user") if type(pr.get("user")) is dict else {}
    repo = head.get("repo") if type(head.get("repo")) is dict else {}
    number = pr.get("number")
    owner_scope = (
        (number == PR_NUMBER and head.get("ref") == PR_BRANCH)
        or (number == FOLLOWUP_PR_NUMBER
            and head.get("ref") == FOLLOWUP_BRANCH
            and base.get("ref") == PR_BRANCH
            and base.get("sha") == FOLLOWUP_BASE_SHA)
        or (number == MOBILE_PR_NUMBER
            and head.get("ref") == MOBILE_BRANCH
            and base.get("ref") == FOLLOWUP_BRANCH
            and base.get("sha") == MOBILE_BASE_SHA)
        or (number == CODE_CAPACITY_PR_NUMBER
            and head.get("ref") == CODE_CAPACITY_BRANCH
            and base.get("ref") == MOBILE_BRANCH
            and base.get("sha") == CODE_CAPACITY_BASE_SHA)
        or (number == POST_CUTOVER_PR_NUMBER
            and head.get("ref") == POST_CUTOVER_BRANCH
            and base.get("ref") == CODE_CAPACITY_BRANCH
            and base.get("sha") == POST_CUTOVER_BASE_SHA)
        or (number == P0_OPERATOR_PR_NUMBER
            and head.get("ref") == P0_OPERATOR_BRANCH
            and base.get("ref") == POST_CUTOVER_BRANCH
            and base.get("sha") == P0_OPERATOR_BASE_SHA)
        or (number == OWNER_REVIEW_PR_NUMBER
            and head.get("ref") == OWNER_REVIEW_BRANCH
            and base.get("ref") == P0_OPERATOR_BRANCH
            and base.get("sha") == OWNER_REVIEW_BASE_SHA)
        or (number == RUNTIME_IMPORT_PR_NUMBER
            and head.get("ref") == RUNTIME_IMPORT_BRANCH
            and base.get("ref") == OWNER_REVIEW_BRANCH
            and base.get("sha") == RUNTIME_IMPORT_BASE_SHA)
        or (number == SELFDEV_WHOLE_PR_NUMBER
            and head.get("ref") == SELFDEV_WHOLE_BRANCH
            and base.get("ref") == RUNTIME_IMPORT_BRANCH
            and base.get("sha") == SELFDEV_WHOLE_BASE_SHA)
    )
    return (env.get("GITHUB_EVENT_NAME") == "pull_request"
            and env.get("GITHUB_REPOSITORY") == REPO
            and event.get("action") in ("synchronize", "opened")
            and type(number) is int
            and owner_scope
            and user.get("login") == OWNER
            and repo.get("full_name") == REPO
            and type(current_sha) is str
            and re.fullmatch("[a-f0-9]{40}", current_sha) is not None
            and current_sha == head.get("sha"))


def source_probe(candidate, owner_checkout, trusted_bytes):
    """Compare only publicly named source bytes; owner checkout != live code."""
    candidate, owner_checkout = Path(candidate), Path(owner_checkout)
    drift = []
    for relative in SOURCE_FILES:
        current = trusted_bytes(candidate / relative)
        ast.parse(current, filename=relative)
        try:
            installed_reference = trusted_bytes(owner_checkout / relative)
        except (OSError, ValueError, PermissionError):
            drift.append(relative)
        else:
            if sha256(installed_reference).digest() != sha256(current).digest():
                drift.append(relative)
    return {"candidate_python_files_checked": len(SOURCE_FILES),
            "owner_checkout_different_modules": len(drift),
            "owner_checkout_source_match": not drift}


def inspect(*, event, env, current_sha, system, machine, uid, euid,
            candidate, owner_checkout, trusted_bytes, tunnel_readiness):
    if not scoped_event(event, env=env, current_sha=current_sha):
        return {"status": "BLOCKED", "reason": "EXACT_OWNER_PR_HEAD_REQUIRED",
                "model_calls": 0, "service_mutations": 0}
    if system != "Darwin" or machine not in ("arm64", "aarch64") or uid != euid or uid != 501:
        return {"status": "BLOCKED", "reason": "M1_OWNER_REQUIRED",
                "model_calls": 0, "service_mutations": 0}
    try:
        comparison = source_probe(candidate, owner_checkout, trusted_bytes)
        tunnel = tunnel_readiness(checkout=candidate)
        reason = tunnel.get("reason")
        if reason not in {"NONE", "OWNER_SOURCE_INSTALL_REQUIRED",
                          "TUNNEL_CLIENT_NOT_INSTALLED_OR_UNTRUSTED",
                          "PINNED_PYTHON_NOT_INSTALLED", "OWNER_M1_REQUIRED"}:
            reason = "TUNNEL_PROBE_UNVERIFIED"
    except (OSError, ValueError, SyntaxError, TypeError, PermissionError):
        return {"status": "BLOCKED", "reason": "OWNER_SOURCE_PREFLIGHT_UNVERIFIED",
                "model_calls": 0, "service_mutations": 0}
    return {"status": "READONLY_SOURCE_OBSERVED",
            **comparison,
            "existing_tunnel_readiness": "READY" if reason == "NONE" else "BLOCKED",
            "existing_tunnel_reason": reason,
            "production_installed": False,
            "remote_mcp_cycle_verified": False,
            "owner_review_created": False,
            "model_calls": 0, "service_mutations": 0}


def main():
    from m1_foundation_tunnel import _trusted_bytes
    from m1_guarded_tunnel import readiness
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        sha = subprocess.run(
            ["/usr/bin/git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True, timeout=5).stdout.strip()
        observed = inspect(
            event=event, env=os.environ, current_sha=sha,
            system=platform.system(), machine=platform.machine(),
            uid=os.getuid(), euid=os.geteuid(),
            candidate=ROOT, owner_checkout=Path.home() / "Develop/AI-Foundation",
            trusted_bytes=_trusted_bytes, tunnel_readiness=readiness)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        observed = {"status": "BLOCKED", "reason": "OWNER_PROBE_UNVERIFIED",
                    "model_calls": 0, "service_mutations": 0}
    print(json.dumps(observed, sort_keys=True))
    return 0 if observed["status"] == "READONLY_SOURCE_OBSERVED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
