"""Harness-managed external Free service; no live Groq/network or approvals."""
from dataclasses import dataclass
import json
from types import SimpleNamespace

import pytest

from ai_foundation.agent import AgentRequest, AgentResult
from ai_foundation.core import CanonContract, GuardState
from ai_foundation.guard import GuardCore
from ai_foundation.harness_provider_adapter import (
    GroqHarnessIPv4Transport, HarnessManagedProposalAgent,
    compiled_source, create_harness_managed_agent,
)
from ai_foundation.inference_service import InferenceOutcome
from ai_foundation.model_work_roles import (
    ModelWorkContract, ModelWorkRole, public_payload_hash,
)
from ai_foundation.provider_catalog import spec


SOURCE = "def add(x, y):\n    return x + y\n"
KEY = "gsk_" + "X" * 24


def public_contract(text):
    return ModelWorkContract(
        role=ModelWorkRole.FOUNDATION_DEVELOPMENT,
        data_class="PUBLIC_NONSECRET",
        public_source="fixture:harness-sanitized-python",
        reviewed_sha256=public_payload_hash(text),
        host_public_reviewed=True,
        external_transfer_allowed=True,
        local_data_reviewed=True,
        local_data_verdict="PUBLIC_NONSECRET",
    )


def test_cloud_transport_enforces_pinned_provider_and_no_secrets_in_argv():
    calls = []
    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        response = json.dumps({
            "choices": [{"message": {"content": SOURCE}}]
        }).encode() + b"\n200"
        return SimpleNamespace(returncode=0, stdout=response,
                               stderr=b"private-provider-message")
    adapter = GroqHarnessIPv4Transport(runner=fake_run)
    payload = {
        "model": spec("GROQ").model,
        "messages": [{"role": "user", "content": "Public: write add(x,y)."}],
    }
    result = adapter.send("GROQ", KEY, payload)
    assert result.status == 200
    assert json.loads(result.body)["choices"][0]["message"]["content"] == SOURCE
    assert len(calls) == 1
    argv, opts = calls[0]
    assert argv[0:2] == ["/usr/bin/curl", "-q"]
    assert "--ipv4" in argv and "--proto" in argv
    assert "--request" in argv and "POST" in argv
    assert "--location" not in argv and "--retry" not in argv
    assert "--noproxy" not in argv and "--config" in argv
    assert argv[-1] == spec("GROQ").endpoint
    assert KEY not in repr(argv)
    assert KEY.encode() in opts["input"]
    assert opts["capture_output"] and opts["timeout"] == 55
    body = json.loads(argv[argv.index("--data-binary") + 1])
    assert body["service_tier"] == "on_demand"
    assert body["max_completion_tokens"] == 4096
    assert "tools" not in body and "fallback_models" not in body


def test_transport_rejects_tool_access_private_expansion_and_model_override():
    calls = []
    def fail_if_network(*args, **kwargs):
        calls.append(True)
        raise AssertionError("network forbidden")
    t = GroqHarnessIPv4Transport(runner=fail_if_network)
    good = {
        "model": spec("GROQ").model,
        "messages": [{"role": "user", "content": "public"}],
    }
    candidates = (
        ("PAID_OTHER", good),
        ("GROQ", dict(good, model="model-latest")),
        ("GROQ", dict(good, tools=[{"type": "browser_search"}])),
        ("GROQ", dict(good, fallback_models=["paid"])),
        ("GROQ", dict(good, service_tier="auto")),
        ("GROQ", dict(good, messages=[{"role": "system", "content": "hidden"}])),
        ("GROQ", dict(good, messages=[{"role": "user", "content": "x" * 4097}])),
    )
    for provider, payload in candidates:
        with pytest.raises(ValueError):
            t.send(provider, KEY, payload)
    assert calls == []


def test_transport_ambiguous_result_never_leaks_or_retries():
    calls = []
    def failed(argv, **kwargs):
        calls.append(True)
        return SimpleNamespace(returncode=56, stdout=b"", stderr=b"secret")
    t = GroqHarnessIPv4Transport(runner=failed)
    payload = {"model": spec("GROQ").model,
               "messages": [{"role": "user", "content": "public"}]}
    with pytest.raises(RuntimeError, match="GROQ_HARNESS_REQUEST_UNCERTAIN"):
        t.send("GROQ", KEY, payload)
    assert len(calls) == 1


