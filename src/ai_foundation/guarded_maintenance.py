"""Host-bound composition of reviewed maintenance with the existing Guard.

No shell, approval issuer, service adapter, lease implementation, scheduler,
rollback engine or state store lives here. Production bindings are separate
acceptance work; source fixtures must never be treated as live authorization.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import re

from .core import CanonContract, EffectStatus, TaskPlan

OPERATIONS = frozenset({"activate-reviewed-release", "rollback-reviewed-release", "restart-reviewed-service"})
TARGETS = frozenset({"foundation_operator", "local9b_autodev", "llama_swap"})
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class ReviewedMaintenanceIntent:
    operation: str
    target: str
    canon_source: str
    before_fingerprint: str
    after_fingerprint: str
    canon_revision: str
    policy_revision: str
    nonce: str
    data_scope: str = "NON_PERSONAL_RUNTIME_ONLY"

    def __post_init__(self):
        if (type(self.operation) is not str or self.operation not in OPERATIONS
                or type(self.target) is not str or self.target not in TARGETS):
            raise ValueError("MAINTENANCE_OPERATION_OR_TARGET_INVALID")
        for value in (self.before_fingerprint, self.after_fingerprint, self.policy_revision):
            if type(value) is not str or HEX64.fullmatch(value) is None:
                raise ValueError("MAINTENANCE_FINGERPRINT_REQUIRED")
        if self.before_fingerprint == self.after_fingerprint:
            raise ValueError("MAINTENANCE_DISTINCT_GENERATION_PROOF_REQUIRED")
        if self.data_scope != "NON_PERSONAL_RUNTIME_ONLY":
            raise ValueError("MAINTENANCE_PERSONAL_DATA_SCOPE_EXCLUDED")
        if (type(self.canon_source) is not str or re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", self.canon_source) is None
                or type(self.canon_revision) is not str or re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", self.canon_revision) is None
                or type(self.nonce) is not str or re.fullmatch(r"[0-9a-f]{32}", self.nonce) is None):
            raise ValueError("MAINTENANCE_REVIEW_IDENTITY_INVALID")

    @property
    def digest(self):
        return sha256(json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    @property
    def run_id(self):
        return "maintenance:" + self.digest


class GuardedMaintenance:
    """Capture an immutable owner-reviewed intent; execute accepts no arguments.

    Existing host owners supply the durable Guard, policy, shared whole-job
    lease and exact bound port. The port observes independent generation/state
    fingerprints and performs only its reviewed action. It must not touch a
    personal-data target or replace the Guard authority it is using.
    """
    REQUIRED_STORE_METHODS = ("get_effect", "try_claim", "try_claim_target", "renew_claim",
        "renew_target", "transition_effect", "claim_for_reconcile", "is_approved", "is_cancelled")

    def __init__(self, intent, canon, guard, port, lease):
        if type(intent) is not ReviewedMaintenanceIntent or not isinstance(canon, CanonContract):
            raise ValueError("MAINTENANCE_REVIEWED_BINDING_REQUIRED")
        if canon.source != intent.canon_source:
            raise ValueError("MAINTENANCE_CANON_SOURCE_MISMATCH")
        if (guard.store is None or guard.policy_boundary is None
                or any(not callable(getattr(guard.store, name, None)) for name in self.REQUIRED_STORE_METHODS)
                or not callable(getattr(lease, "hold", None))):
            raise ValueError("MAINTENANCE_EXISTING_DURABLE_GUARD_POLICY_LEASE_REQUIRED")
        self._intent, self._canon, self._guard, self._port, self._lease = intent, canon, guard, port, lease
        self._validate_binding()
        self._plan = TaskPlan(run_id=intent.run_id, effect_id=intent.run_id,
            action="production_deploy", target="maintenance:" + intent.target,
            # Receipt metadata is not user-originated content. Keep the text
            # payload to a fixed digest label; full metadata remains bound by
            # that digest and describe(). Do not override Guard privacy policy.
            text="reviewed-maintenance:" + intent.digest, paid_cost=0,
            canon_revision=intent.canon_revision, policy_revision=intent.policy_revision,
            target_precondition=intent.before_fingerprint, exclusive_target=True,
            provenance="m1-reviewed-maintenance/v1:" + intent.digest)

    def _validate_binding(self):
        if (getattr(self._port, "intent_digest", None) != self._intent.digest
                or getattr(self._port, "data_scope", None) != self._intent.data_scope
                or not callable(getattr(self._port, "execute", None))
                or not callable(getattr(self._port, "observe", None))):
            raise ValueError("MAINTENANCE_HOST_PORT_BINDING_MISMATCH")

    def describe(self):
        """Review metadata only. Does not request approval or read Guard state."""
        return {**asdict(self._intent), "digest": self._intent.digest,
            "run_id": self._intent.run_id, "guard_action": "production_deploy"}

    def _effect(self):
        effect = self._guard.get_effect(self._plan.effect_id)
        if effect is not None and (effect.run_id != self._plan.run_id
                or effect.target != self._plan.target
                or effect.expected != self._intent.after_fingerprint or effect.paid_cost != 0):
            raise ValueError("MAINTENANCE_EFFECT_IDENTITY_MISMATCH")
        return effect

    def execute(self):
        self._validate_binding()
        with self._lease.hold():
            effect = self._effect()
            if effect is not None and effect.status in {
                    EffectStatus.EXECUTING, EffectStatus.UNCERTAIN, EffectStatus.OBSERVED}:
                return "UNCERTAIN_RECONCILE_REQUIRED"
            port = _BoundPort(self)
            if effect is not None and effect.status is EffectStatus.VERIFIED:
                if port.observe(self._plan) != self._intent.after_fingerprint:
                    return "VERIFIED_EFFECT_TARGET_DRIFT"
            return self._guard.execute(self._plan, self._canon, port, self._intent.after_fingerprint)

    def reconcile(self):
        """Existing Guard observe-only reconciliation; never re-execute a service."""
        self._validate_binding()
        with self._lease.hold():
            if self._effect() is None:
                return "NOT_FOUND"
            return self._guard.reconcile_effect(self._plan.effect_id, self._plan, _BoundPort(self))


class _BoundPort:
    def __init__(self, owner):
        self.owner = owner

    def _check(self, plan):
        self.owner._validate_binding()
        if plan != self.owner._plan:
            raise ValueError("MAINTENANCE_PLAN_MISMATCH")

    def execute(self, plan):
        self._check(plan)
        self.owner._port.execute()

    def observe(self, plan):
        self._check(plan)
        value = self.owner._port.observe()
        if type(value) is not str or HEX64.fullmatch(value) is None:
            raise ValueError("MAINTENANCE_READBACK_FINGERPRINT_INVALID")
        return value
