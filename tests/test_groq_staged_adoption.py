"""Groq staged native-key adoption is no-network, non-executable and idempotent."""
from dataclasses import dataclass

from ai_foundation.groq_staged_adoption import (
    STAGED, MANAGED, adopt_staged_groq, verify_managed_groq_ipv4,
)
from ai_foundation.provider_catalog import spec
from ai_foundation.provider_registry import SQLiteProviderRegistry


KEY = "gsk_" + "A" * 32


@dataclass
class FakeNative:
    keys: dict

    def available(self, binding):
        return binding in self.keys

    def load(self, binding):
        return self.keys[binding]

    def save(self, binding, secret):
        self.keys[binding] = secret

    def delete(self, binding):
        self.keys.pop(binding, None)


def registry(tmp_path):
    return SQLiteProviderRegistry(tmp_path / "providers.sqlite")


def test_register_does_not_validate_using_python_network_or_grant_billing(tmp_path):
    db = registry(tmp_path)
    secret = FakeNative({STAGED: KEY})
    result = adopt_staged_groq(db, secret)
    assert result == {"state": "REGISTERED_UNVERIFIED_NO_INFERENCE", "wrote": True}
    assert secret.keys[STAGED] == KEY and secret.keys[MANAGED] == KEY
    row = db.credential(MANAGED)
    assert row["provider"] == "GROQ" and row["tier"] == "FREE"
    assert row["health"] == "UNVERIFIED" and not row["active"]
    assert row["endpoint"] == spec("GROQ").endpoint
    assert row["model"] == spec("GROQ").model
    assert row["reason"] == "ACCOUNT_BILLING_NOT_ATTESTED_NO_INFERENCE"
    assert KEY not in repr(row)
    assert KEY not in repr(result)
    assert len(db.credentials()) == 1
    assert adopt_staged_groq(db, secret) == {
        "state": "MANAGED_GROQ_ALREADY_REGISTERED", "wrote": False}
    assert len(db.credentials()) == 1


def test_never_adopt_wrong_key_or_overwrite_different_existing_key(tmp_path):
    db = registry(tmp_path)
    for staged in (None, "not a key", "gsk_!" + "A" * 32):
        native = FakeNative({} if staged is None else {STAGED: staged})
        result = adopt_staged_groq(db, native)
        assert result["wrote"] is False
        assert db.credentials() == ()
    native = FakeNative({STAGED: KEY, MANAGED: "gsk_" + "B" * 32})
    assert adopt_staged_groq(db, native) == {
        "state": "MANAGED_KEY_CONFLICT", "wrote": False}
    assert native.keys[MANAGED] == "gsk_" + "B" * 32
    assert db.credentials() == ()


def test_never_override_already_registered_real_groq_service(tmp_path):
    db = registry(tmp_path)
    db.upsert("llm:groq:other-account", "GROQ", "FREE", "ONLINE")
    native = FakeNative({STAGED: KEY})
    assert adopt_staged_groq(db, native) == {
        "state": "GROQ_FREE_ALREADY_REGISTERED", "wrote": False}
    assert MANAGED not in native.keys
    assert db.credential("llm:groq:other-account")["health"] == "ONLINE"


def test_existing_managed_binding_conflict_blocks_keychain_changes(tmp_path):
    db = registry(tmp_path)
    db.upsert(MANAGED, "NVIDIA", "FREE", "ONLINE")
    native = FakeNative({STAGED: KEY})
    assert adopt_staged_groq(db, native) == {
        "state": "EXISTING_ROUTE_IDENTITY_CONFLICT", "wrote": False}
    assert MANAGED not in native.keys


def test_partial_database_failure_cannot_leave_staged_key_erased(tmp_path):
    class FailingRegistry:
        def credential(self, binding):
            return None
        def credentials(self):
            return ()
        def upsert(self, *args, **kwargs):
            raise OSError("private error")
    native = FakeNative({STAGED: KEY})
    result = adopt_staged_groq(FailingRegistry(), native)
    assert result == {
        "state": "REGISTRATION_FAILED_NO_INFERENCE", "wrote": False}
    assert native.keys == {STAGED: KEY}
    assert KEY not in repr(result)


def test_hardcoded_staging_and_managed_dest_cannot_be_redirected(tmp_path):
    db = registry(tmp_path)
    native = FakeNative({STAGED: KEY})
    try:
        adopt_staged_groq(db, native, staging="secret:unrelated")
    except ValueError as exc:
        assert str(exc) == "GROQ_STAGING_BINDING_FIXED"
    else:
        raise AssertionError("should reject foreign Keychain alias")
    assert db.credentials() == ()


