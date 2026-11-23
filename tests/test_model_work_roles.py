"""Focused, no-network evidence for local/external responsibility separation."""
from dataclasses import dataclass

import pytest

from ai_foundation.core import CanonContract, Decision, TaskPlan
from ai_foundation.compute_routing import ComputeRouter
from ai_foundation.inference_service import GuardedInferenceService
from ai_foundation.model_work_roles import (
    ModelWorkContract, ModelWorkRole, evaluate_model_work, public_payload_hash,
)


def reviewed(text, role=ModelWorkRole.FOUNDATION_DEVELOPMENT, **changes):
    values = {
        "role": role, "data_class": "PUBLIC_NONSECRET",
        "public_source": "fixture:public-error-001",
        "reviewed_sha256": public_payload_hash(text),
        "host_public_reviewed": True, "external_transfer_allowed": True,
        "local_data_reviewed": True, "local_data_verdict": "PUBLIC_NONSECRET",
    }
    values.update(changes)
    return ModelWorkContract(**values)


def test_private_owner_roles_are_local_only():
    for role in (
        ModelWorkRole.LOCAL_DEVELOPMENT, ModelWorkRole.HUMAN_MODEL,
        ModelWorkRole.SECRET_MANAGEMENT, ModelWorkRole.DATA_SENSITIVITY_REVIEW,
        ModelWorkRole.FINAL_CODE_REVIEW, ModelWorkRole.ERROR_RECOVERY,
        ModelWorkRole.PRIVATE_KLM, ModelWorkRole.M1_ACCEPTANCE,
        ModelWorkRole.PRIVATE_CONTEXT,
    ):
        decision = evaluate_model_work(ModelWorkContract(role), text="private work")
        assert decision.allowed and decision.local_required and not decision.external_preferred


def test_public_helpers_need_exact_host_reviewed_bounded_payload():
    prompt = "Public fixture: explain why assert 1 == 2 fails."
    good = evaluate_model_work(reviewed(prompt), text=prompt)
    assert good.allowed and good.external_preferred and not good.local_required
    for change in (
        {"host_public_reviewed": False},
        {"local_data_reviewed": False},
        {"local_data_verdict": "UNKNOWN"},
        {"local_data_verdict": "SENSITIVE"},
        {"external_transfer_allowed": False},
        {"data_class": "PRIVATE"},
        {"reviewed_sha256": "0" * 64},
        {"public_source": ""},
    ):
        result = evaluate_model_work(reviewed(prompt, **change), text=prompt)
        assert result.allowed and result.local_required and not result.external_preferred
    assert evaluate_model_work(reviewed(prompt), text=prompt + " changed").local_required
    assert evaluate_model_work(reviewed(prompt), text=prompt, privacy_text="different").local_required
    assert evaluate_model_work(reviewed(prompt), text="x" * 4097).local_required
    assert not evaluate_model_work("PUBLIC_ERROR_TRIAGE", text=prompt).allowed


def test_public_helper_cannot_send_obvious_secrets_or_private_paths():
    for text in (
        "gsk_" + "A" * 25,
        "password=hello",
        "path /Users/person/private",
        "HumanModel evidence",
        "LOCAL_ONLY original",
    ):
        assert evaluate_model_work(reviewed(text), text=text).reason == "LOCAL_FALLBACK_PRIVATE_CONTEXT"


@dataclass
class Candidate:
    binding: str
    health: str = "ONLINE"
    capabilities: tuple = ("CHAT",)
    model: str = "local-9b"
    slot: str = "local-general"


class Local:
    def candidates(self):
        return (Candidate("local:9b"),)


class Settings:
    def __init__(self, cloud):
        self.cloud = cloud
        self.seen = None

    def choose_route(self, function, *, exclude, phase, local_candidates):
        self.seen = set(exclude)
        if self.cloud and self.cloud not in exclude:
            return self.cloud
        return next((c.binding for c in local_candidates if c.binding not in exclude), None)


def test_external_first_preserves_local_9b_fallback_when_cloud_unavailable():
    settings = Settings(None)
    router = ComputeRouter(settings, Local())
    assert router.choose("CHAT").kind == "LOCAL"
    outcome = router.choose("CHAT", external_preferred=True)
    assert outcome.binding == "local:9b" and outcome.kind == "LOCAL"
    assert "local:9b" in settings.seen
    assert router.choose("CHAT", local_required=True, external_preferred=True).binding == "local:9b"


def test_local_only_still_wins_over_available_free_cloud():
    router = ComputeRouter(Settings("llm:groq:accepted"), Local())
    assert router.choose("CHAT", local_required=True).binding == "local:9b"
    assert router.choose("CHAT", external_preferred=True).binding == "llm:groq:accepted"


