"""Service-first view: API keys are subordinate, model approval is scoped."""
import pytest
from ai_foundation.provider_registry import SQLiteProviderRegistry
from ai_foundation.provider_service_view import service_inventory
from ai_foundation.free_route_admission import SQLiteFreeRouteAdmission
from ai_foundation.settings_service import SettingsService


class Secrets:
    def __init__(self, present):
        self.present = set(present)

    def available(self, binding):
        return binding in self.present


def select(gate, meta, *, account="shared-account", project="project-1"):
    gate.select(meta, account_alias=account, project_alias=project)


def test_service_groups_accepted_keys_by_verified_account_project_not_key(tmp_path):
    registry = SQLiteProviderRegistry(tmp_path / "providers.sqlite")
    for binding, model in (("key-g1", "model-1"), ("key-g2", "model-2"),
                           ("key-g3", "model-3")):
        registry.upsert(binding, "GROQ", tier="FREE", health="ONLINE",
                        endpoint="https://api.groq.com/v1", model=model,
                        protocol="openai-chat", capabilities=("CHAT",))
    registry.upsert("key-m", "MISTRAL", tier="PAID", health="ONLINE",
                    endpoint="https://api.mistral.ai/v1",
                    model="paid-model", capabilities=("CHAT",))
    gate = SQLiteFreeRouteAdmission(tmp_path / "gate.sqlite", clock=lambda: 1000)
    select(gate, registry.credential("key-g1"))
    select(gate, registry.credential("key-g2"))
    secrets = Secrets({"key-g1", "key-g2", "key-g3", "key-m"})
    rows = service_inventory(registry.credentials(), gate, secrets.available)
    assert [s.provider for s in rows] == ["GROQ", "MISTRAL"]
    groq = rows[0]
    assert groq.credentials == 3 and groq.approved_connections == 2
    assert len(groq.accounts) == 2
    approved_account = next(a for a in groq.accounts if a.identity_verified)
    assert len(approved_account.projects) == 1
    approved_project = approved_account.projects[0]
    assert approved_project.identity_verified
    assert {c.models for c in approved_project.credentials} == {
        ("model-1",), ("model-2",)}
    assert all(c.approved_for_model for c in approved_project.credentials)
    unknown = next(a for a in groq.accounts if not a.identity_verified)
    assert len(unknown.projects[0].credentials) == 1
    assert unknown.projects[0].credentials[0].admission_reason == "NOT_MANUALLY_SELECTED"
    assert rows[1].approved_connections == 0
    assert "key-g1" not in repr(rows) and "key-g2" not in repr(rows)
    assert "shared-account" not in repr(rows) and "project-1" not in repr(rows)


def test_same_service_different_verified_projects_are_kept_separate(tmp_path):
    registry = SQLiteProviderRegistry(tmp_path / "p.sqlite")
    gate = SQLiteFreeRouteAdmission(tmp_path / "g.sqlite", clock=lambda: 1000)
    for name, project in (("k1", "one"), ("k2", "two")):
        registry.upsert(name, "GROQ", "FREE", "ONLINE",
                        endpoint="https://api.groq.com/v1", model="model-1",
                        capabilities=("CHAT",))
        select(gate, registry.credential(name), project=project)
    row = service_inventory(registry.credentials(), gate, Secrets(["k1", "k2"]).available)[0]
    assert len(row.accounts) == 1
    assert len(row.accounts[0].projects) == 2
    assert row.approved_connections == 2
    gate.revoke("k2")
    after = service_inventory(registry.credentials(), gate, Secrets(["k1", "k2"]).available)[0]
    assert after.approved_connections == 1
    assert len(after.accounts) == 2
    assert sum(not a.identity_verified for a in after.accounts) == 1


def test_missing_key_unverified_and_paid_never_claim_executable(tmp_path):
    registry = SQLiteProviderRegistry(tmp_path / "p.sqlite")
    registry.upsert("g", "GROQ", "FREE", "ONLINE",
                    endpoint="https://api.groq.com/v1", model="m", capabilities=("CHAT",))
    registry.upsert("paid", "GROQ", "PAID", "ONLINE",
                    endpoint="https://api.groq.com/v1", model="m", capabilities=("CHAT",))
    gate = SQLiteFreeRouteAdmission(tmp_path / "g.sqlite", clock=lambda: 1000)
    select(gate, registry.credential("g"))
    view = service_inventory(registry.credentials(), gate, Secrets([]).available)[0]
    assert view.credentials == 2
    assert view.approved_connections == 0
    states = [c for a in view.accounts for p in a.projects for c in p.credentials]
    assert all(not c.stored and not c.approved_for_model for c in states)
    assert all(c.admission_reason == "CREDENTIAL_MISSING" for c in states)


