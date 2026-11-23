"""Immutable, Guard/owner-approved release+rollback gate.

This module records and verifies release-scope authority only. It never writes
host services, restarts processes, dispatches Native/model effects, or bypasses
Guard. A verified gate is permission metadata for an independently authorized
operator action, not that action itself.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass

from .migration import CutoverRegistry
from .store import approval_request_ref as _store_request_ref

_SHA = re.compile(r"[0-9a-f]{40,64}\Z")
_RUN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_REF = re.compile(r"[a-f0-9]{64}\Z")


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} required")
    return value.strip()


def _sha(value, name):
    value = _text(value, name).lower()
    if not _SHA.fullmatch(value):
        raise ValueError(f"invalid {name}")
    return value


def release_scope_ref(scope):
    raw = json.dumps(scope, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


@dataclass(frozen=True)
class ImmutableReleaseScope:
    """Exact release identity + rollback contract. Any change yields a new scope."""

    path: str
    source_sha: str
    previous_authority: str
    previous_endpoint: str
    candidate_authority: str
    candidate_endpoint: str
    rollback_procedure: str
    switch_target: str
    readback_target: str
    rollback_readback_target: str

    def __post_init__(self):
        object.__setattr__(self, "path", _text(self.path, "path"))
        object.__setattr__(self, "source_sha", _sha(self.source_sha, "source_sha"))
        for field in ("previous_authority", "previous_endpoint", "candidate_authority",
                      "candidate_endpoint", "rollback_procedure", "switch_target",
                      "readback_target", "rollback_readback_target"):
            object.__setattr__(self, field, _text(getattr(self, field), field))

    @property
    def scope_ref(self):
        return release_scope_ref(self.as_dict())

    def as_dict(self):
        return {
            "path": self.path, "source_sha": self.source_sha,
            "previous_authority": self.previous_authority,
            "previous_endpoint": self.previous_endpoint,
            "candidate_authority": self.candidate_authority,
            "candidate_endpoint": self.candidate_endpoint,
            "rollback_procedure": self.rollback_procedure,
            "switch_target": self.switch_target,
            "readback_target": self.readback_target,
            "rollback_readback_target": self.rollback_readback_target,
        }


def _guard(store):
    missing = [name for name in ("request_approval", "is_approved_for")
               if not hasattr(store, name)]
    if missing:
        raise ValueError("Guard store missing release approval support")


class GuardReleaseGate:
    """Bind an immutable release scope to one Guard/owner-approved pending request.

    The approval is stored in the existing Guard approval tables; no second
    database is introduced. A scope change requires a new run/request/approval.
    """

    RELEASE_ACTION = "production_deploy"

    def __init__(self, guard_store, registry_path):
        _guard(guard_store)
        self.store = guard_store
        self.registry = CutoverRegistry(registry_path)

    def prepare(self, scope, *, run_id=None, canon_revision=None,
                verified_predecessor_ref=None):
        if not isinstance(scope, ImmutableReleaseScope):
            raise ValueError("immutable release scope required")
        # A synthetic gate version is NOT a current Canon revision. The
        # authenticated host must supply its exact independently observed one.
        canon_revision = _text(canon_revision, "current Canon revision")
        if canon_revision == "release-gate/v1":
            raise ValueError("synthetic Canon revision is not authority")
        run_id = _text(run_id or ("release-" + secrets.token_hex(12)), "run_id")
        if not _RUN.fullmatch(run_id):
            raise ValueError("invalid run_id")
        incumbent = self.registry.get(scope.path)
        if incumbent is not None and incumbent.status == "VERIFIED":
            if (type(verified_predecessor_ref) is not str
                    or verified_predecessor_ref != incumbent.release_scope_ref
                    or scope.scope_ref == incumbent.release_scope_ref
                    or scope.previous_endpoint != incumbent.candidate_endpoint
                    or scope.candidate_authority == incumbent.candidate_authority):
                raise ValueError("verified incumbent release readback required")
        elif incumbent is not None and incumbent.status != "ROLLED_BACK":
            raise ValueError("cutover already active")
        effect_id = "release:" + scope.scope_ref
        target = "release-scope:" + scope.scope_ref
        created = self.store.request_approval(run_id, self.RELEASE_ACTION, target,
                                              canon_revision, effect_id)
        if not created:
            return {"ok": False, "status": "RUN_CONSUMED_OR_CONFLICT",
                    "run_id": run_id, "scope_ref": scope.scope_ref}
        row = self._request_row(run_id)
        if row is None:
            return {"ok": False, "status": "PENDING_UNAVAILABLE",
                    "run_id": run_id, "scope_ref": scope.scope_ref}
        request_ref = self._request_ref(run_id, row)
        self.registry.prepare(
            scope.path, scope.previous_authority, scope.previous_endpoint,
            scope.candidate_authority, scope.candidate_endpoint,
            scope.rollback_procedure, scope.switch_target, scope.readback_target,
            verified_predecessor_ref=verified_predecessor_ref,
            release_scope=scope.as_dict(), release_scope_ref=scope.scope_ref,
            release_run_id=run_id, release_request_ref=request_ref,
            release_canon_revision=canon_revision, rollback_readback_target=scope.rollback_readback_target,
        )
        return {"ok": True, "status": "WAITING_HUMAN", "run_id": run_id,
                "scope_ref": scope.scope_ref, "request_ref": request_ref,
                "release_permitted": False, "service_mutations": 0}

    def _request_row(self, run_id):
        with self.store._connect() as db:
            row = db.execute(
                "SELECT action,target,request_nonce,canon_revision,effect_id "
                "FROM approval_requests WHERE run_id=?", (run_id,)
            ).fetchone()
        if row is None or not row[3] or not row[4]:
            return None
        return row

    def _request_ref(self, run_id, row):
        return _store_request_ref(run_id, *row)

    # Deliberately no approve() method: an opaque request reference identifies
    # a Guard plan; it is not proof of the operator's identity or authority.
    # Approvals can ONLY be made through the existing authenticated UI/MCP
    # Operator decision path, never from this release metadata adapter.

    def verify(self, scope, run_id, request_ref, *, require_approved=True):
        if not isinstance(scope, ImmutableReleaseScope):
            raise ValueError("immutable release scope required")
        if not isinstance(run_id, str) or not _RUN.fullmatch(run_id):
            return {"ok": False, "status": "INVALID_RUN"}
        if not isinstance(request_ref, str) or not _REF.fullmatch(request_ref):
            return {"ok": False, "status": "INVALID_REQUEST_REF"}
        rec = self.registry.get(scope.path)
        if rec is None:
            return {"ok": False, "status": "RELEASE_SCOPE_NOT_PREPARED",
                    "scope_ref": scope.scope_ref}
        recorded = getattr(rec, "release_scope_ref", None) or (rec.release_scope if rec.release_scope is not None else None)
        if isinstance(recorded, dict):
            recorded = release_scope_ref(recorded)
        if recorded != scope.scope_ref or rec.release_run_id != run_id:
            return {"ok": False, "status": "RELEASE_SCOPE_MISMATCH",
                    "scope_ref": scope.scope_ref}
        if not isinstance(rec.release_request_ref, str) or not hmac.compare_digest(
                rec.release_request_ref, request_ref):
            return {"ok": False, "status": "REQUEST_REF_MISMATCH",
                    "scope_ref": scope.scope_ref, "approved": False}
        if not rec.release_canon_revision:
            return {"ok": False, "status": "CANON_REVISION_UNBOUND",
                    "scope_ref": scope.scope_ref, "approved": False}
        approved = self.store.is_approved_for(
            run_id, self.RELEASE_ACTION, "release-scope:" + scope.scope_ref,
            rec.release_canon_revision, "release:" + scope.scope_ref,
        )
        if require_approved and not approved:
            return {"ok": False, "status": "OWNER_APPROVAL_REQUIRED",
                    "scope_ref": scope.scope_ref, "approved": False}
        return {"ok": bool(approved) or not require_approved,
                "status": "APPROVED" if approved else "PENDING",
                "scope_ref": scope.scope_ref, "approved": approved,
                "release_permitted": False, "service_mutations": 0,
                "note": "Guard approval exists for this immutable scope; host service modification still requires separately verified release-scoped human gate and operator action."}


