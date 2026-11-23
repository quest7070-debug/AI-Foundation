"""No-network Strata route acceptance for M1 private work and public CODE."""
import hashlib
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from ai_foundation.agent import AgentRequest, AgentResult
from ai_foundation.compute_routing import ComputeRouter
from ai_foundation.core import CanonContract, GuardState
from ai_foundation.guard import GuardCore
from ai_foundation.harness_provider_adapter import create_harness_managed_agent
from ai_foundation.harness_service_registry import HarnessServiceRegistry
from ai_foundation.local_compute_registry import (
    LocalComputeCandidate, CompositeLocalComputeRegistry,
)
from ai_foundation.model_work_roles import ModelWorkContract, ModelWorkRole
from ai_foundation.openai_local_adapter import OpenAILocalExecution
from scripts import mainpc_strata_preflight as probe


class Registry:
    def __init__(self, *candidates):
        self.rows = candidates
    def candidates(self):
        return self.rows


class Settings:
    free_route = object()
    registry = object()
    def choose_route(self, *a, **kw):
        return None


class M1Harness:
    def __init__(self):
        self.calls = 0
    def run(self, request):
        self.calls += 1
        return AgentResult("VALUE = 1\n")


class Reply:
    def __init__(self):
        self.status = 200
    def __enter__(self):
        return self
    def __exit__(self, *exc):
        return None
    def read(self, n):
        return b'{"choices":[{"message":{"content":"VALUE = 2\\n"}}]}'


def public_review(prompt):
    return ModelWorkContract(
        ModelWorkRole.FOUNDATION_DEVELOPMENT,
        data_class="PUBLIC_NONSECRET",
        public_source="synthetic-fixture",
        reviewed_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
        host_public_reviewed=True, external_transfer_allowed=True,
        local_data_reviewed=True, local_data_verdict="PUBLIC_NONSECRET")


def test_strata_is_real_selected_execution_and_private_stays_on_m1():
    observations = []
    def opener(req, timeout):
        observations.append((req.full_url, req.data.decode(), timeout))
        return Reply()
    remote = OpenAILocalExecution(
        "http://10.0.1.1:8080", allowed_hosts=("10.0.1.1",),
        alias_to_model={"code-agent": "qwen3.8-flash-next-coder-iq1_m"},
        opener=opener, timeout=300)
    candidates = CompositeLocalComputeRegistry(
        Registry(LocalComputeCandidate(
            "local:mainpc-strata:code-agent", health="ONLINE", active=True,
            capabilities=("CODE",), model="qwen3.8-flash-next-coder-iq1_m",
            slot="code-agent", same_host=False)),
        Registry(LocalComputeCandidate(
            "local:m1:code-agent", health="ONLINE", active=True,
            capabilities=("CODE",), model="m1-fixture", slot="code-agent")))
    m1 = M1Harness()
    agent = create_harness_managed_agent(
        job_id="fixture-public", canon=CanonContract("foundation-code", "code-v1"),
        guard=GuardCore(GuardState()), settings=Settings(),
        local_registry=candidates, local_harness=m1,
        durable_attempts=object(), local_review=public_review,
        local_final_review=lambda *_: True,
        service_adapters=HarnessServiceRegistry(),
        local_execution_by_prefix=(("local:mainpc-strata", remote),))
    assert agent.run(AgentRequest("Public synthetic coding fixture")).output == "VALUE = 2\n"
    assert len(observations) == 1 and m1.calls == 0
    assert "/v1/chat/completions" in observations[0][0]
    assert '"model": "qwen3.8-flash-next-coder-iq1_m"' in observations[0][1]
    assert observations[0][2] == 300

    private = create_harness_managed_agent(
        job_id="fixture-private", canon=CanonContract("foundation-code", "code-v1"),
        guard=GuardCore(GuardState()), settings=Settings(),
        local_registry=candidates, local_harness=m1,
        durable_attempts=object(),
        local_review=lambda *_: ModelWorkContract(ModelWorkRole.LOCAL_DEVELOPMENT),
        local_final_review=lambda *_: True,
        service_adapters=HarnessServiceRegistry(),
        local_execution_by_prefix=(("local:mainpc-strata", remote),))
    assert private.run(AgentRequest("Private data must not leave M1")).output == "VALUE = 1\n"
    assert m1.calls == 1 and len(observations) == 1

    # A discovered remote candidate without a trusted real execution binding
    # must never masquerade as Strata after falling into the M1 CLI.
    without_port = create_harness_managed_agent(
        job_id="fixture-unbound", canon=CanonContract("foundation-code", "code-v1"),
        guard=GuardCore(GuardState()), settings=Settings(),
        local_registry=candidates, local_harness=m1, durable_attempts=object(),
        local_review=public_review, local_final_review=lambda *_: True,
        service_adapters=HarnessServiceRegistry())
    assert without_port.run(AgentRequest("Public fixture with no Strata port")).output == "VALUE = 1\n"
    assert m1.calls == 2 and len(observations) == 1