class AllowGuard:
    def __init__(self, decision=Decision.ALLOW):
        self.decision = decision
    def preflight(self, plan, canon):
        return self.decision


class RecordingRouter:
    def __init__(self):
        self.kwargs = []
    def choose(self, function, **kw):
        self.kwargs.append(kw)
        from ai_foundation.compute_routing import ComputeRoute
        return ComputeRoute(None, None)


def test_inference_gate_holds_responsibility_within_existing_guard():
    router = RecordingRouter()
    service = GuardedInferenceService(AllowGuard(), router, local_execution=object())
    plan = TaskPlan("role-1", "compute", "llm", text="private", canon_revision="v1")
    canon = CanonContract("test", "v1")
    result = service.run(plan, canon, role_contract=ModelWorkContract(ModelWorkRole.PRIVATE_KLM))
    assert result.status == "NO_ELIGIBLE_COMPUTE"
    assert router.kwargs[-1]["local_required"] is True
    assert "cloud_only" not in router.kwargs[-1]

    prompt = "Public minimal fixture."
    public_plan = TaskPlan("role-2", "compute", "llm", text=prompt, canon_revision="v1")
    result = service.run(public_plan, canon, role_contract=reviewed(prompt))
    assert result.status == "NO_ELIGIBLE_COMPUTE"
    assert router.kwargs[-1]["external_preferred"] is True
    assert router.kwargs[-1]["strata_first"] is True

    result = service.run(public_plan, canon, role_contract=reviewed(prompt, host_public_reviewed=False))
    assert result.status == "NO_ELIGIBLE_COMPUTE"
    assert router.kwargs[-1]["local_required"] is True
    assert "external_preferred" not in router.kwargs[-1]

    protected = GuardedInferenceService(AllowGuard(Decision.LOCAL_ONLY), router, local_execution=object())
    result = protected.run(public_plan, canon, role_contract=reviewed(prompt))
    assert result.status == "NO_ELIGIBLE_COMPUTE"
    assert router.kwargs[-1]["local_required"] is True
    assert "external_preferred" not in router.kwargs[-1]

def test_foundation_development_external_first_only_when_public_verified():
    text = "Write tests for a public pure function that adds two integers."
    external = evaluate_model_work(reviewed(text, ModelWorkRole.FOUNDATION_DEVELOPMENT), text=text)
    assert external.allowed and external.external_preferred and not external.local_required
    default = evaluate_model_work(ModelWorkContract(ModelWorkRole.FOUNDATION_DEVELOPMENT), text=text)
    assert default.allowed and default.local_required and not default.external_preferred
    human = evaluate_model_work(reviewed(text, ModelWorkRole.HUMAN_MODEL), text=text)
    assert human.allowed and human.local_required and not human.external_preferred


def test_local_privacy_review_is_mandatory_and_not_a_model_self_grant():
    sample="Function increment(x) returns x + 1. Please add unit tests."
    without_review = reviewed(sample, local_data_reviewed=False)
    denied = evaluate_model_work(without_review, text=sample)
    assert denied.local_required and not denied.external_preferred
    assert denied.reason == "LOCAL_FALLBACK_EGRESS_NOT_ATTESTED"
    for role in (
        ModelWorkRole.HUMAN_MODEL, ModelWorkRole.SECRET_MANAGEMENT,
        ModelWorkRole.DATA_SENSITIVITY_REVIEW, ModelWorkRole.FINAL_CODE_REVIEW,
        ModelWorkRole.ERROR_RECOVERY,
    ):
        decision = evaluate_model_work(reviewed(sample, role), text=sample)
        assert decision.allowed and decision.local_required
        assert not decision.external_preferred

def test_reviewed_public_noncode_tasks_are_strata_eligible_only_after_attestation():
    roles = (ModelWorkRole.PUBLIC_TEXT_ANALYSIS,
             ModelWorkRole.PUBLIC_SUMMARIZATION,
             ModelWorkRole.PUBLIC_PLANNING,
             ModelWorkRole.PUBLIC_ERROR_TRIAGE,
             ModelWorkRole.PUBLIC_CODE_REVIEW)
    prompt = "Summarize public documentation about unit test isolation."
    for role in roles:
        assert evaluate_model_work(reviewed(prompt, role), text=prompt).external_preferred
        blocked = evaluate_model_work(ModelWorkContract(role), text=prompt)
        assert blocked.local_required and not blocked.external_preferred
    for role in (ModelWorkRole.HUMAN_MODEL, ModelWorkRole.PRIVATE_KLM,
                 ModelWorkRole.SECRET_MANAGEMENT, ModelWorkRole.FINAL_CODE_REVIEW):
        result = evaluate_model_work(reviewed(prompt, role), text=prompt)
        assert result.local_required and not result.external_preferred
