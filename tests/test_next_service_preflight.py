"""Zero-cost next-service preflight; never imports or executes provider CLIs."""
from dataclasses import replace

from ai_foundation.next_service_preflight import (
    OpenCodeReviewEvidence, JulesReviewEvidence,
    opencode_candidate_config, opencode_readiness, jules_readiness,
    next_services_status,
)


def open_evidence(**updates):
    obj = OpenCodeReviewEvidence(
        model="opencode/hy4-flash-free",
        observed_at=1000.0,
        official_model_revision_sha256="a" * 64,
        free_model_priced_zero=True,
        actual_account_free=True,
        no_payment_method=True,
        no_prepaid_balance=True,
        auto_recharge_off=True,
        go_extra_usage_off=True,
        paid_fallback_off=True,
        background_model_free_only=True,
        isolated_binary_verified=True,
        private_server_verified=True,
        no_shared_auth_or_project=True,
        native_sandbox_verified=True,
        exact_model_network_enforcement_verified=True,
    )
    return replace(obj, **updates)


def jules_evidence(**updates):
    obj = JulesReviewEvidence(
        observed_at=1000.0,
        actual_free_account=True,
        available_daily_tasks=2,
        active_sessions=0,
        paid_subscription_absent=True,
        exact_repository_scope_verified=True,
        public_only_source_reviewed=True,
        no_auto_create_or_merge_pr=True,
        draft_pr_independent_readback_ready=True,
        local_final_review_ready=True,
    )
    return replace(obj, **updates)


def test_no_evidence_never_creates_cost_approval_or_live_execution():
    services = next_services_status()
    assert len(services) == 1
    (a,) = services
    assert a["service"] == "opencode-console-free"
    assert a["stage"] == "HOLD_UNVERIFIED"
    assert a["blockers"] == ("TRUSTED_ACCOUNT_EVIDENCE_REQUIRED",)
    for report in services:
        assert report["execution_authorized"] is False
        assert report["billing_receipt_issued"] is False
        assert report["local_fallback"] == "LOCAL_HARNESS_9B"


def test_locked_config_is_v2_gate_only_not_open_console_payment_permission():
    diagnostic = opencode_candidate_config()
    assert diagnostic["execution_authorized"] is False
    assert diagnostic["schema"] == "OPENCODE_V2_GATE_CONFIGURATION_REQUIRES_PORT"
    assert diagnostic["candidate_model"] == "opencode/hy4-flash-free"
    cfg = opencode_candidate_config(41555)
    assert cfg["model"] == "foundation-public-gate/hy4-flash-free"
    assert list(cfg["providers"]) == ["foundation-public-gate"]
    assert cfg["permissions"] == [{"action": "*", "resource": "*", "effect": "deny"}]
    assert cfg["policies"] == [
        {"action": "provider.use", "resource": "*", "effect": "deny"},
        {"action": "provider.use", "resource": "foundation-public-gate", "effect": "allow"},
    ]
    assert cfg["compaction"]["auto"] is False
    assert cfg["warming"] is False
    assert cfg["plugins"] == [] and cfg["mcp"] == {}
    assert cfg["providers"]["foundation-public-gate"]["package"] == "@opencode/ai/providers/openai-compatible"
    assert cfg["providers"]["foundation-public-gate"]["settings"]["baseURL"] == (
        "http://127.0.0.1:41555/v1")
    assert "apiKey" not in str(cfg)
    assert opencode_readiness()["execution_authorized"] is False

