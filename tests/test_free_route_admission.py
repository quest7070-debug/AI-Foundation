"""Small no-network acceptance tests for the host-owned free-inference gate."""
import pytest

from ai_foundation.free_route_admission import SQLiteFreeRouteAdmission, fixed_model
from ai_foundation.cloud_execution import ObservedCloudExecution, CloudResponse
from ai_foundation.provider_registry import SQLiteProviderRegistry
from ai_foundation.provider_observer import ProviderResponseObserver
from ai_foundation.settings_service import SettingsService
from ai_foundation.provider_onboarding import ProbeResult


class Secrets:
    def __init__(self):
        self.loads = 0
    def available(self, binding):
        return True
    def load(self, binding):
        self.loads += 1
        return "mock-secret"
    def save(self, binding, secret):
        pass
    def delete(self, binding):
        return True


class Transport:
    def __init__(self):
        self.calls = 0
    def send(self, provider, secret, payload):
        self.calls += 1
        return CloudResponse(200, {}, '{"choices":[{"message":{"content":"ok"}}]}')


class Probe:
    def probe(self, secret, provider=None):
        return ProbeResult(provider or "GROQ", "ONLINE")


def select(gate, meta):
    gate.select(meta, account_alias="account-hash-1",
                project_alias="project-hash-1")


def environment(tmp_path, *, local_compute=None):
    gate = SQLiteFreeRouteAdmission(tmp_path / "no-charge.sqlite", clock=lambda: 1000)
    secrets = Secrets()
    settings = SettingsService(tmp_path / "settings", Probe(), secrets,
                               local_compute=local_compute, free_route=gate)
    settings.registry.upsert(
        "llm:groq:test", "GROQ", tier="FREE", health="ONLINE",
        endpoint="https://api.groq.com/openai/v1/chat/completions",
        model="openai/gpt-oss-20b", protocol="openai-chat",
        capabilities=("CHAT",))
    return gate, settings, secrets


def test_fixed_model_rejects_control_characters():
    for model in ("provider/model\x00hidden", "provider/model\x1b", "provider/model\x7f", "provider/with space", "provider/with\u2003space",
                  "provider/model\u0085", "provider/model\u202e", "provider/model\u200d"):
        assert fixed_model(model) is False
    assert fixed_model("provider/model:free") is True


def test_default_deny_cannot_route_or_send_even_with_free_tier_and_quota(tmp_path):
    gate, settings, secrets = environment(tmp_path)
    binding = "llm:groq:test"
    settings.optimize_routing("CHAT")
    assert settings.choose_route("CHAT") is None
    transport = Transport()
    execution = ObservedCloudExecution(
        settings.registry, secrets,
        ProviderResponseObserver(settings.registry), transport, admission=gate)
    with pytest.raises(PermissionError, match="NOT_MANUALLY_SELECTED"):
        execution.invoke_for_function(binding, {"messages": []}, "CHAT")
    assert transport.calls == 0 and secrets.loads == 0
    assert settings.registry.credential(binding)["active"] is False


def test_specific_fresh_receipt_enables_only_exact_account_model_route(tmp_path):
    gate, settings, secrets = environment(tmp_path)
    meta = settings.registry.credential("llm:groq:test")
    select(gate, meta)
    assert gate.decide(meta).allowed
    settings.optimize_routing("CHAT")
    assert settings.choose_route("CHAT") == meta["binding"]
    transport = Transport()
    execution = ObservedCloudExecution(
        settings.registry, secrets,
        ProviderResponseObserver(settings.registry), transport, admission=gate)
    execution.invoke_for_function(meta["binding"], {"messages": []}, "CHAT")
    assert transport.calls == 1
    with pytest.raises(PermissionError, match="MODEL_OVERRIDE"):
        execution.invoke(meta["binding"], {"model": "paid-model", "messages": []})
    with pytest.raises(PermissionError, match="UNPRICED_PROVIDER_TOOLS"):
        execution.invoke(meta["binding"], {
            "model": meta["model"], "tools": [{"type": "browser_search"}]})
    for tier in ("auto", "flex", "performance"):
        with pytest.raises(PermissionError, match="UNBOUND_SERVICE_TIER"):
            execution.invoke(meta["binding"], {
                "model": meta["model"], "service_tier": tier, "messages": []})
    assert transport.calls == 1
    assert not gate.decide({**meta, "model": "other-model"}).allowed


def test_manual_selection_rejects_paid_and_unbound_routes(tmp_path):
    gate, settings, _ = environment(tmp_path)
    meta = settings.registry.credential("llm:groq:test")
    for change in (
        {"tier": "PAID"}, {"model": "openrouter/free"},
        {"model": "model-latest"}, {"endpoint": "http://example.test"},
        {"binding": ""}, {"provider": ""},
    ):
        with pytest.raises(ValueError):
            gate.select({**meta, **change})
    with pytest.raises(ValueError, match="INVALID_MANUAL_SCOPE"):
        gate.select(meta, account_alias="known", project_alias="")
    assert not gate.decide(meta).allowed