def test_proposals_compile_without_running_source():
    assert compiled_source(SOURCE) == SOURCE
    assert compiled_source(json.dumps(SOURCE)) == SOURCE
    for invalid in ('return 1', 'hello', '"""only a string"""'):
        with pytest.raises((SyntaxError, ValueError)):
            compiled_source(invalid)


class FakeInference:
    def __init__(self, outcomes):
        self.attempts = object()
        self.outcomes = list(outcomes)
        self.plans = []
    def run(self, plan, canon, function, *, role_contract):
        self.plans.append((plan, canon, function, role_contract))
        return self.outcomes.pop(0)


def test_harness_adapter_passes_exact_reviewed_code_through_local_final_review():
    fake = FakeInference([
        InferenceOutcome("VERIFIED_COMPLETE", "CLOUD", SOURCE, "llm:groq:free")
    ])
    reviews = []
    def final(prompt, source):
        reviews.append((prompt, source))
        return True
    harness = HarnessManagedProposalAgent(
        job_id="issue-123", canon=CanonContract("test", "c"),
        inference=fake, local_review=public_contract,
        local_final_review=final,
    )
    request = AgentRequest("Public code task")
    assert harness.run(request) == AgentResult(SOURCE)
    plan, canon, function, contract = fake.plans[0]
    assert plan.text == request.instruction
    assert plan.privacy_text == request.instruction
    assert plan.paid_cost == 0 and plan.effect_id == "issue-123:proposal:1"
    assert function == "CODE" and contract.reviewed_sha256 == public_payload_hash(plan.text)
    assert reviews == [(request.instruction, SOURCE)]


def test_missing_local_review_is_local_only_and_unknown_evidence_cannot_grant():
    fake = FakeInference([
        InferenceOutcome("VERIFIED_COMPLETE", "LOCAL", SOURCE, "local:9b")
    ])
    harness = HarnessManagedProposalAgent(
        job_id="issue-124", canon=CanonContract("test", "c"),
        inference=fake, local_review=lambda _: None,
        local_final_review=lambda *_: (_ for _ in ()).throw(
            AssertionError("local source should not need external final review")),
    )
    assert harness.run(AgentRequest("secret-ish task")).output == SOURCE
    contract = fake.plans[0][3]
    assert contract.role == ModelWorkRole.LOCAL_DEVELOPMENT


def test_cloud_rejected_by_local_final_review_never_writes():
    fake = FakeInference([
        InferenceOutcome("VERIFIED_COMPLETE", "CLOUD", SOURCE, "llm:groq:free")
    ])
    harness = HarnessManagedProposalAgent(
        job_id="issue-125", canon=CanonContract("test", "c"),
        inference=fake, local_review=public_contract,
        local_final_review=lambda *_: False,
    )
    with pytest.raises(RuntimeError, match="HARNESS_LOCAL_FINAL_REVIEW_REQUIRED"):
        harness.run(AgentRequest("Public code task"))


def test_inference_adapter_requires_durable_store_and_real_host_callbacks():
    fake = FakeInference([])
    fake.attempts = None
    with pytest.raises(ValueError, match="HARNESS_DURABLE_CLOUD_ATTEMPTS_REQUIRED"):
        HarnessManagedProposalAgent(
            job_id="issue-1", canon=CanonContract("test", "c"),
            inference=fake, local_review=public_contract,
            local_final_review=lambda *_: True)
    with pytest.raises(ValueError, match="HARNESS_TRUSTED_HOST_BINDINGS_REQUIRED"):
        HarnessManagedProposalAgent(
            job_id="issue-1", canon=CanonContract("test", "c"),
            inference=FakeInference([]), local_review=None,
            local_final_review=lambda *_: True)


@dataclass(frozen=True)
class LocalCandidate:
    binding: str = "local:9b"
    health: str = "ONLINE"
    capabilities: tuple = ("CODE",)
    model: str = "qwen3.5:9b"
    slot: str = "local-general"


class LocalRegistry:
    def candidates(self):
        return (LocalCandidate(),)


class StubRegistry:
    def credential(self, binding):
        return {
            "binding": binding, "provider": "GROQ", "tier": "FREE",
            "model": spec("GROQ").model,
            "endpoint": spec("GROQ").endpoint,
            "health": "ONLINE",
        }