def test_each_opencode_cost_or_privacy_gap_blocks_candidate_review():
    gates = (
        ("free_model_priced_zero", "MODEL_MUST_BE_FREE_NOW"),
        ("actual_account_free", "ACCOUNT_BILLING_REVIEW_REQUIRED"),
        ("no_payment_method", "PAYMENT_METHOD_PRESENT"),
        ("no_prepaid_balance", "PREPAID_CREDIT_SPEND_RISK"),
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
    for field, expected in gates:
        state = opencode_readiness(open_evidence(**{field: False}), now=1200)
        assert expected in state["blockers"]
        assert state["stage"] == "HOLD_UNVERIFIED"
        assert state["execution_authorized"] is False


def test_opencode_price_revision_expiry_and_paid_model_are_denied():
    for ev, reason in (
        (open_evidence(model="opencode/gpt-6.1-sol"), "PINNED_FREE_MODEL_REQUIRED"),
        (open_evidence(model="opencode/auto"), "PINNED_FREE_MODEL_REQUIRED"),
        (open_evidence(model="opencode/glm-5.3-flash"), "PINNED_FREE_MODEL_REQUIRED"),
        (open_evidence(observed_at=-100000.0), "OFFICIAL_FREE_MODEL_RECHECK_REQUIRED"),
        (open_evidence(observed_at=1400.0), "OFFICIAL_FREE_MODEL_RECHECK_REQUIRED"),
        (open_evidence(official_model_revision_sha256="unknown"),
         "OFFICIAL_MODEL_REVISION_HASH_REQUIRED"),
    ):
        assert reason in opencode_readiness(ev, now=1200)["blockers"]


def test_verified_zero_dollar_workspace_budget_replaces_payment_and_credit_absence():
    # Console's server-enforced all-spend budget blocks paid requests at $0.
    # Free models do not count. This is a trusted host observation, not
    # something a model or Issue may assert to obtain activation.
    with_budget = open_evidence(
        no_payment_method=False, no_prepaid_balance=False,
        workspace_zero_budget_verified=True)
    reviewed = opencode_readiness(with_budget, now=1200)
    assert reviewed["stage"] == "PREPARED_FOR_HOST_REVIEW"
    assert reviewed["blockers"] == ()
    assert reviewed["execution_authorized"] is False
    assert reviewed["billing_receipt_issued"] is False

    without_budget = opencode_readiness(
        open_evidence(no_payment_method=False,
                      no_prepaid_balance=False,
                      workspace_zero_budget_verified=False),
        now=1200)
    assert without_budget["stage"] == "HOLD_UNVERIFIED"
    assert {"PAYMENT_METHOD_PRESENT", "PREPAID_CREDIT_SPEND_RISK"}.issubset(
        set(without_budget["blockers"]))
    # Even the server-side budget cannot replace auto-recharge-off.
    unsafe = opencode_readiness(
        open_evidence(no_payment_method=False,
                      no_prepaid_balance=False,
                      workspace_zero_budget_verified=True,
                      auto_recharge_off=False),
        now=1200)
    assert "AUTO_RECHARGE_MUST_BE_OFF" in unsafe["blockers"]


def test_all_positive_preflight_still_never_executes_opencode():
    state = opencode_readiness(open_evidence(), now=1200)
    assert state["stage"] == "PREPARED_FOR_HOST_REVIEW"
    assert state["blockers"] == ()
    assert state["execution_authorized"] is False
    assert state["billing_receipt_issued"] is False
    assert state["paid_fallback_enabled"] is False


def test_jules_quota_plan_and_concurrency_all_gate_remote_acceptance():
    cases = (
        (jules_evidence(actual_free_account=False),
         "JULES_FREE_PLAN_NOT_VERIFIED"),
        (jules_evidence(available_daily_tasks=0),
         "FREE_DAILY_QUOTA_NOT_CONFIRMED"),
        (jules_evidence(available_daily_tasks=16),
         "FREE_DAILY_QUOTA_NOT_CONFIRMED"),
        (jules_evidence(active_sessions=3),
         "FREE_CONCURRENCY_UNAVAILABLE"),
        (jules_evidence(active_sessions=True),
         "FREE_CONCURRENCY_UNAVAILABLE"),
        (jules_evidence(paid_subscription_absent=False),
         "PAID_JULES_SUBSCRIPTION_RISK"),
        (jules_evidence(exact_repository_scope_verified=False),
         "REPOSITORY_SCOPE_UNVERIFIED"),
        (jules_evidence(public_only_source_reviewed=False),
         "REMOTE_PRIVATE_DATA_RISK"),
        (jules_evidence(no_auto_create_or_merge_pr=False),
         "UNCONTROLLED_PR_PUBLICATION_RISK"),
        (jules_evidence(draft_pr_independent_readback_ready=False),
         "DRAFT_PR_READBACK_REQUIRED"),
        (jules_evidence(local_final_review_ready=False),
         "LOCAL_FINAL_REVIEW_REQUIRED"),
        (jules_evidence(observed_at=-100000.0),
         "FREE_PLAN_AND_LIMITS_RECHECK_REQUIRED"),
    )
    for ev, reason in cases:
        state = jules_readiness(ev, now=1200)
        assert reason in state["blockers"]
        assert state["stage"] == "RETIRED"
        assert state["execution_authorized"] is False
        assert state["auto_pr_enabled"] is False


def test_jules_positive_host_review_is_still_not_session_launch():
    state = jules_readiness(jules_evidence(), now=1200)
    assert state["stage"] == "RETIRED"
    assert "JULES_RETIRED_NO_DISPATCH" in state["blockers"]
    assert state["execution_authorized"] is False
    assert state["billing_receipt_issued"] is False
    assert state["local_fallback"] == "LOCAL_HARNESS_9B"


def test_jules_shutdown_is_excluded_from_new_service_onboarding():
    """Official Jules turndown: sessions end 2026-11-11, shutdown 2026-12-31."""
    assert all(item["service"] != "jules" for item in next_services_status())


def test_ranked_free_candidate_requires_same_existing_cost_and_identity_gates():
    ranked = "opencode/deepseek-v4.1-flash-free"
    accepted = opencode_readiness(open_evidence(model=ranked), now=1200)
    assert accepted["candidate_model"] == ranked
    assert accepted["stage"] == "PREPARED_FOR_HOST_REVIEW"
    assert accepted["execution_authorized"] is False
    denied = opencode_readiness(
        open_evidence(model=ranked, free_model_priced_zero=False), now=1200)
    assert "MODEL_MUST_BE_FREE_NOW" in denied["blockers"]
    assert denied["execution_authorized"] is False