def test_legacy_receipt_table_is_not_a_manual_selection(tmp_path):
    import sqlite3
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE free_route_receipts(binding TEXT PRIMARY KEY)")
        db.execute("INSERT INTO free_route_receipts VALUES('a')")
    gate = SQLiteFreeRouteAdmission(path)
    meta = {"binding": "a", "provider": "GROQ", "tier": "FREE",
            "endpoint": "https://example.test/v1", "model": "fixed-model"}
    assert gate.decide(meta).reason == "NOT_MANUALLY_SELECTED"


def test_manual_selection_survives_time_but_identity_drift_and_revoke_block(tmp_path):
    now = [1000]
    gate = SQLiteFreeRouteAdmission(tmp_path / "gate.db", clock=lambda: now[0])
    meta = {
        "binding": "a", "provider": "GROQ", "tier": "FREE",
        "endpoint": "https://example.test/v1", "model": "fixed-model",
        "protocol": "openai-chat",
    }
    select(gate, meta)
    assert gate.decide(meta).allowed
    assert gate.decide({**meta, "endpoint": "https://another.example.test"}).reason == "ROUTE_IDENTITY_CHANGED"
    now[0] = 1400
    assert gate.decide(meta).allowed
    now[0] = 1000
    gate.revoke("a")
    assert gate.decide(meta).reason == "NOT_MANUALLY_SELECTED"


def test_replacing_credential_revokes_previous_billing_attestation(tmp_path):
    gate, settings, secrets = environment(tmp_path)
    meta = settings.registry.credential("llm:groq:test")
    select(gate, meta)
    assert gate.decide(meta).allowed
    settings.replace_provider_credential(meta["binding"], "different-secret")
    assert gate.decide(settings.registry.credential(meta["binding"])).reason == "NOT_MANUALLY_SELECTED"


def test_original_research_ledger_is_never_a_grant():
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    inventory = json.loads((root / "docs/data/free_ai_route_candidates_20261109.json").read_text())
    services = inventory["services"]
    assert len(services) == 42
    assert len({x["id"] for x in services}) == 42
    assert inventory["deployment_state"] == "RESEARCH_ONLY"
    assert all(x["enabled"] is False and x["live_account_billing_verified"] is False
               for x in services)


def test_no_charge_receipt_not_probe_health_controls_billing(tmp_path):
    gate, settings, secrets = environment(tmp_path)
    binding = "llm:groq:test"
    meta = settings.registry.credential(binding)
    select(gate, meta)
    transport = Transport()
    execution = ObservedCloudExecution(
        settings.registry, secrets,
        ProviderResponseObserver(settings.registry), transport, admission=gate)
    settings.registry.observe(binding, health="UNVERIFIED")
    execution.invoke(binding, {"model": meta["model"], "messages": []})
    assert secrets.loads == 1 and transport.calls == 1
    gate.revoke(binding)
    with pytest.raises(PermissionError, match="NOT_MANUALLY_SELECTED"):
        execution.invoke(binding, {"model": meta["model"], "messages": []})
    assert secrets.loads == 1 and transport.calls == 1


def test_manual_free_service_selection_never_needs_calendar_renewal(tmp_path):
    now = [1_000_000.0]
    gate = SQLiteFreeRouteAdmission(tmp_path / "monthly.sqlite", clock=lambda: now[0])
    meta = {"binding": "verified", "provider": "GROQ", "tier": "FREE",
            "endpoint": "https://example.test/v1", "model": "pinned-v1"}
    select(gate, meta)
    now[0] += 8 * 24 * 3600
    assert gate.decide(meta).allowed
    now[0] += 22 * 24 * 3600
    assert gate.decide(meta).allowed


@pytest.mark.parametrize("alias", [
    "openrouter/auto", "openrouter/latest", "provider/free",
    "PROVIDER/AUTO", "provider/model:auto", "provider/model:latest",
    "provider/model@auto", "provider/model@latest",
    "openrouter/auto:free", "openrouter/latest:free",
    "openrouter/free:free", "kilo-auto/free:free",
    "provider/model:latest:free", "provider/model@auto:free",
])
def test_namespaced_dynamic_alias_never_enters_manual_free_registry(tmp_path, alias):
    gate, settings, secrets = environment(tmp_path)
    meta = settings.registry.credential("llm:groq:test")
    alias_meta = {**meta, "model": alias}
    with pytest.raises(ValueError, match="INVALID_MANUAL_FREE_ROUTE"):
        gate.select(alias_meta)
    assert gate.decide(alias_meta).reason == "DYNAMIC_OR_UNBOUND_MODEL"
    assert secrets.loads == 0


