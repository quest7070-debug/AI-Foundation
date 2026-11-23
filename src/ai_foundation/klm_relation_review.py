"""Host-only exact KLM review decisions using the existing durable Guard.

The host authenticates the owner and binds read_current to the original source
adapter. Neither arbitrary JSON nor a model-produced atom is a source reader.
No MCP tool, automatic approval, external write or source-text persistence.
"""
from dataclasses import dataclass
import sqlite3

from .core import CanonContract, Decision, TaskPlan
from .guard import GuardCore
from .knowledge_lifecycle import (
    HEX64, MAX_RECEIPTS, POLICY_VERSION, RELATIONS, SemanticAtom, _digest,
)

ACTION = "klm_relation_review"


def unresolved_review_filter(db, alias="r"):
    """Fixed SQL only, including backwards-compatible pre-disposition journals."""
    if alias != "r":
        raise ValueError("FIXED_REVIEW_ALIAS_REQUIRED")
    present = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='klm_relation_dispositions'").fetchone()
    return ("r.status='UNRESOLVED' AND NOT EXISTS "
            "(SELECT 1 FROM klm_relation_dispositions d WHERE d.review_key=r.review_key)"
            if present else "r.status='UNRESOLVED'")


@dataclass(frozen=True)
class RelationReviewIntent:
    run_id: str
    action: str
    target: str
    canon_revision: str
    effect_id: str


def _snapshot(db, review_key, scope):
    review = db.execute(
        "SELECT review_key,before_id,after_id,reason,status,policy "
        "FROM klm_relation_reviews WHERE review_key=?", (review_key,)).fetchone()
    if review is None or review[4:] != ("UNRESOLVED", POLICY_VERSION):
        raise ValueError("CURRENT_REVIEW_REQUIRED")
    rows = []
    for atom_id in review[1:3]:
        row = db.execute("SELECT * FROM klm_atoms WHERE atom_id=?", (atom_id,)).fetchone()
        feature = db.execute("SELECT * FROM klm_atom_features WHERE atom_id=?", (atom_id,)).fetchone()
        if row is None or feature is None or row[5] != scope or row[12] != POLICY_VERSION:
            raise PermissionError("CURRENT_SCOPED_ATOM_FEATURES_REQUIRED")
        rows.append((row, feature))
    if any(rows[0][0][i] != rows[1][0][i] for i in (1, 5, 6)):
        raise PermissionError("SOURCE_SCOPE_PRIVACY_BOUNDARY")
    return review, tuple(rows)


def _intent(snapshot, *, decision, relation_kind, authenticated_owner, scope, canon, run_id):
    if (type(authenticated_owner) is not str or not authenticated_owner.strip()
            or len(authenticated_owner) > 512
            or type(scope) is not str or not scope or scope == "*"
            or type(run_id) is not str or not 0 < len(run_id) <= 512
            or not isinstance(canon, CanonContract) or canon.clear is not True
            or not canon.revision):
        raise PermissionError("AUTHENTICATED_HOST_REVIEW_REQUIRED")
    if not ((decision == "ACCEPT" and relation_kind in RELATIONS)
            or (decision == "REJECT" and relation_kind == "")):
        raise ValueError("EXACT_REVIEW_DECISION_REQUIRED")
    digest = _digest((ACTION, authenticated_owner, scope, canon.revision,
                      snapshot, decision, relation_kind))
    return RelationReviewIntent(run_id, ACTION, "klm-review:" + digest,
                                canon.revision, digest)


def relation_review_intent(journal, *, review_key, decision, authenticated_owner,
                           scope, canon, run_id, relation_kind=""):
    """Build an exact opaque approval proposal; this is never authorization."""
    if type(review_key) is not str or HEX64.fullmatch(review_key) is None:
        raise ValueError("EXACT_REVIEW_KEY_REQUIRED")
    with sqlite3.connect(journal.path, timeout=5) as db:
        db.execute("BEGIN")
        snapshot = _snapshot(db, review_key, scope)
    return _intent(snapshot, decision=decision, relation_kind=relation_kind,
                   authenticated_owner=authenticated_owner, scope=scope,
                   canon=canon, run_id=run_id)


def _current(snapshot, read_current, *, authenticated_owner=None, scope=None):
    if not callable(read_current):
        raise PermissionError("HOST_SOURCE_READER_REQUIRED")
    from .klm_review_source import NativeKlmReviewReader
    if isinstance(read_current, NativeKlmReviewReader):
        if not read_current.bound_to(authenticated_owner, scope):
            raise PermissionError("SOURCE_OWNER_SCOPE_UNBOUND")
        for row, features in snapshot[1]:
            read_current.verify(read_current(row[0]), row, features)
        return
    for row, features in snapshot[1]:
        atom = read_current(row[0])
        if not isinstance(atom, SemanticAtom):
            raise PermissionError("CURRENT_SOURCE_ATOM_REQUIRED")
        s, m = atom.source, atom.meaning
        identity = {"policy": POLICY_VERSION, "owner_system": s.system,
                    "resource_id": s.resource_id, "record_id": s.record_id,
                    "revision": s.revision, "scope": s.scope,
                    "source_sha256": atom.source_sha256, "start": atom.byte_start,
                    "end": atom.byte_end, "span_sha256": atom.span_sha256,
                    "meaning": m.__dict__}
        actual = (atom.atom_id, s.system, s.resource_id, s.record_id, s.revision,
                  s.scope, s.privacy, atom.source_sha256, atom.span_sha256,
                  atom.byte_start, atom.byte_end, _digest(m.__dict__), POLICY_VERSION)
        actual_features = (atom.atom_id, _digest(m.subject), _digest(m.predicate),
                           _digest(m.object), _digest((m.condition, m.valid_from,
                           m.valid_until, m.modality, m.speaker_claim)), m.polarity, m.kind)
        if atom.atom_id != _digest(identity) or actual != row or actual_features != features:
            raise PermissionError("SOURCE_REVISION_OR_MEANING_CHANGED")


