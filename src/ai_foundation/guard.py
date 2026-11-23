import re
import time
import threading
import uuid
from typing import Protocol

from .core import CanonContract, CredentialBoundary, Decision, EffectIntent, EffectStatus, ExecutionPort, GuardState, PolicyBoundary, TaskPlan
from .sensitive_input_scan import contains_sensitive_value


class GuardStore(Protocol):
    def save(self, state: GuardState) -> None: ...


class GuardCore:
    APPROVAL_ACTIONS = {"purchase", "delete", "send_email", "production_deploy", "development_scope"}
    SECRET = re.compile(
        r"(?i)(password|passwd|passphrase|api[_ -]?key|secret|token|bearer|private[_ -]?key|"
        r"パスワード|パスフレーズ|api(?:キー|鍵)|トークン|秘密鍵)\s*[：:=]?\s*\S+"
    )
    PRIVATE = re.compile(
        r"(?i)(private|personal|個人情報|秘密|機密|住所|電話(?:番号)?|メール(?:アドレス)?|"
        r"e-?mail|phone|address)"
    )

    def __init__(self, state: GuardState, monthly_limit: int = 0, store: GuardStore | None = None, claim_ttl: float = 30.0, credential_boundary: CredentialBoundary | None = None, policy_boundary: PolicyBoundary | None = None):
        self.state = state
        self.monthly_limit = monthly_limit
        self.store = store
        self.owner = uuid.uuid4().hex
        self.claim_ttl = claim_ttl
        self.credential_boundary = credential_boundary
        self.policy_boundary = policy_boundary

    def _save(self):
        if self.store:
            self.store.save(self.state)

    def get_effect(self, effect_id: str) -> EffectIntent | None:
        """Observe existing effect identity without initializing or mutating it."""
        if self.store and hasattr(self.store, 'get_effect'):
            return self.store.get_effect(effect_id)
        return self.state.effects.get(effect_id)

    def _release_budget(self, effect_id: str) -> None:
        if self.store and hasattr(self.store, "release_budget"):
            self.store.release_budget(effect_id)

    def _release_claim(self, effect_id: str) -> None:
        if self.store and hasattr(self.store, "release_claim"):
            self.store.release_claim(effect_id, self.owner)

    def _release_target(self, plan: TaskPlan, claimed: bool) -> None:
        if claimed and self.store and hasattr(self.store, "release_target"):
            self.store.release_target(plan.target, self.owner)

    def _set_effect_status(self, effect: EffectIntent, old: EffectStatus, new: EffectStatus) -> bool:
        if self.store and hasattr(self.store, "transition_effect"):
            if not self.store.transition_effect(effect.effect_id, old, new):
                return False
            effect.status = new
        else:
            effect.status = new
            self._save()
        return True

    def approve_pending(self, run_id: str, request_ref: str) -> bool:
        """Decision must target the current Guard-owned pending request."""
        if not self.store or not hasattr(self.store, 'approve_pending'):
            return False
        if not self.store.approve_pending(run_id, request_ref):
            return False
        # The store already committed atomically; avoid a second full-state
        # save that could overwrite concurrent approval/cancellation decisions.
        self.state.approvals.add(run_id)
        return True

    def cancel_pending(self, run_id: str, request_ref: str) -> bool:
        if not self.store or not hasattr(self.store, 'cancel_pending'):
            return False
        if not self.store.cancel_pending(run_id, request_ref):
            return False
        self.state.cancellations.add(run_id)
        return True

    def approve(self, run_id: str):
        self.state.approvals.add(run_id)
        self._save()
        if self.store and hasattr(self.store,'resolve_approval'):self.store.resolve_approval(run_id)

    def cancel(self, run_id: str):
        self.state.cancellations.add(run_id)
        self._save()
        if self.store and hasattr(self.store,'resolve_approval'):self.store.resolve_approval(run_id)

    def preflight(self, plan: TaskPlan, canon: CanonContract) -> Decision:
        if self.store and hasattr(self.store, 'spent'):
            self.state.spent = self.store.spent()
        elif self.store and hasattr(self.store, 'load'):
            self.state.spent = self.store.load().spent
        cancelled = plan.run_id in self.state.cancellations
        if not cancelled and self.store and hasattr(self.store, 'is_cancelled'):
            cancelled = self.store.is_cancelled(plan.run_id)
        if cancelled:
            return Decision.DENY
        if plan.credential_binding:
            if self.credential_boundary is None:
                return Decision.DENY
            try:
                if not self.credential_boundary.authorize(plan.credential_binding, plan.target):
                    return Decision.DENY
            except Exception:
                return Decision.DENY
        if not canon.clear or plan.canon_revision != canon.revision:
            return Decision.WAITING_HUMAN
        if self.policy_boundary is not None:
            try:
                policy_decision = self.policy_boundary.authorize(plan)
            except Exception:
                return Decision.DENY
            if policy_decision is not Decision.ALLOW:
                return policy_decision
        if plan.paid_cost < 0:
            return Decision.DENY
        if self.monthly_limit >= 0 and self.state.spent + plan.paid_cost > self.monthly_limit:
            return Decision.DENY
        privacy_text = plan.text if plan.privacy_text is None else plan.privacy_text
        # Keep user-origin privacy_text for ambiguous policy keywords. Inspect
        # structured values in the outbound body too: tool results may contain
        # unlabelled secrets or PII absent from privacy_text.
        if (self.SECRET.search(privacy_text) or self.PRIVATE.search(privacy_text)
                or contains_sensitive_value(privacy_text)
                or (plan.privacy_text is not None and
                    contains_sensitive_value(plan.text))):
            return Decision.LOCAL_ONLY
        approved = plan.run_id in self.state.approvals or (self.store is not None and hasattr(self.store,'is_approved') and self.store.is_approved(plan.run_id))
        if plan.action in self.APPROVAL_ACTIONS:
            if self.store is not None and hasattr(self.store,'is_approved_for'):
                # Durable UI grants are exact plan-bound, not cached run IDs.
                # Refuse to turn a previously consumed run into a new effect.
                approved = self.store.is_approved_for(
                    plan.run_id, plan.action, plan.target, plan.canon_revision,
                    plan.effect_id or plan.run_id)
                if not approved and self.store.is_approved(plan.run_id):
                    return Decision.DENY
            if not approved:
                if self.store and hasattr(self.store,'request_approval'):
                    if hasattr(self.store,'is_approved_for'):
                        self.store.request_approval(
                            plan.run_id, plan.action, plan.target,
                            plan.canon_revision, plan.effect_id or plan.run_id)
                    else:
                        self.store.request_approval(plan.run_id,plan.action,plan.target)
                return Decision.WAITING_HUMAN
        return Decision.ALLOW

    def execute(self, plan: TaskPlan, canon: CanonContract, port: ExecutionPort, expected: str, *, local_only: bool = False) -> str:
        effect_id = plan.effect_id or plan.run_id
        decision = self.preflight(plan, canon)
        if local_only and decision is Decision.LOCAL_ONLY:
            decision = Decision.ALLOW
        if decision is not Decision.ALLOW:
            return decision.value
        if self.store and hasattr(self.store, "reserve_budget"):
            if not self.store.reserve_budget(effect_id, plan.paid_cost, self.monthly_limit):
                return Decision.DENY.value
        # Durable state can advance while another host instance still holds a
        # cached PLANNED/EXECUTING snapshot. Refresh before choosing execution
        # versus reconciliation; a stale cache cannot revive the old phase.
        effect = self.get_effect(effect_id)
        if effect is not None:
            self.state.effects[effect_id] = effect
        if effect is None:
            effect=EffectIntent(effect_id, plan.run_id, plan.target, expected, paid_cost=plan.paid_cost)
            self.state.effects[effect_id]=effect
        self._save()
        target_claimed = False
        if effect.status is EffectStatus.PLANNED and plan.target_precondition:
            if port.observe(plan) != plan.target_precondition:
                self._release_budget(effect_id)
                return "TARGET_PRECONDITION_CONFLICT"
        if effect.status is EffectStatus.PLANNED and plan.exclusive_target and self.store and hasattr(self.store, "try_claim_target"):
            if not self.store.try_claim_target(plan.target, self.owner, time.time(), self.claim_ttl):
                self._release_budget(effect_id)
                return "TARGET_IN_PROGRESS"
            target_claimed = True
        if effect.status is EffectStatus.VERIFIED:
            self._release_budget(effect_id)
            return "VERIFIED_COMPLETE"
        if effect.status is EffectStatus.FAILED:
            self._release_budget(effect_id)
            return "FAILED_EFFECT"
        if effect.status in {EffectStatus.UNCERTAIN, EffectStatus.EXECUTING, EffectStatus.OBSERVED}:
            if self.store and hasattr(self.store, "claim_for_reconcile"):
                if not self.store.claim_for_reconcile(effect_id, self.owner, time.time(), self.claim_ttl):
                    return "EFFECT_IN_PROGRESS"
            elif self.store and hasattr(self.store, "claim_owner"):
                active_owner = self.store.claim_owner(effect_id, time.time())
                if active_owner and active_owner != self.owner:
                    return "EFFECT_IN_PROGRESS"
            try:
                return self._reconcile(plan, port, effect)
            finally:
                self._release_claim(effect_id)
        if self.store and hasattr(self.store, "try_claim"):
            if not self.store.try_claim(effect_id, self.owner, time.time(), self.claim_ttl):
                return "EFFECT_IN_PROGRESS"
        if self.store and hasattr(self.store, "transition_effect"):
            if not self.store.transition_effect(effect_id, EffectStatus.PLANNED, EffectStatus.AUTHORIZED):
                self._release_target(plan, target_claimed)
                return "EFFECT_STATE_CONFLICT"
            effect.status = EffectStatus.AUTHORIZED
            if not self.store.transition_effect(effect_id, EffectStatus.AUTHORIZED, EffectStatus.EXECUTING):
                self._release_target(plan, target_claimed)
                return "EFFECT_STATE_CONFLICT"
            effect.status = EffectStatus.EXECUTING
        else:
            effect.status = EffectStatus.AUTHORIZED
            self._save()
            effect.status = EffectStatus.EXECUTING
            self._save()
        # Re-evaluate mutable authorization/canon conditions at the last safe
        # point before the external effect. A changed contract must fail closed.
        final_decision = self.preflight(plan, canon)
        if local_only and final_decision is Decision.LOCAL_ONLY:
            final_decision = Decision.ALLOW
        if final_decision is not Decision.ALLOW:
            if self.store and hasattr(self.store, "transition_effect"):
                self.store.transition_effect(effect_id, EffectStatus.EXECUTING, EffectStatus.UNCERTAIN)
            else:
                effect.status = EffectStatus.UNCERTAIN
                self._save()
            self._release_claim(effect_id)
            self._release_target(plan, target_claimed)
            return final_decision.value
        stop_heartbeat = threading.Event()
        lease_lost = threading.Event()
        heartbeat = None
        if self.store and hasattr(self.store, "renew_claim"):
            interval = max(0.001, min(self.claim_ttl / 3, self.claim_ttl * 0.25))
            def renew_loop():
                while not stop_heartbeat.wait(interval):
                    now = time.time()
                    if not self.store.renew_claim(effect_id, self.owner, now, self.claim_ttl):
                        lease_lost.set()
                        break
                    if target_claimed and hasattr(self.store, "renew_target"):
                        if not self.store.renew_target(plan.target, self.owner, now, self.claim_ttl):
                            lease_lost.set()
                            break
            heartbeat = threading.Thread(target=renew_loop, daemon=True)
            heartbeat.start()
        try:
            port.execute(plan)
        except Exception:
            stop_heartbeat.set()
            if heartbeat: heartbeat.join(timeout=1)
            if self.store and hasattr(self.store, "transition_effect"):
                if not self.store.transition_effect(effect_id, EffectStatus.EXECUTING, EffectStatus.UNCERTAIN):
                    return "EFFECT_STATE_CONFLICT"
                effect.status = EffectStatus.UNCERTAIN
            else:
                effect.status = EffectStatus.UNCERTAIN
                self._save()
            self._release_claim(effect_id)
            self._release_target(plan, target_claimed)
            return "UNCERTAIN_RECONCILE_REQUIRED"
        stop_heartbeat.set()
        if heartbeat: heartbeat.join(timeout=1)
        # Once execute() returned, cancellation cannot mean "nothing happened".
        # Reconcile the real world instead of pretending the effect was stopped.
        cancelled = plan.run_id in self.state.cancellations
        if not cancelled and self.store and hasattr(self.store,'is_cancelled'):
            cancelled=self.store.is_cancelled(plan.run_id)
        if cancelled:
            if self.store and hasattr(self.store, "transition_effect"):
                if not self.store.transition_effect(effect_id, EffectStatus.EXECUTING, EffectStatus.UNCERTAIN):
                    return "EFFECT_STATE_CONFLICT"
                effect.status = EffectStatus.UNCERTAIN
            else:
                effect.status = EffectStatus.UNCERTAIN
                self._save()
            self._release_claim(effect_id)
            self._release_target(plan, target_claimed)
            return "CANCELLED_RECONCILE_REQUIRED"
        if lease_lost.is_set():
            if self.store and hasattr(self.store, "transition_effect"):
                self.store.transition_effect(effect_id, EffectStatus.EXECUTING, EffectStatus.UNCERTAIN)
            else:
                effect.status = EffectStatus.UNCERTAIN
                self._save()
            self._release_target(plan, target_claimed)
            return "UNCERTAIN_RECONCILE_REQUIRED"
        if self.store and hasattr(self.store, "transition_effect"):
            if not self.store.transition_effect(effect_id, EffectStatus.EXECUTING, EffectStatus.OBSERVED):
                return "EFFECT_STATE_CONFLICT"
            effect.status = EffectStatus.OBSERVED
        else:
            effect.status = EffectStatus.OBSERVED
            self._save()
        try:
            return self._verify(plan, port, effect)
        finally:
            self._release_claim(effect_id)
            self._release_target(plan, target_claimed)

    def reconcile_effect(self, effect_id: str, plan: TaskPlan, port: ExecutionPort) -> str:
        """Public observe-only reconciliation boundary for operator/runtime callers."""
        effect=self.state.effects.get(effect_id)
        if effect is None and self.store and hasattr(self.store,'get_effect'):
            effect=self.store.get_effect(effect_id)
        elif effect is None and self.store and hasattr(self.store,'load'):
            effect=self.store.load().effects.get(effect_id)
            if effect: self.state.effects[effect_id]=effect
        if effect is None: return 'NOT_FOUND'
        if effect.status not in {EffectStatus.EXECUTING,EffectStatus.UNCERTAIN,EffectStatus.OBSERVED}: return 'NOT_ACTIONABLE'
        if self.store and hasattr(self.store,'claim_for_reconcile'):
            if not self.store.claim_for_reconcile(effect_id,self.owner,time.time(),self.claim_ttl): return 'EFFECT_IN_PROGRESS'
        try:
            return self._reconcile(plan,port,effect)
        finally:
            self._release_claim(effect_id)

    def _reconcile(self, plan: TaskPlan, port: ExecutionPort, effect: EffectIntent) -> str:
        observed = port.observe(plan)
        if observed == effect.expected:
            return self._mark_verified(effect)
        if not self._set_effect_status(effect, effect.status, EffectStatus.UNCERTAIN):
            return "EFFECT_STATE_CONFLICT"
        return "WAITING_HUMAN_UNCERTAIN_EFFECT"

    def _verify(self, plan: TaskPlan, port: ExecutionPort, effect: EffectIntent) -> str:
        if port.observe(plan) != effect.expected:
            if not self._set_effect_status(effect, effect.status, EffectStatus.FAILED):
                return "EFFECT_STATE_CONFLICT"
            return "FAILED_VERIFICATION"
        return self._mark_verified(effect)

    def _mark_verified(self, effect: EffectIntent) -> str:
        if effect.status is not EffectStatus.VERIFIED:
            old_status = effect.status
            if self.store and hasattr(self.store, "transition_effect"):
                if not self.store.transition_effect(effect.effect_id, old_status, EffectStatus.VERIFIED):
                    return "EFFECT_STATE_CONFLICT"
                effect.status = EffectStatus.VERIFIED
                if hasattr(self.store,'spent'):
                    self.state.spent=self.store.spent()
                elif hasattr(self.store, "load"):
                    self.state.spent = self.store.load().spent
            else:
                effect.status = EffectStatus.VERIFIED
                self.state.spent += effect.paid_cost
                self._save()
        return "VERIFIED_COMPLETE"
