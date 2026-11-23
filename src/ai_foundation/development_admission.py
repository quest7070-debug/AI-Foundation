"""Evidence-bound admission for zero-cost, useful, M1-compatible development.

No credentials, Drive token, model, scheduler or execution permission live here.
All receipts are produced by *trusted host adapters*; an LLM supplies only a
candidate ID. This module cannot manufacture receipts or expand Guard scopes.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
import re
import time

_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_TARGET = re.compile(r"src/ai_foundation/[a-z][a-z0-9_]*\.py\Z")
_EFFECTS = frozenset({"isolated_trial", "draft_code"})
_DENIED_TARGETS = frozenset({
    "src/ai_foundation/guard.py",
    "src/ai_foundation/core.py",
    "src/ai_foundation/credential_boundary.py",
    "src/ai_foundation/release_gate.py",
})


@dataclass(frozen=True)
class CostReceipt:
    checked_at: float
    proof: str
    license_free: bool
    initial_yen: int
    recurring_yen: int
    billing: str  # VERIFIED_DISABLED or NOT_APPLICABLE_LOCAL


@dataclass(frozen=True)
class BenefitReceipt:
    checked_at: float
    proof: str
    metric: str
    baseline: float
    observed: float
    direction: str  # higher or lower
    independently_measured: bool


@dataclass(frozen=True)
class HardwareReceipt:
    checked_at: float
    proof: str
    os_name: str
    arch: str
    device: str
    available_ram_bytes: int
    free_disk_bytes: int
    competing_work: bool


@dataclass(frozen=True)
class HostContract:
    """Provided by a host-owned finite registry, never by model output."""
    effect: str
    target: str
    test_sha256: str
    required_ram_bytes: int
    required_disk_bytes: int
    minimum_relative_gain: float
    guard_scope: str


class AdmissionError(ValueError):
    pass


def _proof(value):
    # A pointer to an independent source, never raw account or owner data.
    return (type(value) is str and 8 <= len(value) <= 256 and
            value.startswith(("https://", "m1:", "github:")) and
            not any(c.isspace() for c in value))


def _fresh(checked, now, age):
    return (type(checked) in (float, int) and math.isfinite(checked) and
            0 <= now - checked <= age)


def evaluate(candidate_id, contract, cost, benefit, hardware, *, now=None):
    """Fail closed on absent/stale/ambiguous evidence. No side effects."""
    now = time.time() if now is None else now
    if type(candidate_id) is not str or not _ID.fullmatch(candidate_id):
        return "INVALID_CANDIDATE"
    if type(contract) is not HostContract or contract.effect not in _EFFECTS:
        return "INVALID_HOST_CONTRACT"
    if (type(contract.target) is not str or not _TARGET.fullmatch(contract.target)
            or contract.target in _DENIED_TARGETS or
            type(contract.test_sha256) is not str or
            not _SHA.fullmatch(contract.test_sha256) or
            type(contract.guard_scope) is not str or
            not contract.guard_scope.startswith("development:")):
        return "INVALID_HOST_CONTRACT"
    if (type(contract.required_ram_bytes) is not int or
            type(contract.required_disk_bytes) is not int or
            contract.required_ram_bytes <= 0 or contract.required_disk_bytes <= 0 or
            type(contract.minimum_relative_gain) not in (int, float) or
            not math.isfinite(contract.minimum_relative_gain) or
            not 0 < contract.minimum_relative_gain <= 1):
        return "INVALID_HOST_CONTRACT"
    if (type(cost) is not CostReceipt or not _fresh(cost.checked_at, now, 86400)
            or not _proof(cost.proof) or cost.license_free is not True or
            type(cost.initial_yen) is not int or cost.initial_yen != 0 or
            type(cost.recurring_yen) is not int or cost.recurring_yen != 0 or
            cost.billing not in ("VERIFIED_DISABLED", "NOT_APPLICABLE_LOCAL")):
        return "COST_NOT_VERIFIED"
    if (type(benefit) is not BenefitReceipt or
            not _fresh(benefit.checked_at, now, 604800) or
            not _proof(benefit.proof) or
            benefit.independently_measured is not True or
            type(benefit.metric) is not str or
            not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", benefit.metric) or
            benefit.direction not in ("higher", "lower") or
            type(benefit.baseline) not in (int, float) or
            type(benefit.observed) not in (int, float) or
            not math.isfinite(benefit.baseline) or
            not math.isfinite(benefit.observed) or
            benefit.baseline <= 0 or benefit.observed < 0):
        return "BENEFIT_NOT_VERIFIED"
    improvement = ((benefit.observed - benefit.baseline) if benefit.direction == "higher"
                   else (benefit.baseline - benefit.observed)) / benefit.baseline
    if improvement < contract.minimum_relative_gain:
        return "BENEFIT_BELOW_THRESHOLD"
    if (type(hardware) is not HardwareReceipt or
            not _fresh(hardware.checked_at, now, 300) or
            not _proof(hardware.proof) or
            hardware.os_name != "macOS" or hardware.arch != "arm64" or
            type(hardware.device) is not str or
            re.fullmatch(r"Apple M1(?: Pro| Max| Ultra)?", hardware.device) is None or
            type(hardware.available_ram_bytes) is not int or
            type(hardware.free_disk_bytes) is not int or
            hardware.available_ram_bytes < contract.required_ram_bytes or
            hardware.free_disk_bytes < contract.required_disk_bytes or
            hardware.competing_work is not False):
        return "M1_FIT_NOT_VERIFIED"
    return "ADMITTED"


def _plan(candidate_id, contract, cost, benefit, hardware):
    """Only bounded nonsecret fields go to the owner-readable Drive plan."""
    return {
        "schema": "foundation-free-fit-admission/v1",
        "candidate_id": candidate_id,
        "decision": "TRIAL_CANDIDATE_PENDING_GUARD",
        "execution": {"effect": contract.effect, "target": contract.target,
                      "fixed_test_sha256": contract.test_sha256,
                      "guard_scope": contract.guard_scope,
                      "rollback": "DISCARD_ISOLATED_WORKTREE"},
        "cost": {"initial_yen": 0, "recurring_yen": 0,
                 "billing": cost.billing, "proof": cost.proof},
        "benefit": {"metric": benefit.metric, "baseline": benefit.baseline,
                    "measured": benefit.observed, "direction": benefit.direction,
                    "minimum_relative_gain": contract.minimum_relative_gain,
                    "proof": benefit.proof},
        "hardware": {"os": hardware.os_name, "arch": hardware.arch,
                     "device": hardware.device, "proof": hardware.proof,
                     "checked_at": hardware.checked_at,
                     "available_ram_bytes": hardware.available_ram_bytes,
                     "free_disk_bytes": hardware.free_disk_bytes,
                     "required_ram_bytes": contract.required_ram_bytes,
                     "required_disk_bytes": contract.required_disk_bytes},
        "status": "PLAN_ONLY_NOT_PRODUCTION_AUTHORITY",
    }


def plan_and_submit(candidate_id, *, contract, verifiers, drive, guard, executor,
                    now=None):
    """Plan -> independent Drive readback -> recheck -> Guard -> isolated submit.

    Host-owned ports:
      verifiers.cost/benefit/hardware(candidate_id) return trusted receipts;
      drive.create_once(digest, text) is idempotent; drive.read(id) returns
      exact text (not a summary); guard.authorize(contract, plan_id, digest)
      returns 'ALLOW' only for current exact Guard scope and plan identity;
      executor.submit(contract, plan_id, digest) uses digest as durable effect
      identity in the existing Work/Guard ledger, never creates another grant.

    The status is SUBMITTED_UNVERIFIED, NEVER production accepted. External
    source/CI/Drive and real M1 readback must independently complete acceptance.
    The model never supplies shell commands or chooses execution authority.
    """
    if (type(candidate_id) is not str or not _ID.fullmatch(candidate_id)):
        return {"status": "HOLD", "reason": "INVALID_CANDIDATE"}
    # A disconnected/failed host verifier is missing evidence, not permission
    # to continue or an uncaught exception that a scheduler may blindly retry.
    try:
        receipts = (verifiers.cost(candidate_id), verifiers.benefit(candidate_id),
                    verifiers.hardware(candidate_id))
        # Measure freshness after host evidence acquisition: a genuinely
        # fresh hardware sample must not be future-dated relative to entry.
        decision = evaluate(candidate_id, contract, *receipts,
                            now=time.time() if now is None else now)
    except Exception:
        return {"status": "HOLD", "reason": "HOST_EVIDENCE_UNAVAILABLE"}
    if decision != "ADMITTED":
        return {"status": "HOLD", "reason": decision}
    body = json.dumps(_plan(candidate_id, contract, *receipts),
                      ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = sha256(body.encode("utf-8")).hexdigest()
    try:
        plan_id = drive.create_once(digest, body)
        if type(plan_id) is not str or not _ID.fullmatch(plan_id.lower()):
            # Native Drive IDs contain uppercase/hyphens/underscores.
            if type(plan_id) is not str or not re.fullmatch(
                    r"[A-Za-z0-9_-]{10,160}", plan_id):
                raise AdmissionError("INVALID_DRIVE_PLAN_ID")
        if drive.read(plan_id) != body:
            return {"status": "HOLD", "reason": "DRIVE_READBACK_MISMATCH"}
    except Exception:
        # Unknown write effect requires reconciliation by digest, not retry.
        return {"status": "HOLD", "reason": "DRIVE_PLAN_UNVERIFIED"}
    # Recheck time-sensitive evidence AFTER the Drive write, before execution.
    try:
        current = (verifiers.cost(candidate_id), verifiers.benefit(candidate_id),
                   verifiers.hardware(candidate_id))
        still_admitted = evaluate(candidate_id, contract, *current,
                                  now=time.time() if now is None else now) == "ADMITTED"
    except Exception:
        return {"status": "HOLD", "reason": "HOST_EVIDENCE_RECHECK_UNAVAILABLE",
                "plan_id": plan_id}
    # New hardware snapshots legitimately have a new timestamp and free
    # capacity. Cost/benchmark *identity* stays pinned while actual M1
    # capacity must be freshly sufficient, not byte-for-byte identical.
    if (current[0] != receipts[0] or current[1] != receipts[1]
            or current[2].device != receipts[2].device or not still_admitted):
        return {"status": "HOLD", "reason": "EVIDENCE_CHANGED_AFTER_PLAN",
                "plan_id": plan_id}
    try:
        guard_result = guard.authorize(contract, plan_id, digest)
    except Exception:
        # A Guard callback may have persisted a pending request before failing.
        # Reconcile that exact request; never infer ALLOW or auto-resubmit.
        return {"status": "HOLD", "reason": "GUARD_OUTCOME_UNCERTAIN",
                "plan_id": plan_id, "reconciliation_required": True}
    # Only the canonical Guard's explicit WAITING_HUMAN verdict is a human
    # request. DENY is a final refusal of this plan, LOCAL_ONLY may not cross
    # the GitHub/Drive/worker submission boundary, and unknown values never
    # become an owner escalation or an implicit authority grant.
    if guard_result == "WAITING_HUMAN":
        return {"status": "WAITING_HUMAN", "reason": "GUARD_NOT_AUTHORIZED",
                "plan_id": plan_id}
    if guard_result == "DENY":
        return {"status": "HOLD", "reason": "GUARD_DENIED",
                "plan_id": plan_id}
    if guard_result == "LOCAL_ONLY":
        return {"status": "HOLD", "reason": "GUARD_LOCAL_ONLY",
                "plan_id": plan_id}
    if guard_result != "ALLOW":
        return {"status": "HOLD", "reason": "GUARD_RESULT_UNVERIFIED",
                "plan_id": plan_id}
    # Last readback catches any in-flight Drive replacement after Guard.
    try:
        plan_still_current = drive.read(plan_id) == body
    except Exception:
        return {"status": "HOLD", "reason": "PLAN_READBACK_UNAVAILABLE",
                "plan_id": plan_id}
    if not plan_still_current:
        return {"status": "HOLD", "reason": "PLAN_CHANGED_BEFORE_EXECUTION",
                "plan_id": plan_id}
    try:
        execution_ref = executor.submit(contract, plan_id, digest)
    except Exception:
        # submit() may have started a real effect before its acknowledgement
        # failed; caller MUST reconcile via canonical effect identity.
        return {"status": "HOLD", "reason": "EXECUTION_OUTCOME_UNCERTAIN",
                "plan_id": plan_id, "reconciliation_required": True}
    if type(execution_ref) is not str or not execution_ref:
        return {"status": "HOLD", "reason": "EXECUTION_RECEIPT_UNVERIFIED",
                "plan_id": plan_id, "reconciliation_required": True}
    return {"status": "SUBMITTED_UNVERIFIED", "plan_id": plan_id,
            "plan_sha256": digest, "execution_ref": execution_ref}
