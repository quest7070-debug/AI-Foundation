"""Issue #223: offline observation-envelope verifier; not runtime authority.

No network, host probes, model calls, key generation or key storage. The key and
expected context MUST be supplied by a trusted host component in a later PR.
A valid HMAC proves integrity relative to that key, NOT the truth of sensors,
model residency, lease ownership or job-wide exclusivity.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import hmac
import json
import re

MAX_ENVELOPE_BYTES = 65536
MAX_AGE_MS = 5000
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class TrustedContext:
    host_id: str
    boot_id: str
    job_id: str
    request_nonce: str
    source_sha: str
    lock_dev: int
    lock_ino: int
    lock_uid: int
    now_monotonic_ms: int


def canonical_bytes(value: object) -> bytes:
    """Strict deterministic encoding; no NaN, tuples, or implicit coercions."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def verify_envelope(envelope: object, mac_hex: object, key: object,
                    trusted: TrustedContext) -> dict:
    """Verify offline binding only. Always returns effect_authorized=False."""
    def deny(reason):
        return {"schema": "issue223-binding-verification/v1",
                "status": "INVALID_OWNERSHIP_EVIDENCE", "reason": reason,
                "binding_verified": False, "effect_authorized": False,
                "model_calls": 0}

    if (not isinstance(trusted, TrustedContext) or
            any(type(v) is not str or not v for v in
                (trusted.host_id, trusted.boot_id, trusted.job_id)) or
            type(trusted.request_nonce) is not str or
            not HEX64.fullmatch(trusted.request_nonce) or
            type(trusted.source_sha) is not str or
            not HEX40.fullmatch(trusted.source_sha) or
            any(type(v) is not int or v < 0 for v in
                (trusted.lock_dev, trusted.lock_ino, trusted.lock_uid,
                 trusted.now_monotonic_ms)) or
            trusted.lock_dev == 0 or trusted.lock_ino == 0):
        return deny("INVALID_TRUSTED_CONTEXT")
    if (type(key) is not bytes or len(key) < 32 or
            type(mac_hex) is not str or not HEX64.fullmatch(mac_hex)):
        return deny("INVALID_ATTESTATION_INPUT")
    if type(envelope) is not dict:
        return deny("INVALID_ENVELOPE_TYPE")
    try:
        raw = canonical_bytes(envelope)
    except (TypeError, ValueError, OverflowError, UnicodeEncodeError, RecursionError):
        return deny("UNENCODABLE_ENVELOPE")
    if len(raw) > MAX_ENVELOPE_BYTES:
        return deny("ENVELOPE_TOO_LARGE")
    signature = hmac.new(key, raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, mac_hex):
        return deny("ATTESTATION_MISMATCH")
    if (set(envelope) != {"schema", "context", "request", "evidence"} or
            envelope.get("schema") != "issue223-observation-envelope/v2"):
        return deny("INVALID_ENVELOPE_SCHEMA")
    ctx = envelope.get("context")
    if type(ctx) is not dict or set(ctx) != {
            "host_id", "boot_id", "job_id", "request_nonce", "source_sha", "lock_dev",
            "lock_ino", "lock_uid", "observed_at_monotonic_ms"}:
        return deny("INVALID_OBSERVATION_CONTEXT")
    expected = {"host_id": trusted.host_id, "boot_id": trusted.boot_id, "job_id": trusted.job_id,
                "request_nonce": trusted.request_nonce,
                "source_sha": trusted.source_sha, "lock_dev": trusted.lock_dev,
                "lock_ino": trusted.lock_ino, "lock_uid": trusted.lock_uid}
    if any(type(ctx.get(k)) is not type(v) or ctx.get(k) != v
           for k, v in expected.items()):
        return deny("CROSS_CONTEXT_REPLAY_OR_LOCK_MISMATCH")
    observed = ctx.get("observed_at_monotonic_ms")
    if (type(observed) is not int or observed < 0 or
            observed > trusted.now_monotonic_ms or
            trusted.now_monotonic_ms - observed > MAX_AGE_MS):
        return deny("EXPIRED_OR_FUTURE_OBSERVATION")
    request = envelope.get("request")
    evidence = envelope.get("evidence")
    # Exact allowlists mirror ownership-only proposal.py; no RAM/page/swap data.
    if type(request) is not dict or set(request) != {
            "alias", "bound_alias", "expected_digest", "observed_digest",
            "required_role", "host_roles", "provider"}:
        return deny("INVALID_REQUEST_SHAPE")
    if type(evidence) is not dict or set(evidence) != {
            "captured_at_ms", "checked_at_ms", "endpoints_verified", "lock_held",
            "job_scope_verified", "runner_uids_coordinated", "runner_uid",
            "lease_uid", "other_ci_active", "shared_ollama_clients", "residents"}:
        return deny("INVALID_EVIDENCE_SHAPE")
    if (type(evidence["checked_at_ms"]) is not int or
            evidence["checked_at_ms"] != observed or
            type(evidence["runner_uid"]) is not int or
            evidence["runner_uid"] != trusted.lock_uid or
            type(evidence["lease_uid"]) is not int or
            evidence["lease_uid"] != trusted.lock_uid):
        return deny("EVIDENCE_CLOCK_OR_UID_MISMATCH")
    if (type(request["host_roles"]) is not list or
            not all(type(x) is str and x for x in request["host_roles"]) or
            len(request["host_roles"]) != len(set(request["host_roles"])) or
            type(evidence["residents"]) is not list or len(evidence["residents"]) > 64 or
            any(type(x) is not dict or set(x) != {"model_id", "owner"}
                for x in evidence["residents"])):
        return deny("INVALID_NESTED_EVIDENCE_SHAPE")
    # Hash is an audit locator, not proof of provenance on its own.
    return {"schema": "issue223-binding-verification/v1",
            "status": "VERIFIED_OFFLINE_BINDING_ONLY",
            "reason": "INTEGRITY_AND_CONTEXT_MATCH_NO_SENSOR_OR_LEASE_ATTESTATION",
            "binding_verified": True,
            "payload_sha256": hashlib.sha256(raw).hexdigest(),
            "effect_authorized": False, "model_calls": 0}