def test_compute_router_never_treats_windows_local_as_private_execution():
    remote = LocalComputeCandidate(
        "local:mainpc-strata:code-agent", health="ONLINE",
        capabilities=("CODE",), same_host=False, slot="code-agent")
    local = LocalComputeCandidate(
        "local:m1:code-agent", health="ONLINE",
        capabilities=("CODE",), same_host=True, slot="code-agent")
    router = ComputeRouter(Settings(), Registry(remote))
    assert router.choose("CODE", local_required=True).binding is None
    assert router.choose("CODE").binding == remote.binding
    router = ComputeRouter(Settings(), Registry(remote, local))
    assert router.choose("CODE", local_required=True).binding == local.binding


def test_one_shot_wake_existing_script_is_explicit_only(tmp_path, monkeypatch):
    script = tmp_path / "wake-desktop.py"
    script.write_text("# existing user-owned fake script\n")
    script.chmod(0o600)
    calls = []
    online = [False]
    clock = [0.0]
    class Discovery:
        def candidates(self):
            if not online[0]:
                return ()
            return (LocalComputeCandidate(
                "local:mainpc-strata:code-agent",
                health="ONLINE", same_host=False),)
    class Execution:
        models = {"code-agent": "qwen3.8-flash-next-coder-iq1_m"}
        def chat(self, text, model):
            assert text == probe._SMOKE and model == "code-agent"
            return "STRATA_ROUTE_OK"
    monkeypatch.setattr(probe, "load_local_endpoints",
                        lambda _: (("local:mainpc-strata", Discovery(), Execution()),))
    def runner(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0)
    def sleep(seconds):
        clock[0] += seconds
        online[0] = True
    args = dict(home=tmp_path, runner=runner,
                monotonic=lambda: clock[0], sleep=sleep)
    assert probe.verify_strata("host-config", **args)["status"] == "MAINPC_UNAVAILABLE"
    assert calls == []
    result = probe.verify_strata("host-config", wake=True, smoke=True, **args)
    assert result == {"status": "INFERENCE_VERIFIED"}
    assert len(calls) == 1 and Path(calls[0][-1]) == script
    online[0] = False
    script.chmod(0o666)
    assert probe.verify_strata("host-config", wake=True, **args) == {
        "status": "WAKE_UNAVAILABLE"}
    assert len(calls) == 1