def test_readonly_service_report_never_exposes_native_key(tmp_path):
    from scripts.groq_register_staged_key import report
    db = registry(tmp_path)
    native = FakeNative({STAGED: KEY})
    first = report(db, native)
    assert first["registered"] is False
    assert first["staged_key_present"] is True
    assert first["manually_selected"] is False
    assert first["inference_calls"] == 0
    adopt_staged_groq(db, native)
    second = report(db, native)
    assert second["registered"] is True
    assert second["live_code_route_enabled"] is False
    assert not second["manually_selected"]
    assert KEY not in repr(second)


def test_one_verified_ipv4_models_get_changes_health_not_billing(tmp_path):
    from ai_foundation.harness_provider_adapter import default_harness_services
    class UntrustedBilling:
        def decide(self, meta):
            from types import SimpleNamespace
            return SimpleNamespace(allowed=False, reason="NOT_MANUALLY_SELECTED")
    db = registry(tmp_path)
    native = FakeNative({STAGED: KEY})
    assert adopt_staged_groq(db, native)["wrote"]
    transport_calls = []
    def approved_read_only(key):
        transport_calls.append(key)
        return {"status": "GROQ_KEY_ACCEPTED_IPV4", "http_status": 200}
    result = verify_managed_groq_ipv4(db, native, checker=approved_read_only)
    assert result == {
        "status": "GROQ_KEY_ACCEPTED_IPV4", "http_status": 200,
        "health_updated": True, "billing_verified": False,
        "inference_calls": 0}
    assert transport_calls == [KEY]
    assert db.credential(MANAGED)["health"] == "ONLINE"
    # Even after positive Keychain authentication, billing remains independent.
    assert not default_harness_services().admitted(
        db.credential(MANAGED), UntrustedBilling())


def test_failed_ipv4_verification_cannot_leave_previously_online_key_runnable(tmp_path):
    db = registry(tmp_path)
    native = FakeNative({STAGED: KEY})
    adopt_staged_groq(db, native)
    ok = verify_managed_groq_ipv4(db, native, checker=lambda _: {
        "status": "GROQ_KEY_ACCEPTED_IPV4", "http_status": 200})
    assert ok["health_updated"] and db.credential(MANAGED)["health"] == "ONLINE"
    fail = verify_managed_groq_ipv4(db, native, checker=lambda _: {
        "status": "GROQ_IPV4_NETWORK_ERROR", "http_status": None})
    assert fail["health_updated"] and db.credential(MANAGED)["health"] == "UNVERIFIED"
    assert fail["billing_verified"] is False
    limit = verify_managed_groq_ipv4(db, native, checker=lambda _: {
        "status": "GROQ_RATE_LIMITED_IPV4", "http_status": 429})
    assert limit["health_updated"]
    assert db.credential(MANAGED)["health"] == "RATE_LIMITED"


def test_empty_or_wrong_binding_never_triggers_provider_probe(tmp_path):
    db = registry(tmp_path)
    native = FakeNative({STAGED: KEY})
    calls = []
    result = verify_managed_groq_ipv4(db, native, checker=lambda _: calls.append(1))
    assert result["status"] == "GROQ_MANAGED_ROUTE_NOT_PINNED"
    assert calls == []


def test_staged_managed_probe_is_not_a_billing_attestation_even_after_manual_selection(tmp_path):
    from ai_foundation.free_route_admission import (
        SQLiteFreeRouteAdmission)
    db = registry(tmp_path)
    native = FakeNative({STAGED: KEY})
    adopt_staged_groq(db, native)
    row = db.credential(MANAGED)
    gate = SQLiteFreeRouteAdmission(tmp_path / "free.sqlite")
    # Fixture only: a human-selected binding, independent of the live Keychain.
    gate.select(row, account_alias="fixture-only",
                project_alias="fixture-only")
    from ai_foundation.harness_provider_adapter import default_harness_services
    assert gate.decide(row).allowed
    # Already manually selected Free accounts need not re-probe /models for billing.
    assert default_harness_services().admitted(row, gate)
    verify_managed_groq_ipv4(db, native, checker=lambda _: {
        "status": "GROQ_KEY_ACCEPTED_IPV4", "http_status": 200})
    assert default_harness_services().admitted(
        db.credential(MANAGED), gate)


def test_preexisting_paid_or_active_managed_record_never_passes_staging(tmp_path):
    for tier, active in (("PAID", False), ("FREE", True)):
        db = registry(tmp_path)
        pin = spec("GROQ")
        db.upsert(MANAGED, "GROQ", tier=tier, health="ONLINE",
                  active=active, endpoint=pin.endpoint, model=pin.model)
        native = FakeNative({STAGED: KEY, MANAGED: KEY})
        assert adopt_staged_groq(db, native) == {
            "state": "EXISTING_ROUTE_IDENTITY_CONFLICT", "wrote": False}
        assert db.credential(MANAGED)["tier"] == tier
        assert db.credential(MANAGED)["active"] is active
        db.remove(MANAGED)
