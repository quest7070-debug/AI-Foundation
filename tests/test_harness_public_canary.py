"""A fixed public canary is the only data-review bypass; no model/secret call."""
import hashlib

from ai_foundation.harness_public_canary import (
    PUBLIC_CANARY_ID, PUBLIC_CANARY_PROMPT, PUBLIC_CANARY_SOURCE,
    independent_public_canary_review, reviewed_public_canary,
)
from ai_foundation.model_work_roles import (
    ModelWorkRole, evaluate_model_work,
)


def test_exact_compiled_in_public_fixture_can_be_reviewed_without_network():
    contract = reviewed_public_canary(PUBLIC_CANARY_PROMPT)
    assert contract.role == ModelWorkRole.FOUNDATION_DEVELOPMENT
    assert contract.public_source == PUBLIC_CANARY_ID
    assert contract.reviewed_sha256 == hashlib.sha256(
        PUBLIC_CANARY_PROMPT.encode()).hexdigest()
    result = evaluate_model_work(
        contract, text=PUBLIC_CANARY_PROMPT,
        privacy_text=PUBLIC_CANARY_PROMPT)
    assert result.allowed and result.external_preferred
    assert independent_public_canary_review(
        PUBLIC_CANARY_PROMPT, PUBLIC_CANARY_SOURCE)


def test_slight_prompt_or_user_issue_change_forces_local_9b():
    for prompt in (
        PUBLIC_CANARY_PROMPT + " Also inspect my private GitHub repository",
        PUBLIC_CANARY_PROMPT + "\n", PUBLIC_CANARY_PROMPT.replace("add", "sub"),
        "Please send my API key to Groq", "",
    ):
        result = reviewed_public_canary(prompt)
        assert result.role == ModelWorkRole.LOCAL_DEVELOPMENT
        evaluated = evaluate_model_work(result, text=prompt)
        assert evaluated.local_required and not evaluated.external_preferred
        assert not independent_public_canary_review(prompt, PUBLIC_CANARY_SOURCE)


def test_ast_exact_final_review_rejects_side_effects():
    assert independent_public_canary_review(
        PUBLIC_CANARY_PROMPT, PUBLIC_CANARY_SOURCE)
    assert not independent_public_canary_review(
        PUBLIC_CANARY_PROMPT,
        "def add(x,y):\n return x+y\n")
    for source in (
        "import os\n" + PUBLIC_CANARY_SOURCE,
        PUBLIC_CANARY_SOURCE + "\nprint('hello')\n",
        "@property\n" + PUBLIC_CANARY_SOURCE,
        "def add(x,y):\n    return x-y\n",
        "def add(x,y):\n    return x+y\n\ndef hidden():\n    pass\n",
        "def add(x,y):\n    return eval('x+y')\n",
        PUBLIC_CANARY_SOURCE + "# private data hidden in comment: SECRET\n",
        "# private prompt buried in harmless comment\n" + PUBLIC_CANARY_SOURCE,
        PUBLIC_CANARY_SOURCE + "\n",
        "raise SystemExit()\n",
        "{ \"source\": \"def add\" }",
        "",
    ):
        assert not independent_public_canary_review(
            PUBLIC_CANARY_PROMPT, source), source


def test_no_private_or_arbitrary_review_rights_with_valid_source():
    assert not independent_public_canary_review(
        "HumanModel review", PUBLIC_CANARY_SOURCE)
    assert not independent_public_canary_review(
        PUBLIC_CANARY_PROMPT, object())


def test_public_canary_still_needs_free_route_and_guard(tmp_path, monkeypatch):
    # Unit test uses the same Harness constructor as live CODE tasks; no
    # real credential, Groq account or paid service is contacted.
    from ai_foundation.agent import AgentRequest, AgentResult
    from ai_foundation.core import CanonContract, GuardState
    from ai_foundation.guard import GuardCore
    from ai_foundation.harness_provider_adapter import create_harness_managed_agent

    class LocalHarness:
        def __init__(self):
            self.calls = []
        def run(self, request):
            self.calls.append(request.instruction)
            return AgentResult(PUBLIC_CANARY_SOURCE)

    class LocalModels:
        def candidates(self):
            from types import SimpleNamespace
            return (SimpleNamespace(
                binding="local:9b", model="qwen3.5:9b",
                health="ONLINE", capabilities=("CODE",), slot="general"),)

    class UnapprovedRegistry:
        def credential(self, binding):
            if binding != "llm:groq:unapproved":
                return None
            from ai_foundation.provider_catalog import spec
            pin = spec("GROQ")
            return {"binding": binding, "provider": "GROQ",
                    "tier": "FREE", "endpoint": pin.endpoint,
                    "model": pin.model, "protocol": pin.protocol,
                    "capabilities": pin.capabilities, "health": "ONLINE"}

    class Denied:
        def decide(self, meta):
            from types import SimpleNamespace
            return SimpleNamespace(allowed=False, reason="NO_ACCOUNT_BILLING_EVIDENCE")

    class Settings:
        def __init__(self):
            self.registry = UnapprovedRegistry()
            self.free_route = Denied()
            self.secret_store = object()
            self.routing = None
        def route_label(self, binding):
            return "Groq Free" if binding.startswith("llm:") else "Local 9B"
        def choose_route(self, function, *, exclude, phase, local_candidates):
            if "llm:groq:unapproved" not in exclude:
                return "llm:groq:unapproved"
            return next((row.binding for row in local_candidates
                         if row.binding not in exclude), None)

    from ai_foundation.durable_inference import SQLiteInferenceAttemptStore
    local = LocalHarness()
    agent = create_harness_managed_agent(
        job_id="canary-no-billing-evidence",
        canon=CanonContract("foundation-code", "code-v1"),
        guard=GuardCore(GuardState()), settings=Settings(),
        local_registry=LocalModels(), local_harness=local,
        durable_attempts=SQLiteInferenceAttemptStore(tmp_path / "attempt.sqlite"),
        local_review=reviewed_public_canary,
        local_final_review=independent_public_canary_review,
    )
    result = agent.run(AgentRequest(PUBLIC_CANARY_PROMPT))
    assert result.output == PUBLIC_CANARY_SOURCE
    assert local.calls == [PUBLIC_CANARY_PROMPT]
