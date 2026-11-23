"""Thin admission adapter to the CURRENT Guard, never a second permission DB.

A host-owned immutable predelegation registry binds full contract objects.
Drive/model/Issue text cannot extend it. This is only a preflight, not a
permission to change production or a replacement for GuardedToolGateway.
"""
from __future__ import annotations

from hashlib import sha256
import re

from .core import CanonContract, Decision, TaskPlan
from .development_admission import HostContract

SHA64 = re.compile(r"[a-f0-9]{64}\Z")
DRIVE_ID = re.compile(r"[A-Za-z0-9_-]{10,160}\Z")


class GuardAdmissionPort:
    def __init__(self, guard, canon, *, delegated_contracts):
        if (type(canon) is not CanonContract or not canon.clear or
                type(delegated_contracts) is not frozenset or
                not delegated_contracts or
                any(type(v) is not HostContract for v in delegated_contracts)):
            raise ValueError("TRUSTED_GUARD_ADMISSION_REGISTRY_REQUIRED")
        self.guard = guard
        self.canon = canon
        self.allowed = delegated_contracts

    def authorize(self, contract, plan_id, digest):
        """Return ALLOW only after current exact bound Guard preflight.

        Guard's approved scope may be narrower than this registry. Both must
        agree and later real source writes still cross the existing Guard tool.
        """
        if (type(contract) is not HostContract or contract not in self.allowed or
                type(plan_id) is not str or not DRIVE_ID.fullmatch(plan_id) or
                type(digest) is not str or not SHA64.fullmatch(digest) or
                contract.effect not in {"isolated_trial", "draft_code"} or
                contract.guard_scope != "development:fixed-test"):
            return "DENY"
        # Same digest across plan, Guard authorization and durable executor.
        run_id = "foundation-admission-" + digest[:32]
        plan = TaskPlan(
            run_id=run_id, action="write", target=contract.target,
            text="Offline reversible test via host-pinned candidate and Drive plan",
            paid_cost=0, canon_revision=self.canon.revision,
            exclusive_target=True, effect_id=digest,
            provenance="admission/" + sha256(
                (plan_id + ":" + digest).encode("ascii")).hexdigest(),
        )
        result = self.guard.preflight(plan, self.canon)
        return "ALLOW" if result is Decision.ALLOW else result.value