class DeniedAdmission:
    def decide(self, meta):
        return SimpleNamespace(allowed=False, reason="NO_ACCOUNT_BILLING_EVIDENCE")


class Settings:
    def __init__(self):
        self.free_route = DeniedAdmission()
        self.registry = StubRegistry()
        self.secret_store = object()
        self.routing = None
    def choose_route(self, function, *, exclude, phase, local_candidates):
        if "llm:groq:unaccepted" not in exclude:
            return "llm:groq:unaccepted"
        return next((c.binding for c in local_candidates
                     if c.binding not in exclude), None)
    def route_label(self, binding):
        return "Groq Free" if binding.startswith("llm:groq:") else "Local"


class LocalHarness:
    def __init__(self):
        self.calls = []
    def run(self, request):
        self.calls.append(request.instruction)
        return AgentResult(SOURCE)


def test_canonical_builder_skips_unapproved_groq_and_uses_local_harness():
    local = LocalHarness()
    agent = create_harness_managed_agent(
        job_id="issue-126", canon=CanonContract("foundation", "c"),
        guard=GuardCore(GuardState()), settings=Settings(),
        local_registry=LocalRegistry(), local_harness=local,
        durable_attempts=object(), local_review=public_contract,
        local_final_review=lambda *_: True,
    )
    assert agent.run(AgentRequest("Public fixture coding")).output == SOURCE
    assert local.calls == ["Public fixture coding"]


class EligibleAdmission:
    def decide(self, meta):
        return SimpleNamespace(allowed=True, reason="ATTESTED_FREE_ROUTE")
    def require(self, meta, payload):
        if payload.get("model") != spec("GROQ").model:
            raise PermissionError("MODEL_OVERRIDE")


class LiveRegistry(StubRegistry):
    def __init__(self):
        self.observations = []
    def credential(self, binding):
        return {**super().credential(binding), "protocol": "openai-chat",
                "capabilities": ("CODE",)}
    def observe(self, binding, **kw):
        self.observations.append((binding, kw))
        return True


class EligibleSettings(Settings):
    def __init__(self):
        super().__init__()
        self.free_route = EligibleAdmission()
        self.registry = LiveRegistry()
        self.secret_store = SimpleNamespace(load=lambda binding: KEY)


def test_admitted_groq_runs_as_host_agent_and_local_final_review(tmp_path, monkeypatch):
    from ai_foundation.cloud_execution import CloudResponse
    from ai_foundation.durable_inference import SQLiteInferenceAttemptStore
    import ai_foundation.harness_provider_adapter as subject
    calls = []
    class FixtureGroq:
        def send(self, provider, secret, payload):
            calls.append((provider, secret, payload))
            return CloudResponse(
                200, {},
                json.dumps({"choices": [{"message": {"content": SOURCE}}]}))
    monkeypatch.setattr(subject, "GroqHarnessIPv4Transport", FixtureGroq)
    local = LocalHarness()
    final = []
    s = EligibleSettings()
    agent = create_harness_managed_agent(
        job_id="issue-201", canon=CanonContract("foundation", "c"),
        guard=GuardCore(GuardState()), settings=s,
        local_registry=LocalRegistry(), local_harness=local,
        durable_attempts=SQLiteInferenceAttemptStore(tmp_path / "attempts.sqlite"),
        local_review=public_contract,
        local_final_review=lambda prompt, source: final.append(
            (prompt, source)) or True,
    )
    output = agent.run(AgentRequest("Public simple addition function"))
    assert output.output == SOURCE
    assert not local.calls
    assert len(calls) == 1
    assert calls[0][0] == "GROQ" and calls[0][1] == KEY
    assert calls[0][2]["model"] == spec("GROQ").model
    assert calls[0][2]["messages"] == [
        {"role": "user", "content": "Public simple addition function"}]
    assert final == [("Public simple addition function", SOURCE)]