def test_optional_mainpc_configuration_does_not_block_m1_without_key(tmp_path, monkeypatch):
    import json
    from ai_foundation import native_credentials
    def missing_owner_key(*_):
        raise KeyError("SYNTHETIC_MISSING_OWNER_KEY")
    # This case models an unenrolled owner; never read the actual M1 Keychain.
    monkeypatch.setattr(native_credentials.MacOSNativeCredentialStore, "load", missing_owner_key)
    from ai_foundation.local_endpoint_config import load_local_endpoints
    template = (Path(__file__).parents[1] /
                "docs/configs/mainpc-strata-endpoints.example.json")
    data = json.loads(template.read_text())
    assert data["endpoints"][0]["optional"] is True
    installed = tmp_path / "endpoints.json"
    installed.write_text(json.dumps(data))
    monkeypatch.delenv("STRATA_API_KEY", raising=False)
    assert load_local_endpoints(installed) == ()
    monkeypatch.setenv("STRATA_API_KEY", "")
    assert load_local_endpoints(installed) == ()  # no unauthenticated Strata
    monkeypatch.setenv("STRATA_API_KEY", "test-synthetic-only")
    prefixes = load_local_endpoints(installed)
    assert len(prefixes) == 1 and prefixes[0][0] == "local:mainpc-strata"
    assert prefixes[0][2].models == {
        "code-agent": "qwen3.8-flash-next-coder-iq1_m"}

def test_offline_cached_remote_local_binding_never_becomes_cloud():
    class Stale(Settings):
        def choose_route(self, *a, **kw):
            return "local:mainpc-strata:code-agent"
    m1 = LocalComputeCandidate(
        "local:m1:code-agent", health="ONLINE", capabilities=("CODE",),
        same_host=True, slot="code-agent")
    route = ComputeRouter(Stale(), Registry(m1)).choose("CODE")
    assert route.binding == "local:m1:code-agent"
    assert route.kind == "LOCAL"
    assert ComputeRouter(Stale(), Registry()).choose("CODE").binding is None



def test_strata_m1_bridge_reports_real_configuration_without_key_or_prompt(
        tmp_path, monkeypatch):
    import json
    from scripts import m1_runtime_status_probe as status
    from scripts import m1_development_bridge as bridge
    monkeypatch.setattr(status, "require_m1", lambda: None)
    source = (Path(__file__).parents[1] /
              "docs/configs/mainpc-strata-endpoints.example.json")
    installed = tmp_path / "endpoints.json"
    installed.write_bytes(source.read_bytes())
    installed.chmod(0o600)
    monkeypatch.delenv("STRATA_API_KEY", raising=False)
    assert status.strata_status(config_path=installed) == {
        "status": "RUNNER_KEY_UNAVAILABLE", "model_calls": 0,
        "note": "Owner Operator credentials not inferred"}
    from scripts import mainpc_strata_preflight as preflight
    calls = []
    def checked(config, **kwargs):
        calls.append(kwargs)
        return {"status": "MODEL_DISCOVERED"}
    monkeypatch.setenv("STRATA_API_KEY", "SYNTHETIC_DO_NOT_REPORT")
    monkeypatch.setattr(preflight, "verify_strata", checked)
    observed = status.strata_status(config_path=installed)
    assert observed == {"status": "MODEL_DISCOVERED",
                        "model_calls": 0, "wake_calls": 0}
    assert calls == [{"wake": False, "smoke": False}]
    assert "SYNTHETIC" not in str(observed)
    request = ('<!-- foundation-m1-bridge: '
               '{"version":1,"operation":"strata-status"} -->')
    assert bridge.parse_request("Foundation M1 Bridge: strata-status",
                                request) == "strata-status"
    installed.chmod(0o644)
    assert status.strata_status(config_path=installed)["status"] == \
        "MAINPC_CONFIG_UNTRUSTED"
    installed.chmod(0o600)
    wrong = json.loads(source.read_text())
    wrong["endpoints"][0]["api_key_env"] = "ARBITRARY_SECRET"
    installed.write_text(json.dumps(wrong))
    assert status.strata_status(config_path=installed)["status"] == \
        "MAINPC_CONFIG_INVALID"