def _allowed(guard, canon, intent):
    if not isinstance(guard, GuardCore):
        return False
    store = guard.store
    if store is None or not callable(getattr(store, "is_approved_for", None)):
        return False
    if store.is_approved_for(intent.run_id, intent.action, intent.target,
                             intent.canon_revision, intent.effect_id) is not True:
        return False
    plan = TaskPlan(intent.run_id, intent.action, intent.target,
                    canon_revision=intent.canon_revision, effect_id=intent.effect_id,
                    paid_cost=0, privacy_text="")
    return guard.preflight(plan, canon) in (Decision.ALLOW, Decision.LOCAL_ONLY)


def request_relation_review(journal, *, guard, read_current, **kwargs):
    """Stage one existing Guard pending request, never approve it."""
    if not isinstance(guard, GuardCore) or guard.store is None:
        raise PermissionError("DURABLE_GUARD_REQUIRED")
    intent = relation_review_intent(journal, **kwargs)
    with sqlite3.connect(journal.path, timeout=5) as db:
        snapshot = _snapshot(db, kwargs["review_key"], kwargs["scope"])
    _current(snapshot, read_current, authenticated_owner=kwargs["authenticated_owner"],
             scope=kwargs["scope"])
    # Recheck candidate identity after the potentially slow source reader.
    if relation_review_intent(journal, **kwargs) != intent:
        raise PermissionError("REVIEW_CHANGED")
    if _allowed(guard, kwargs["canon"], intent):
        return {"status": "APPROVED", "run_id": intent.run_id}
    if not guard.store.request_approval(intent.run_id, intent.action, intent.target,
                                         intent.canon_revision, intent.effect_id):
        raise PermissionError("REVIEW_RUN_ALREADY_CONSUMED")
    return {"status": "WAITING_HUMAN", "run_id": intent.run_id}


def resolve_relation_review(journal, *, guard, read_current, **kwargs):
    """Commit one current host decision; exact repeats perform no mutation."""
    intent = relation_review_intent(journal, **kwargs)
    canon = kwargs["canon"]
    if not _allowed(guard, canon, intent):
        raise PermissionError("EXACT_GUARD_REVIEW_REQUIRED")
    with sqlite3.connect(journal.path, timeout=5) as db:
        snapshot = _snapshot(db, kwargs["review_key"], kwargs["scope"])
    _current(snapshot, read_current, authenticated_owner=kwargs["authenticated_owner"],
             scope=kwargs["scope"])
    with sqlite3.connect(journal.path, timeout=5) as db:
        db.execute("BEGIN IMMEDIATE")
        current = _snapshot(db, kwargs["review_key"], kwargs["scope"])
        expected = _intent(current, decision=kwargs["decision"],
                           relation_kind=kwargs.get("relation_kind", ""),
                           authenticated_owner=kwargs["authenticated_owner"],
                           scope=kwargs["scope"], canon=canon, run_id=kwargs["run_id"])
        if expected != intent or not _allowed(guard, canon, intent):
            raise PermissionError("REVIEW_CHANGED_OR_CANCELLED")
        values = (kwargs["review_key"], intent.effect_id, kwargs["decision"],
                  kwargs.get("relation_kind", ""), _digest(intent.run_id), canon.revision)
        old = db.execute("SELECT * FROM klm_relation_dispositions WHERE review_key=?",
                         (kwargs["review_key"],)).fetchone()
        if old is not None:
            if old != values:
                raise PermissionError("IMMUTABLE_REVIEW_DECISION_CONFLICT")
            return {"status": "ALREADY_RECORDED", "decision": old[2]}
        if db.execute("SELECT COUNT(*) FROM klm_relation_dispositions").fetchone()[0] >= MAX_RECEIPTS:
            raise RuntimeError("RELATION_DISPOSITION_CAPACITY_REACHED")
        if kwargs["decision"] == "ACCEPT":
            a, b = current[0][1:3]
            kind = kwargs["relation_kind"]
            key = _digest((POLICY_VERSION, a, b, kind))
            old_relation = db.execute("SELECT source_atom_id,target_atom_id,kind,status,policy "
                                      "FROM klm_relations WHERE relation_key=?", (key,)).fetchone()
            if old_relation is not None and old_relation not in (
                    (a, b, kind, "proposed", POLICY_VERSION),
                    (a, b, kind, "owner_verified", POLICY_VERSION)):
                raise PermissionError("RELATION_IDENTITY_CONFLICT")
            if old_relation is None:
                if db.execute("SELECT COUNT(*) FROM klm_relations").fetchone()[0] >= MAX_RECEIPTS:
                    raise RuntimeError("RELATION_CAPACITY_REACHED")
                db.execute("INSERT INTO klm_relations VALUES(?,?,?,?,?,?)",
                           (key, a, b, kind, "owner_verified", POLICY_VERSION))
            else:
                db.execute("UPDATE klm_relations SET status='owner_verified' WHERE relation_key=?", (key,))
        db.execute("INSERT INTO klm_relation_dispositions VALUES(?,?,?,?,?,?)", values)
    with sqlite3.connect(journal.path, timeout=5) as db:
        if db.execute("SELECT * FROM klm_relation_dispositions WHERE review_key=?",
                      (kwargs["review_key"],)).fetchone() != values:
            raise RuntimeError("REVIEW_READBACK_MISMATCH")
    return {"status": "RECORDED", "decision": kwargs["decision"]}