def test_settings_service_exposes_service_view_without_additional_registry(tmp_path):
    class Probe: pass
    class Sec:
        def available(self, key):
            return True
    settings = SettingsService(tmp_path, Probe(), Sec())
    settings.registry.upsert("hidden-binding", "GROQ", "FREE", "UNVERIFIED",
                             endpoint="https://api.groq.com/v1", model="model-1")
    services = settings.services()
    assert len(services) == 1
    assert services[0].provider == "GROQ"
    assert services[0].credentials == 1
    assert services[0].approved_connections == 0
    assert "hidden-binding" not in repr(services)


def test_harness_service_state_blocks_unapproved_free_and_paid(tmp_path):
    class Probe: pass
    class Sec:
        def available(self, binding):
            return binding == "groq-free"
    gate = SQLiteFreeRouteAdmission(tmp_path / "free.sqlite", clock=lambda: 1000)
    settings = SettingsService(tmp_path / "runtime", Probe(), Sec(), free_route=gate)
    from ai_foundation.provider_catalog import spec
    meta = spec("GROQ")
    settings.registry.upsert(
        "groq-free", "GROQ", "FREE", "UNVERIFIED",
        endpoint=meta.endpoint, model=meta.model,
        protocol=meta.protocol, capabilities=meta.capabilities)
    settings.registry.upsert(
        "groq-paid", "GROQ", "PAID", "ONLINE",
        endpoint=meta.endpoint, model=meta.model,
        protocol=meta.protocol, capabilities=meta.capabilities)
    data = settings.harness_service_status()
    assert data["manager"] == "FOUNDATION_HARNESS"
    assert data["state"] == "HOLD_NO_APPROVED_FREE_CONNECTION"
    assert data["free_credentials"] == 1
    assert data["account_admitted_connections"] == 0
    assert data["live_deployment_confirmed"] is False
    assert "groq-free" not in repr(data)

    select(gate, settings.registry.credential("groq-free"))
    # Status reports a no-charge approved connection even without a
    # redundant /models connectivity probe; runtime errors remain observable.
    state = settings.harness_service_status()
    assert state["account_admitted_connections"] == 1
    assert state["state"] == "ACCOUNT_ADMITTED_HOST_REVIEW_STILL_REQUIRED"

    gate.revoke("groq-free")
    assert settings.harness_service_status()["account_admitted_connections"] == 0


def test_harness_inventory_shows_new_service_before_adapter_approval(tmp_path):
    from ai_foundation.harness_service_registry import (
        HarnessServiceAdapter, HarnessServiceRegistry,
    )
    from ai_foundation.provider_catalog import spec
    class Probe: pass
    class Native:
        def available(self, binding):
            return True
    gate = SQLiteFreeRouteAdmission(tmp_path / "free.sqlite", clock=lambda:1000)
    settings = SettingsService(
        tmp_path / "runtime", Probe(), Native(), free_route=gate)
    for name in ("GROQ", "NVIDIA"):
        p = spec(name)
        settings.registry.upsert(
            "key:" + name.lower(), name, "FREE", "ONLINE",
            endpoint=p.endpoint, model=p.model,
            capabilities=p.capabilities, protocol=p.protocol)
    select(gate, settings.registry.credential("key:nvidia"))
    before = settings.harness_services_status()
    states = {x["service"]: x for x in before["services"]}
    assert states["GROQ"]["state"] == "HOLD_NO_APPROVED_FREE_CONNECTION"
    assert states["NVIDIA"]["state"] == "ADAPTER_REQUIRED"
    assert not states["NVIDIA"]["adapter_installed"]
    assert states["NVIDIA"]["account_admitted_connections"] == 0
    assert before["default_fallback"] == "LOCAL_HARNESS_9B"
    assert not before["runtime_enabled"]
    assert "key:nvidia" not in repr(before)

    p = spec("NVIDIA")
    adapters = HarnessServiceRegistry((
        HarnessServiceAdapter("NVIDIA", p.model, p.endpoint, lambda: object()),
    ))
    after = settings.harness_services_status(adapters)
    states = {x["service"]: x for x in after["services"]}
    assert states["NVIDIA"]["state"] == "ACCOUNT_ADMITTED_HOST_REVIEW_STILL_REQUIRED"
    assert states["NVIDIA"]["account_admitted_connections"] == 1
    assert states["GROQ"]["state"] == "ADAPTER_REQUIRED"
    gate.revoke("key:nvidia")
    denied = settings.harness_services_status(adapters)
    assert next(x for x in denied["services"] if x["service"] == "NVIDIA")[
        "account_admitted_connections"] == 0