@pytest.mark.parametrize("field, value, reason", [
    ("base_url", "http://10.0.1.1:8080/unreviewed", "URL_POLICY"),
    ("allowed_hosts", ["unrelated.invalid"], "HOST_ALLOWLIST"),
    ("api_key_env", "UNREVIEWED_CREDENTIAL", "KEY_BINDING"),
    ("optional", False, "OPTIONAL_GUARD"),
    ("models", [{"alias": "general", "runtime_model": "other",
                 "capabilities": ["CHAT"]}], "CODE_MODEL_POLICY"),
])
def test_strata_owner_denial_reports_only_fixed_reason(
        tmp_path, monkeypatch, field, value, reason):
    import json
    from scripts import m1_runtime_status_probe as status
    monkeypatch.setattr(status, "require_m1", lambda: None)
    sample = json.loads((Path(__file__).parents[1] /
                         "docs/configs/mainpc-strata-endpoints.example.json").read_text())
    sample["endpoints"][0][field] = value
    config = tmp_path / "endpoints.json"
    config.write_text(json.dumps(sample))
    config.chmod(0o600)
    monkeypatch.setenv("STRATA_API_KEY", "SYNTHETIC_PRIVATE_KEY")
    assert status.strata_status(config_path=config) == {
        "status": "MAINPC_CONFIG_INVALID", "reason_code": reason}



def test_strata_owner_scoped_alias_not_confused_with_runner_generic_secrets(
        tmp_path, monkeypatch):
    import json
    from scripts import m1_runtime_status_probe as status
    from scripts import mainpc_strata_preflight as preflight
    monkeypatch.setattr(status, "require_m1", lambda: None)
    source = (Path(__file__).parents[1] /
              "docs/configs/mainpc-strata-endpoints.example.json")
    row = json.loads(source.read_text())
    row["endpoints"][0]["api_key_env"] = "MAINPC_STRATA_OWNER_TOKEN"
    path = tmp_path / "endpoints.json"
    path.write_text(json.dumps(row))
    path.chmod(0o600)
    monkeypatch.setenv("GITHUB_TOKEN", "MUST_NEVER_BECOME_STRATA_BEARER")
    monkeypatch.setenv("STRATA_API_KEY", "OTHER_STRATA_BINDING")
    monkeypatch.delenv("MAINPC_STRATA_OWNER_TOKEN", raising=False)
    assert status.strata_status(config_path=path)["status"] == \
        "RUNNER_KEY_UNAVAILABLE"
    calls = []
    def discover(config, **kw):
        calls.append(kw)
        return {"status": "MODEL_DISCOVERED"}
    monkeypatch.setattr(preflight, "verify_strata", discover)
    monkeypatch.setenv("MAINPC_STRATA_OWNER_TOKEN", "SYNTHETIC_STRATA_ONLY")
    observed = status.strata_status(config_path=path)
    assert observed == {"status": "MODEL_DISCOVERED",
                        "model_calls": 0, "wake_calls": 0}
    assert calls == [{"wake": False, "smoke": False}]
    assert "TOKEN" not in str(observed)
    row["endpoints"][0]["api_key_env"] = "GITHUB_TOKEN"
    path.write_text(json.dumps(row))
    assert status.strata_status(config_path=path) == {
        "status": "MAINPC_CONFIG_INVALID", "reason_code": "KEY_BINDING"}


def test_mac_keychain_fallback_is_strata_only_and_never_unauthenticated(tmp_path,monkeypatch):
    import json
    from pathlib import Path
    from ai_foundation import local_endpoint_config as cfg
    from ai_foundation import native_credentials
    data = json.loads((Path(__file__).parents[1] /
        "docs/configs/mainpc-strata-endpoints.example.json").read_text())
    endpoint = data["endpoints"][0]
    endpoint["base_url"] = "http://10.0.1.1:18080"
    path = tmp_path / "endpoints.json"
    path.write_text(json.dumps(data))
    monkeypatch.delenv("STRATA_API_KEY",raising=False)
    monkeypatch.setattr(cfg.platform,"system",lambda:"Darwin")
    calls=[]
    class Store:
        def load(self,binding):
            calls.append(binding)
            return "keychain-synthetic"
    monkeypatch.setattr(native_credentials,"MacOSNativeCredentialStore",Store)
    rows=cfg.load_local_endpoints(path)
    assert rows[0][2].api_key == "keychain-synthetic"
    assert calls == ["local:mainpc-strata:api-key"]
    endpoint["name"]="other-provider"
    path.write_text(json.dumps(data))
    assert cfg.load_local_endpoints(path) == ()
    assert len(calls) == 1