def test_old_namespaced_auto_selection_is_ineligible_without_new_model_admission(tmp_path):
    import sqlite3
    gate, settings, _ = environment(tmp_path)
    meta = settings.registry.credential("llm:groq:test")
    # Existing DB selections predate the alias block. Reading them must not
    # silently activate a provider-controlled paid fallback model.
    with sqlite3.connect(gate.path) as db:
        db.execute("""INSERT INTO manually_selected_free_routes
            (binding,provider,endpoint,model,account_alias,project_alias)
            VALUES (?,?,?,?,?,?)""",
            (meta["binding"], meta["provider"], meta["endpoint"],
             "openrouter/auto", "", ""))
    assert gate.decide({**meta, "model": "openrouter/auto"}).reason == "DYNAMIC_OR_UNBOUND_MODEL"
    assert not gate.decide(meta).allowed
    # Exact, fixed-model manual selection remains possible without changes
    # to provider discovery, budget refresh, Guard or model ranking.
    gate.select({**meta, "model": "qwen/qwen3-32b:free"})
    assert gate.decide({**meta, "model": "qwen/qwen3-32b:free"}).allowed


@pytest.mark.parametrize("tools", [
    [{"type": "web_search_preview"}],
    [{"type": "file_search"}],
    [{"type": "computer_use_preview"}],
    [{"type": "image_generation"}],
    [{"type": "browser_search"}],
    [{"type": "code_interpreter"}],
    {"type": "web_search_preview"},
    "web_search_preview",
    ["web_search_preview"],
    [{"type": "function"}, {"type": "web_search_preview"}],
])
def test_free_route_rejects_unpriced_builtins_and_malformed_tools_before_send(tmp_path, tools):
    gate, settings, secrets = environment(tmp_path)
    meta = settings.registry.credential("llm:groq:test")
    select(gate, meta)
    transport = Transport()
    executor = ObservedCloudExecution(
        settings.registry, secrets,
        ProviderResponseObserver(settings.registry), transport, admission=gate)
    with pytest.raises(PermissionError, match="UNPRICED_PROVIDER_TOOLS"):
        executor.invoke(meta["binding"], {"model": meta["model"], "tools": tools})
    assert secrets.loads == 0
    assert transport.calls == 0


def test_free_route_preserves_only_host_defined_function_tools(tmp_path):
    gate, settings, secrets = environment(tmp_path)
    meta = settings.registry.credential("llm:groq:test")
    select(gate, meta)
    gate.require(meta, {"model": meta["model"], "tools": [{
        "type": "function", "function": {"name": "bounded_tool"}
    }]})
    gate.require(meta, {"model": meta["model"], "tools": []})


@pytest.mark.parametrize("extension", [
    {"web_search_options": {"search_context_size": "low"}},
    {"audio": {"voice": "alloy", "format": "wav"}},
    {"modalities": ["text", "audio"]},
    {"prediction": {"type": "content", "content": "candidate"}},
    {"image_generation": {}},
    {"file_search": {}},
    {"video": {}},
    {"response_modalities": ["audio"]},
    {"provider_options": {"tool": "paid-preview"}},
])
def test_free_route_rejects_top_level_metered_features_before_secret_or_send(
        tmp_path, extension):
    gate, settings, secrets = environment(tmp_path)
    meta = settings.registry.credential("llm:groq:test")
    select(gate, meta)
    transport = Transport()
    executor = ObservedCloudExecution(
        settings.registry, secrets,
        ProviderResponseObserver(settings.registry), transport, admission=gate)
    with pytest.raises(PermissionError, match="UNPRICED_PROVIDER_FEATURE"):
        executor.invoke(meta["binding"], {
            "model": meta["model"], "messages": [], **extension})
    assert secrets.loads == 0
    assert transport.calls == 0



def test_groq_native_function_tools_pass_admission_only_via_boundary(tmp_path):
    gate, settings, secrets = environment(tmp_path)
    meta = settings.registry.credential("llm:groq:test")
    select(gate, meta)
    transport = Transport()
    execution = ObservedCloudExecution(
        settings.registry, secrets,
        ProviderResponseObserver(settings.registry), transport, admission=gate)
    execution.invoke_for_function(meta["binding"], {"messages": [{"role": "user", "content": "q"}]}, "SEARCH")
    assert transport.calls == 1
    execution.invoke_for_function(meta["binding"], {"messages": [{"role": "user", "content": "q"}]}, "DATA")
    assert transport.calls == 2
    with pytest.raises(PermissionError, match="UNPRICED_PROVIDER_TOOLS"):
        execution.invoke(meta["binding"], {
            "model": meta["model"], "tools": [{"type": "browser_search"}]})
    assert transport.calls == 2
