"""Issue #223: ownership-only, source-only 9B admission proposal.

Host RAM, page counters, swap and model-size thresholds are intentionally
absent. This function cannot launch a model or confer effect authority.
Trusted runtime host/process ownership and exclusive lease must be verified
by an independent service before any effectful invocation.
"""
from __future__ import annotations
from dataclasses import dataclass
import re

MAX_AGE_MS = 5_000
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class Resident:
    model_id: str
    owner: str  # COOPERATING / EXTERNAL / UNKNOWN


@dataclass(frozen=True)
class Evidence:
    captured_at_ms: int
    checked_at_ms: int
    endpoints_verified: bool
    lock_held: bool
    job_scope_verified: bool
    runner_uids_coordinated: bool
    runner_uid: int
    lease_uid: int
    other_ci_active: bool
    shared_ollama_clients: str  # NONE / ACTIVE / UNKNOWN
    residents: tuple[Resident, ...]


@dataclass(frozen=True)
class Request:
    alias: str
    bound_alias: str
    expected_digest: str
    observed_digest: str
    required_role: str
    host_roles: frozenset[str]
    provider: str  # LOCAL_ONLY


def assess(request: Request, evidence: Evidence) -> dict:
    """Identity/client exclusion precheck, never RAM admission or launch."""
    def verdict(status: str, reason: str) -> dict:
        return {
            "schema": "issue223-source-only-owner-admission/v2",
            "status": status,
            "reason": reason,
            "effect_authorized": False,
            "model_calls": 0,
            "model_alias": request.alias if isinstance(request, Request) else None,
            "resident_count": len(evidence.residents)
                              if isinstance(evidence, Evidence)
                              and type(evidence.residents) is tuple else None,
            "warning": "Ownership precheck only; cannot reserve resources or launch a model.",
        }
    invalid = lambda reason: verdict("INVALID_OWNERSHIP_EVIDENCE", reason)
    if not isinstance(request, Request) or not isinstance(evidence, Evidence):
        return invalid("WRONG_EVIDENCE_TYPE")
    nums = (evidence.captured_at_ms, evidence.checked_at_ms,
            evidence.runner_uid, evidence.lease_uid)
    if any(type(v) is not int or v < 0 for v in nums):
        return invalid("INVALID_NUMERIC_EVIDENCE")
    if (evidence.checked_at_ms < evidence.captured_at_ms
            or evidence.checked_at_ms - evidence.captured_at_ms > MAX_AGE_MS):
        return invalid("STALE_OR_NONMONOTONIC_EVIDENCE")
    flags = (evidence.endpoints_verified, evidence.lock_held,
             evidence.job_scope_verified, evidence.runner_uids_coordinated,
             evidence.other_ci_active)
    if not all(type(v) is bool for v in flags):
        return invalid("INVALID_BOOLEAN_EVIDENCE")
    if not evidence.endpoints_verified:
        return invalid("ENDPOINT_STATE_UNVERIFIED")
    if (type(request.alias) is not str or not request.alias
            or type(request.bound_alias) is not str or request.alias != request.bound_alias
            or type(request.expected_digest) is not str
            or not SHA256.fullmatch(request.expected_digest)
            or type(request.observed_digest) is not str
            or request.expected_digest != request.observed_digest
            or type(request.required_role) is not str or not request.required_role
            or type(request.host_roles) is not frozenset
            or request.required_role not in request.host_roles
            or not all(type(v) is str and v for v in request.host_roles)
            or request.provider != "LOCAL_ONLY"):
        return invalid("MODEL_IDENTITY_OR_ROLE_UNVERIFIED")
    if (evidence.shared_ollama_clients not in ("NONE", "ACTIVE", "UNKNOWN")
            or type(evidence.residents) is not tuple
            or any(not isinstance(v, Resident)
                   or type(v.model_id) is not str or not v.model_id
                   or v.owner not in ("COOPERATING", "EXTERNAL", "UNKNOWN")
                   for v in evidence.residents)):
        return invalid("INVALID_CLIENT_RESIDENCY_INVENTORY")
    ids = [v.model_id for v in evidence.residents]
    if len(ids) != len(set(ids)):
        return invalid("DUPLICATE_RESIDENT_ID")
    if not evidence.lock_held or evidence.other_ci_active:
        return verdict("DEFER_RESOURCE_BUSY", "LEASE_OR_CI_BUSY")
    if (not evidence.job_scope_verified
            or not evidence.runner_uids_coordinated
            or evidence.runner_uid != evidence.lease_uid
            or evidence.shared_ollama_clients != "NONE"
            or any(v.owner != "COOPERATING" for v in evidence.residents)):
        return verdict("DEFER_UNCOORDINATED_CLIENT", "UNCOORDINATED_HOST_PARTICIPANT")
    return verdict("ADMIT", "OWNER_PRECHECK_PASSED_NO_EFFECT")
