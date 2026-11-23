"""Existing Guard-backed HumanModel collection-consent verifier.

Integration contract for an authenticated host; it does not authenticate HTTP
requests, mint consent, schedule collection, create a new grant DB, or open
private files. A consent is an exact, durable Guard-approved, still-current
intent for ONE source revision and purpose.

IMPORTANT: GuardCore.preflight() alone does not require approval for the custom
'human_model_collect' action. Never remove the exact is_approved_for() check.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .core import CanonContract, Decision, TaskPlan
from .guard import GuardCore
from .human_model_context import HumanModelBinding

_ACTION = "human_model_collect"
_PREFIX = "human-model:collect:"


def _digest(payload) -> str:
    return hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CollectionIntent:
    """Opaque, exact Guard plan; contains no source URI or raw personal text."""
    run_id: str
    action: str
    target: str
    canon_revision: str
    effect_id: str


def collection_intent(grant, *, binding: HumanModelBinding,
                      canon: CanonContract) -> CollectionIntent:
    """Bind an existing Guard approval to the exact source and purpose.

    The grant is a privately staged source record; it is never authority. Its
    consent_id identifies an existing Guard approval run, not a model assertion.
    """
    if not isinstance(binding, HumanModelBinding) or not isinstance(canon, CanonContract):
        raise PermissionError("HOST_COLLECTION_BINDING_REQUIRED")
    if (not canon.clear or not canon.revision or binding.max_privacy != "private"
            or grant.owner_id != binding.owner_id
            or grant.scope not in binding.scopes
            or grant.privacy != "private"
            or not isinstance(grant.consent_id, str) or not grant.consent_id
            or not isinstance(grant.consent_revision, str) or not grant.consent_revision):
        raise PermissionError("COLLECTION_OWNER_SCOPE_INVALID")
    fingerprint = _digest({
        "version": 1, "owner": binding.owner_id,
        "root": binding.root, "view": binding.view_id,
        "source": grant.source_system, "source_id": grant.source_record_id,
        "uri": grant.source_uri, "source_revision": grant.source_revision,
        "sha256": grant.expected_sha256, "scope": grant.scope,
        "purpose": grant.purpose, "privacy": grant.privacy,
        "consent_id": grant.consent_id, "consent_revision": grant.consent_revision,
    })
    return CollectionIntent(
        run_id=grant.consent_id,
        action=_ACTION,
        target=_PREFIX + fingerprint,
        canon_revision=canon.revision,
        effect_id=fingerprint,
    )


class GuardCollectionConsent:
    """Per-request in-process boundary using the existing durable Guard store.

    This object must be constructed by the authenticated host from its own
    binding/Guard/Canon. Neither model tools nor arbitrary HTTP JSON may create
    a trustworthy instance.
    """

    def __init__(self, *, authenticated_owner: str,
                 binding: HumanModelBinding, guard: GuardCore,
                 canon: CanonContract):
        if (not isinstance(authenticated_owner, str)
                or not isinstance(binding, HumanModelBinding)
                or not isinstance(guard, GuardCore)
                or not isinstance(canon, CanonContract)
                or binding.owner_id != authenticated_owner
                or binding.max_privacy != "private"):
            raise PermissionError("HOST_COLLECTION_AUTHORITY_REQUIRED")
        self.owner = authenticated_owner
        self.binding = binding
        self.guard = guard
        self.canon = canon

    def __call__(self, grant) -> bool:
        """No model needed; consent must be current and exact, or deny."""
        if grant.owner_id != self.owner:
            return False
        try:
            intent = collection_intent(grant, binding=self.binding, canon=self.canon)
            store = self.guard.store
            if store is None or not callable(getattr(store, "is_approved_for", None)):
                return False
            # This is the authorizing check. Generic Guard preflight can permit
            # this action without consent, and is NEVER enough on its own.
            if store.is_approved_for(
                intent.run_id, intent.action, intent.target,
                intent.canon_revision, intent.effect_id,
            ) is not True:
                return False
            plan = TaskPlan(
                run_id=intent.run_id, action=intent.action,
                target=intent.target, canon_revision=intent.canon_revision,
                effect_id=intent.effect_id, paid_cost=0, privacy_text="",
            )
            decision = self.guard.preflight(plan, self.canon)
            # The owner-side ledger writer is local; LOCAL_ONLY is acceptable
            # only here, never as a remote/cloud send grant.
            return decision in (Decision.ALLOW, Decision.LOCAL_ONLY)
        except Exception:
            return False


    def active_digest(self, consent_sha256: str) -> bool:
        """Read-only, host-bound current consent proof for the View reader.

        The HumanModel ledger persists the SHA of the original Guard run, not
        its raw ID. Compare against *durably approved* collection runs only.
        There is no blanket or run-only fallback. Too many approvals or any
        unknown state denies the read. This does not mint consent or update DB.
        """
        if (type(consent_sha256) is not str or len(consent_sha256) != 64
                or not all(c in "0123456789abcdef" for c in consent_sha256)
                or self.canon.clear is not True):
            return False
        store = self.guard.store
        if store is None or not callable(getattr(store, "_connect", None)):
            return False
        try:
            with store._connect() as db:
                approvals = db.execute(
                    "SELECT run_id,target,canon_revision,effect_id FROM approvals "
                    "WHERE action='human_model_collect' LIMIT 513"
                ).fetchall()
            if len(approvals) > 512:
                return False
            for run_id, target, revision, effect_id in approvals:
                if hashlib.sha256(run_id.encode()).hexdigest() != consent_sha256:
                    continue
                if revision != self.canon.revision or not target.startswith(_PREFIX):
                    return False
                if (not effect_id or self.guard.store.is_cancelled(run_id)
                        or not self.guard.store.is_approved_for(
                            run_id, _ACTION, target, revision, effect_id)):
                    return False
                decision = self.guard.preflight(
                    TaskPlan(run_id=run_id,action=_ACTION,target=target,
                             canon_revision=revision,effect_id=effect_id,
                             paid_cost=0,privacy_text=""),
                    self.canon,
                )
                return decision in (Decision.ALLOW, Decision.LOCAL_ONLY)
            return False
        except Exception:
            return False
