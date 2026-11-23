"""Focused v2 ownership-only envelope acceptance; no sensor or effect authority."""
import copy
from dataclasses import replace
import hashlib
import hmac

from experiments.m1_host_admission.bound_evidence import (
    TrustedContext, canonical_bytes, verify_envelope,
)

KEY = b"synthetic-owner-observation-key".ljust(40, b".")
NONCE = "a" * 64
SOURCE = "b" * 40


def evidence_fixture():
    owner = TrustedContext(
        "synthetic-m1", "synthetic-boot", "synthetic-job",
        NONCE, SOURCE, 24, 72, 501, 1100,
    )
    observation = {
        "schema": "issue223-observation-envelope/v2",
        "context": {
            "host_id": owner.host_id, "boot_id": owner.boot_id,
            "job_id": owner.job_id, "request_nonce": owner.request_nonce,
            "source_sha": owner.source_sha, "lock_dev": owner.lock_dev,
            "lock_ino": owner.lock_ino, "lock_uid": owner.lock_uid,
            "observed_at_monotonic_ms": 1000,
        },
        "request": {
            "alias": "local-general", "bound_alias": "local-general",
            "expected_digest": "c" * 64, "observed_digest": "c" * 64,
            "required_role": "CHAT", "host_roles": ["CHAT"],
            "provider": "LOCAL_ONLY",
        },
        "evidence": {
            "captured_at_ms": 900, "checked_at_ms": 1000,
            "endpoints_verified": True, "lock_held": True,
            "job_scope_verified": True, "runner_uids_coordinated": True,
            "runner_uid": 501, "lease_uid": 501,
            "other_ci_active": False, "shared_ollama_clients": "NONE",
            "residents": [],
        },
    }
    return owner, observation


def signed(observation, *, key=KEY):
    return hmac.new(key, canonical_bytes(observation), hashlib.sha256).hexdigest()


def check(owner, observation, *, key=KEY, tag=None):
    return verify_envelope(observation,
                           signed(observation, key=key) if tag is None else tag,
                           key, owner)


def test_pinned_v2_binds_only_integrity_not_effect_permission():
    owner, observation = evidence_fixture()
    result = check(owner, observation)
    assert result["status"] == "VERIFIED_OFFLINE_BINDING_ONLY"
    assert result["binding_verified"] is True
    assert result["effect_authorized"] is False
    assert result["model_calls"] == 0
    # A same-context replay is still a separate owner ledger responsibility.
    assert check(owner, observation)["status"] == "VERIFIED_OFFLINE_BINDING_ONLY"


def test_signature_and_source_owner_drift_fail_closed():
    owner, observation = evidence_fixture()
    signature = signed(observation)
    observation["evidence"]["lock_held"] = False
    assert check(owner, observation, tag=signature)["reason"] == "ATTESTATION_MISMATCH"
    owner, observation = evidence_fixture()
    result = check(replace(owner, host_id="other-host"), observation)
    assert result["status"] == "INVALID_OWNERSHIP_EVIDENCE"
    assert result["reason"] == "CROSS_CONTEXT_REPLAY_OR_LOCK_MISMATCH"
    assert result["effect_authorized"] is False


def test_v1_capacity_fields_cannot_bypass_v2_ownership_contract():
    owner, observation = evidence_fixture()
    observation["request"]["model_bytes"] = 2**30
    result = check(owner, observation)
    assert result["reason"] == "INVALID_REQUEST_SHAPE"
    assert result["effect_authorized"] is False
    owner, observation = evidence_fixture()
    observation["evidence"]["free_pages"] = 100000
    assert check(owner, observation)["reason"] == "INVALID_EVIDENCE_SHAPE"


def test_duplicate_roles_and_stale_attestation_denied():
    owner, observation = evidence_fixture()
    observation["request"]["host_roles"] = ["CHAT", "CHAT"]
    assert check(owner, observation)["reason"] == "INVALID_NESTED_EVIDENCE_SHAPE"
    owner, observation = evidence_fixture()
    assert check(replace(owner, now_monotonic_ms=7000), observation)["reason"] == "EXPIRED_OR_FUTURE_OBSERVATION"
    assert check(owner, observation, key=b"short")["reason"] == "INVALID_ATTESTATION_INPUT"