def test_mac_keychain_unavailable_preserves_optional_fallback(tmp_path,monkeypatch):
    import json
    from pathlib import Path
    from ai_foundation import local_endpoint_config as cfg
    from ai_foundation import native_credentials
    data = json.loads((Path(__file__).parents[1] /
        "docs/configs/mainpc-strata-endpoints.example.json").read_text())
    path = tmp_path / "endpoints.json"
    path.write_text(json.dumps(data))
    monkeypatch.delenv("STRATA_API_KEY",raising=False)
    monkeypatch.setattr(cfg.platform,"system",lambda:"Darwin")
    class Store:
        def load(self,binding):
            raise KeyError(binding)
    monkeypatch.setattr(native_credentials,"MacOSNativeCredentialStore",Store)
    assert cfg.load_local_endpoints(path) == ()

def test_public_noncode_summary_really_calls_strata_and_private_uses_m1():
    from ai_foundation.core import Decision, TaskPlan
    from ai_foundation.inference_service import GuardedInferenceService
    from ai_foundation.openai_local_adapter import LocalExecutionDispatcher
    from ai_foundation.model_work_roles import public_payload_hash
    calls = []
    def opener(req, timeout):
        calls.append((req.full_url, req.data.decode(), timeout))
        return Reply()
    strata = OpenAILocalExecution(
        "http://10.0.1.1:8080", allowed_hosts=("10.0.1.1",),
        alias_to_model={"code-agent": "qwen3.8-flash-next-coder-iq1_m"},
        opener=opener)
    class M1:
        def chat(self, prompt, model=None):
            return "M1_ONLY"
    class Allow:
        def preflight(self, *args): return Decision.ALLOW
    class CloudFirst:
        def choose_route(self, *args, **kwargs): return "cloud:reviewed-free"
    router = ComputeRouter(CloudFirst(), Registry(
        LocalComputeCandidate("local:mainpc-strata:code-agent",
            health="ONLINE", capabilities=("CODE", "CHAT"),
            model="qwen3.8-flash-next-coder-iq1_m", slot="code-agent",
            same_host=False),
        LocalComputeCandidate("local:m1:general", health="ONLINE",
            capabilities=("CHAT",), model="fixture-9b", slot="general",
            same_host=True)))
    service = GuardedInferenceService(
        Allow(), router, LocalExecutionDispatcher(M1(),
          (("local:mainpc-strata", strata),)))
    prompt = "Summarize this public synthetic API note."
    plan = TaskPlan("summary-1", "compute", "llm", text=prompt,
                    canon_revision="v1", privacy_text=prompt)
    pub = ModelWorkContract(
        ModelWorkRole.PUBLIC_SUMMARIZATION, data_class="PUBLIC_NONSECRET",
        public_source="fixture:summary", reviewed_sha256=public_payload_hash(prompt),
        host_public_reviewed=True, external_transfer_allowed=True,
        local_data_reviewed=True, local_data_verdict="PUBLIC_NONSECRET")
    result = service.run(plan, CanonContract("fixture", "v1"),
                         function="CHAT", role_contract=pub)
    assert result.status == "VERIFIED_COMPLETE"
    assert result.route_binding == "local:mainpc-strata:code-agent"
    assert result.result == "VALUE = 2\n"
    assert len(calls) == 1
    assert 'qwen3.8-flash-next-coder-iq1_m' in calls[0][1]

    private = TaskPlan("private-1", "compute", "llm",
                       text="private owner summary", canon_revision="v1")
    blocked = service.run(private, CanonContract("fixture", "v1"),
                          function="CHAT",
                          role_contract=ModelWorkContract(ModelWorkRole.HUMAN_MODEL))
    assert blocked.status == "VERIFIED_COMPLETE"
    assert blocked.result == "M1_ONLY"
    assert blocked.route_binding == "local:m1:general"
    assert len(calls) == 1
