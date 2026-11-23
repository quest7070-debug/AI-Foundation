"""Fail-closed provider onboarding: no billing probe without prior approval."""
from ai_foundation.free_route_admission import SQLiteFreeRouteAdmission
from ai_foundation.settings_service import SettingsService


class NativeSecrets:
    def __init__(self):
        self.items = {}

    def available(self, binding):
        return binding in self.items

    def save(self, binding, secret):
        self.items[binding] = secret

    def load(self, binding):
        return self.items[binding]

    def delete(self, binding):
        return self.items.pop(binding, None) is not None


class MustNotProbe:
    def probe(self, *_args, **_kwargs):
        raise AssertionError("BILLABLE_PROVIDER_PROBE_FORBIDDEN")


def setup(tmp_path):
    gate = SQLiteFreeRouteAdmission(tmp_path / "grant.sqlite", clock=lambda: 1000)
    keys = NativeSecrets()
    settings = SettingsService(tmp_path / "runtime", MustNotProbe(), keys, free_route=gate)
    return settings, keys, gate


def test_add_external_provider_registers_service_without_any_network_or_route(tmp_path):
    settings, keys, gate = setup(tmp_path)
    response = settings.add_provider("gsk_" + "A" * 24, "GROQ", "FREE")
    assert response["provider"] == "GROQ"
    assert response["health"] == "UNVERIFIED"
    rows = settings.credentials()
    assert len(rows) == 1
    row = rows[0]
    assert row["tier"] == "FREE"
    assert row["model"] == "openai/gpt-oss-20b"
    assert keys.available(row["binding"])
    assert settings.choose_route("CHAT") is None
    assert gate.decide(row).reason == "NOT_MANUALLY_SELECTED"
    assert settings.services()[0].approved_connections == 0


def test_refresh_unattested_never_invokes_probe(tmp_path):
    settings, keys, gate = setup(tmp_path)
    settings.add_provider("gsk_" + "A" * 24, "GROQ", "FREE")
    row = settings.credentials()[0]
    result = settings.refresh_provider(row["binding"])
    assert result["health"] == "UNVERIFIED"
    assert result["reason"] == "NOT_MANUALLY_SELECTED"
    assert settings.choose_route("CHAT") is None


def test_key_rotation_revokes_service_approval_without_network(tmp_path):
    settings, keys, gate = setup(tmp_path)
    settings.add_provider("gsk_" + "A" * 24, "GROQ", "FREE")
    meta = settings.credentials()[0]
    gate.select(meta, account_alias="account-fixture",
                project_alias="project-fixture")
    assert gate.decide(meta).allowed
    result = settings.replace_provider_credential(meta["binding"], "gsk_" + "B" * 24)
    assert result["health"] == "UNVERIFIED"
    assert gate.decide(settings.registry.credential(meta["binding"])).reason == "NOT_MANUALLY_SELECTED"
    assert keys.load(meta["binding"]) == "gsk_" + "B" * 24
    assert settings.choose_route("CHAT") is None


def test_unverified_paid_credential_never_becomes_a_usable_route(tmp_path):
    settings, keys, gate = setup(tmp_path)
    result = settings.add_provider("gsk_" + "C" * 24, "GROQ", "PAID")
    assert result["health"] == "UNVERIFIED"
    assert settings.choose_route("CHAT") is None
    assert gate.decide(settings.credentials()[0]).reason == "NOT_FREE_TIER"