def test_harness_status_includes_research_candidates_without_any_credentials(tmp_path):
    class Probe: pass
    class Native:
        def available(self, binding):
            raise AssertionError("a research-only candidate has no key")
    settings = SettingsService(
        tmp_path / "runtime", Probe(), Native(),
        free_route=SQLiteFreeRouteAdmission(tmp_path / "free.sqlite"))
    research = {
        "deployment_state": "RESEARCH_ONLY",
        "services": [
            {"id": "opencode-console-free", "name": "OpenCode Console Free",
             "route_kind": "AGENT_WITH_GATEWAY", "assessment": "PROBE",
             "enabled": False},
            {"id": "jules", "name": "Google Jules",
             "route_kind": "CLOUD_DEVELOPMENT_SERVICE",
             "assessment": "PROBE", "enabled": False},
        ],
    }
    status = settings.harness_services_status(research_ledger=research)
    assert status["research_loaded"] is True
    names = {x["service_id"] for x in status["research_candidates"]}
    assert names == {"opencode-console-free", "jules"}
    assert all(x["execution_authorized"] is False
               for x in status["research_candidates"])
    assert all(x["connection_state"] == "NOT_CONNECTED"
               for x in status["research_candidates"])
    assert all(x["billing_state"] == "NOT_ADMITTED"
               for x in status["research_candidates"])
    assert "opencode-console-free" not in {
        x["service"] for x in status["services"]}
    assert status["runtime_enabled"] is False
    assert settings.harness_services_status()["research_loaded"] is False

    research["services"][0]["enabled"] = True
    with pytest.raises(ValueError, match="RESEARCH_LEDGER_MUST_NOT_ENABLE_EXECUTION"):
        settings.harness_services_status(research_ledger=research)


def test_operator_harness_preflight_shows_next_cli_remote_services_without_grants(tmp_path):
    from ai_foundation.next_service_preflight import (
        SERVICE_OPEN_CODE, SERVICE_JULES,
    )
    class NoNetwork:
        def available(self, binding):
            raise AssertionError("Research preflight must not read Keychain")
    class Probe:
        def probe(self, *_):
            raise AssertionError("Research preflight must not contact network")
    settings = SettingsService(
        tmp_path / "runtime", Probe(), NoNetwork(),
        free_route=SQLiteFreeRouteAdmission(tmp_path / "free.sqlite"))
    research = {
        "deployment_state": "RESEARCH_ONLY",
        "default_route_enabled": False,
        "services": [
            {"id": SERVICE_OPEN_CODE, "name": "OpenCode Console Free models",
             "route_kind": "AGENT_WITH_GATEWAY", "assessment": "PROBE",
             "enabled": False},
            {"id": SERVICE_JULES, "name": "Google Jules",
             "route_kind": "CLOUD_DEVELOPMENT_SERVICE",
             "assessment": "PROBE", "enabled": False},
        ],
    }
    state = settings.harness_services_status(research_ledger=research)
    blocked = {x["service"]: x for x in state["candidate_preflights"]}
    # The legacy Jules research row is retired, not an execution candidate.
    assert set(blocked) == {SERVICE_OPEN_CODE}
    assert all(x["stage"] == "HOLD_UNVERIFIED" for x in blocked.values())
    assert all(not x["execution_authorized"] for x in blocked.values())
    assert blocked[SERVICE_OPEN_CODE]["candidate_model"].endswith("-free")
    assert not state["runtime_enabled"]
    assert settings.harness_services_status()["candidate_preflights"] == []
