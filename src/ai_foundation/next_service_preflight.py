"""Non-executable Free coding-service preflight under Foundation Harness.

OpenCode has paid models in the same provider as temporary free ones, and
may make separate helper calls. A provider allowlist or local config cannot
prove zero spend. This module prepares a *denied-by-default* config review,
never starts the CLI, connects an account or grants Foundation execution.

Jules is a remote GitHub development job and must never be substituted for
a proposal-only HTTP model adapter. Its Free account/quota and independent
Draft PR readback are separate acceptance contracts.

All reports are advisory; values from research/Issue/model output are not
evidence to activate any runtime. Only the trusted host may assemble attestations.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import time

SERVICE_OPEN_CODE = "opencode-console-free"
SERVICE_JULES = "jules"
# Official Console catalog on 2026-11-09. Temporary offers must be
# independently rechecked before each account acceptance.
_OPEN_CODE_FREE_PATTERN = re.compile(r"opencode/[a-z0-9][a-z0-9.-]{1,127}-free\Z")


def reviewable_free_model(model):
    # Only a syntactic candidate. The trusted owner's fresh official price,
    # account, budget and exact-model egress evidence MUST still be verified.
    return type(model) is str and _OPEN_CODE_FREE_PATTERN.fullmatch(model) is not None
_OPEN_CODE_SELECTION = "opencode/hy4-flash-free"
_OFFICIAL_RECHECK_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class OpenCodeReviewEvidence:
    """Trusted-host observations, NOT a provider billing receipt."""
    model: str
    observed_at: float
    official_model_revision_sha256: str
    free_model_priced_zero: bool
    actual_account_free: bool
    no_payment_method: bool
    no_prepaid_balance: bool
    auto_recharge_off: bool
    go_extra_usage_off: bool
    paid_fallback_off: bool
    background_model_free_only: bool
    isolated_binary_verified: bool
    private_server_verified: bool
    no_shared_auth_or_project: bool
    native_sandbox_verified: bool
    exact_model_network_enforcement_verified: bool
    # Verified workspace-wide ALL-SPEND $0 budget: paid requests blocked server-side.
    # Free models do not count toward Console budgets (official 2026-11-10 docs).
    workspace_zero_budget_verified: bool = False


@dataclass(frozen=True)
class JulesReviewEvidence:
    """Remote task/PR acceptance observation, NOT dispatch approval."""
    observed_at: float
    actual_free_account: bool
    available_daily_tasks: int
    active_sessions: int
    paid_subscription_absent: bool
    exact_repository_scope_verified: bool
    public_only_source_reviewed: bool
    no_auto_create_or_merge_pr: bool
    draft_pr_independent_readback_ready: bool
    local_final_review_ready: bool


def opencode_candidate_config(gateway_port=None):
    """OpenCode V2 review-only config, pinned to the loopback model gate.

    Passing a host-selected ephemeral port returns an actual V2 config for
    a *synthetic* model response, not a CLI authorization. Old provider-level
    allow-only configs are unsafe because OpenCode Console exposes paid
    models under the same provider and V1/V2 permissions differ.
    """
    if gateway_port is None:
        return {
            "schema": "OPENCODE_V2_GATE_CONFIGURATION_REQUIRES_PORT",
            "execution_authorized": False,
            "candidate_model": _OPEN_CODE_SELECTION,
        }
    from .opencode_model_gate import opencode_v2_isolated_config
    return opencode_v2_isolated_config(gateway_port)

def _fresh(timestamp, now):
    return (type(timestamp) in (float, int)
            and not isinstance(timestamp, bool)
            and 0 <= now - timestamp <= _OFFICIAL_RECHECK_SECONDS)


def _fingerprint(text):
    return type(text) is str and re.fullmatch(r"[a-f0-9]{64}", text) is not None


def opencode_readiness(evidence=None, *, now=None):
    """Read-only: status NEVER means a runnable coding CLI was admitted."""
    if now is None:
        now = time.time()
    blockers = []
    if not isinstance(evidence, OpenCodeReviewEvidence):
        blockers.append("TRUSTED_ACCOUNT_EVIDENCE_REQUIRED")
    else:
        if not reviewable_free_model(evidence.model):
            blockers.append("PINNED_FREE_MODEL_REQUIRED")
        if not _fresh(evidence.observed_at, now):
            blockers.append("OFFICIAL_FREE_MODEL_RECHECK_REQUIRED")
        if not _fingerprint(evidence.official_model_revision_sha256):
            blockers.append("OFFICIAL_MODEL_REVISION_HASH_REQUIRED")
        gates = (
            ("free_model_priced_zero", "MODEL_MUST_BE_FREE_NOW"),
            ("actual_account_free", "ACCOUNT_BILLING_REVIEW_REQUIRED"),
            ("auto_recharge_off", "AUTO_RECHARGE_MUST_BE_OFF"),
            ("go_extra_usage_off", "GO_EXTRA_USAGE_MUST_BE_OFF"),
            ("paid_fallback_off", "PAID_MODEL_FALLBACK_NOT_EXCLUDED"),
            ("background_model_free_only", "PAID_BACKGROUND_MODEL_RISK"),
            ("isolated_binary_verified", "PINNED_CLI_BINARY_REQUIRED"),
            ("private_server_verified", "SHARED_SERVER_NOT_EXCLUDED"),
            ("no_shared_auth_or_project", "SHARED_CREDENTIAL_OR_PROJECT"),
            ("native_sandbox_verified", "NATIVE_SANDBOX_NOT_VERIFIED"),
            ("exact_model_network_enforcement_verified",
             "MODEL_LEVEL_EGRESS_GATE_NOT_VERIFIED"),
        )
        blockers += [reason for field, reason in gates
                     if getattr(evidence, field) is not True]
        # The zero-dollar *all-spend* budget is an upstream-enforced hard
        # stop, not a soft quota or account hint. It can replace the overly
        # strict "no payment method and no prepaid credits" prerequisite.
        # It cannot replace auto-recharge-off or exact-model authorization.
        if evidence.workspace_zero_budget_verified is not True:
            if evidence.no_payment_method is not True:
                blockers.append("PAYMENT_METHOD_PRESENT")
            if evidence.no_prepaid_balance is not True:
                blockers.append("PREPAID_CREDIT_SPEND_RISK")
    return {
        "service": SERVICE_OPEN_CODE,
        "integration_kind": "AGENT_WITH_GATEWAY",
        "candidate_model": (evidence.model if isinstance(evidence, OpenCodeReviewEvidence)
                             and reviewable_free_model(evidence.model) else _OPEN_CODE_SELECTION),
        "stage": "PREPARED_FOR_HOST_REVIEW" if not blockers
                 else "HOLD_UNVERIFIED",
        "blockers": tuple(blockers),
        "execution_authorized": False,
        "billing_receipt_issued": False,
        "paid_fallback_enabled": False,
        "local_fallback": "LOCAL_HARNESS_9B",
    }


def jules_readiness(evidence=None, *, now=None):
    if now is None:
        now = time.time()
    # Official service turndown (2026-10-29): no new Jules integration.
    blockers = ["JULES_RETIRED_NO_DISPATCH"]
    if not isinstance(evidence, JulesReviewEvidence):
        blockers.append("TRUSTED_JULES_ACCOUNT_EVIDENCE_REQUIRED")
    else:
        if not _fresh(evidence.observed_at, now):
            blockers.append("FREE_PLAN_AND_LIMITS_RECHECK_REQUIRED")
        if evidence.actual_free_account is not True:
            blockers.append("JULES_FREE_PLAN_NOT_VERIFIED")
        if type(evidence.available_daily_tasks) is not int or not (
                1 <= evidence.available_daily_tasks <= 15):
            blockers.append("FREE_DAILY_QUOTA_NOT_CONFIRMED")
        if type(evidence.active_sessions) is not int or not (
                0 <= evidence.active_sessions < 3):
            blockers.append("FREE_CONCURRENCY_UNAVAILABLE")
        gates = (
            ("paid_subscription_absent", "PAID_JULES_SUBSCRIPTION_RISK"),
            ("exact_repository_scope_verified", "REPOSITORY_SCOPE_UNVERIFIED"),
            ("public_only_source_reviewed", "REMOTE_PRIVATE_DATA_RISK"),
            ("no_auto_create_or_merge_pr", "UNCONTROLLED_PR_PUBLICATION_RISK"),
            ("draft_pr_independent_readback_ready",
             "DRAFT_PR_READBACK_REQUIRED"),
            ("local_final_review_ready", "LOCAL_FINAL_REVIEW_REQUIRED"),
        )
        blockers += [reason for field, reason in gates
                     if getattr(evidence, field) is not True]
    return {
        "service": SERVICE_JULES,
        "integration_kind": "CLOUD_DEVELOPMENT_SERVICE",
        "stage": "RETIRED",
        "blockers": tuple(blockers),
        "execution_authorized": False,
        "billing_receipt_issued": False,
        "auto_pr_enabled": False,
        "local_fallback": "LOCAL_HARNESS_9B",
    }


def next_services_status():
    """Static state for Operator readback; never routes or calls either service."""
    # Jules officially retires on 2026-12-31 and is no longer a new
    # development-service candidate (2026-10-29 official turndown).
    return (opencode_readiness(),)