def test_groq_rate_limited_falls_back_to_local_harness_without_second_cloud_call(
        tmp_path, monkeypatch):
    from ai_foundation.cloud_execution import CloudResponse
    from ai_foundation.durable_inference import SQLiteInferenceAttemptStore
    import ai_foundation.harness_provider_adapter as subject
    sends = []
    class RateLimitedGroq:
        def send(self, provider, secret, payload):
            sends.append(True)
            return CloudResponse(
                429, {}, '{"error":{"type":"rate_limit_error"}}')
    monkeypatch.setattr(subject, "GroqHarnessIPv4Transport", RateLimitedGroq)
    local = LocalHarness()
    agent = create_harness_managed_agent(
        job_id="issue-202", canon=CanonContract("foundation", "c"),
        guard=GuardCore(GuardState()), settings=EligibleSettings(),
        local_registry=LocalRegistry(), local_harness=local,
        durable_attempts=SQLiteInferenceAttemptStore(tmp_path / "attempts.sqlite"),
        local_review=public_contract,
        local_final_review=lambda *_: True,
    )
    assert agent.run(AgentRequest("Public simple addition function")).output == SOURCE
    assert len(sends) == 1
    assert local.calls == ["Public simple addition function"]


def test_host_entry_uses_same_guarded_development_loop_not_second_scheduler(monkeypatch):
    import ai_foundation.development_host as host
    import ai_foundation.harness_provider_adapter as adapter
    received = {}
    sentinel = object()
    def construct(**kwargs):
        received["adapter"] = kwargs
        return sentinel
    def execute(**kwargs):
        received["development"] = kwargs
        return "DRAFT_FROM_EXISTING_HOST"
    monkeypatch.setattr(adapter, "create_harness_managed_agent", construct)
    monkeypatch.setattr(host, "run_local_development_task", execute)
    result = host.run_harness_managed_development_task(
        root="owned-checkout", guard="canonical-guard",
        tests="host-tests", local_harness="pinned-sandboxed-harness",
        local_registry="existing-local-models", settings="free-service-registry",
        durable_attempts="durable-inference-receipts",
        local_review=public_contract, local_final_review=lambda *_: True,
        lease="host-lease", instruction="authorized public code",
        target="src/example.py", acceptance_target="tests/test_example.py",
        repository="quest7070-dev/AI-Foundation",
        branch="draft/guarded", job_id="issue-200",
    )
    assert result == "DRAFT_FROM_EXISTING_HOST"
    assert received["development"]["proposal_agent"] is sentinel
    assert received["development"]["guard"] == "canonical-guard"
    assert received["development"]["tests"] == "host-tests"
    assert received["development"]["lease"] == "host-lease"
    assert received["development"]["branch"] == "draft/guarded"
    assert received["adapter"]["local_registry"] == "existing-local-models"
    assert received["adapter"]["local_harness"] == "pinned-sandboxed-harness"

def test_distinct_development_lease_does_not_serialize_cloud_with_local_9b(monkeypatch):
    from contextlib import contextmanager
    import ai_foundation.development_host as host
    import ai_foundation.harness_provider_adapter as adapter
    events = []

    class Lease:
        def __init__(self, tag):
            self.tag = tag
        @contextmanager
        def hold(self):
            events.append(self.tag + ":start")
            try:
                yield
            finally:
                events.append(self.tag + ":end")

    class RealLocal:
        def run(self, request):
            events.append("9b-inference")
            return AgentResult(SOURCE)

    def choose(**kwargs):
        events.append("compose")
        return kwargs["local_harness"]
    def launch(**kwargs):
        with kwargs["lease"].hold():
            events.append("cloud-inference")
            output = kwargs["proposal_agent"].run(AgentRequest("public"))
            assert output.output == SOURCE
        return "GUARDED_DRAFT"

    monkeypatch.setattr(adapter, "create_harness_managed_agent", choose)
    monkeypatch.setattr(host, "run_local_development_task", launch)
    args = dict(
        root="owned-checkout", guard="canonical-guard", tests="fixed-tests",
        local_harness=RealLocal(), local_registry="local-models",
        settings="real-Free-route", durable_attempts="durable-records",
        local_review=lambda *_: None, local_final_review=lambda *_: True,
        lease=Lease("9b"), development_lease=Lease("job"),
        instruction="public", target="src/example.py",
        acceptance_target="tests/test_example.py",
        repository="quest7070-dev/AI-Foundation",
        branch="draft/guarded", job_id="issue-lease-separation",
    )
    assert host.run_harness_managed_development_task(**args) == "GUARDED_DRAFT"
    assert events == ["compose", "job:start", "cloud-inference",
                      "9b:start", "9b-inference", "9b:end", "job:end"]
    with pytest.raises(ValueError, match="SEPARATE_DEVELOPMENT_LEASE_REQUIRED"):
        host.run_harness_managed_development_task(
            **dict(args, development_lease=args["lease"]))
