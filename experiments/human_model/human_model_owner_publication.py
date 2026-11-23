"""Exact, authenticated-owner publication into the EXISTING HumanModel Ledger.

This is an owner-side library, not a service or external request handler.
The canonical host must authenticate the owner and supply the existing
authorization/consent verifier and source reader; no caller-controlled model
text may become a grant, a reader, or a publisher.

This module never creates another DB, never silently migrates a live ledger,
never rebuilds a view or grants execution authority. Schema preparation is an
explicit host-controlled migration step; public receipts expose only codes.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import sqlite3
from uuid import uuid4

from human_model_ledger import Ledger
from human_model_source_admission import HostCollectionGrant, stage_exact_source

_SCHEMA = """
CREATE TABLE IF NOT EXISTS human_source_admissions (
  evidence_id TEXT PRIMARY KEY REFERENCES evidence(id),
  version INTEGER NOT NULL CHECK(version = 2),
  owner_binding_sha256 TEXT NOT NULL,
  source_system TEXT NOT NULL,
  source_record_id_sha256 TEXT NOT NULL,
  source_record_id TEXT NOT NULL,
  source_revision TEXT NOT NULL,
  source_sha256 TEXT NOT NULL,
  consent_id_sha256 TEXT NOT NULL,
  consent_revision TEXT NOT NULL,
  purpose TEXT NOT NULL,
  attestation TEXT NOT NULL CHECK(attestation = 'HOST_VERIFIED_OWNER_SOURCE'),
  recorded_at TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(state IN ('ACTIVE','STALE','WITHDRAWN')),
  withdrawn_at TEXT
);
"""
_COLUMNS = {
    "evidence_id", "version", "owner_binding_sha256", "source_system",
    "source_record_id_sha256", "source_record_id", "source_revision", "source_sha256",
    "consent_id_sha256", "consent_revision", "purpose", "attestation",
    "recorded_at", "state", "withdrawn_at",
}


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def prepare_admission_schema(ledger: Ledger) -> None:
    """Explicit, one-time owner migration. NEVER call on a generic read path.

    A real host must independently authorize this schema migration before
    activation. Its synthetic tests use a disposable SQLite Ledger.
    """
    if type(ledger) is not Ledger:
        raise TypeError("EXISTING_LEDGER_REQUIRED")
    with ledger.db:
        ledger.db.execute(_SCHEMA)


def _assert_prepared(db: sqlite3.Connection) -> None:
    columns = {row[1] for row in db.execute(
        "PRAGMA table_info(human_source_admissions)")}
    if columns != _COLUMNS:
        raise RuntimeError("OWNER_ADMISSION_SCHEMA_NOT_PREPARED")


@dataclass(frozen=True)
class PublicationResult:
    """Private host result; never publish the evidence ID in status telemetry."""
    evidence_id: str
    created: bool

    def safe_receipt(self) -> dict:
        return {
            "status": "SOURCE_PUBLISHED" if self.created else "SOURCE_ALREADY_CURRENT",
            "evidence_kind": "observation",
            "actor_proof": "HOST_VERIFIED",
            "person_fact_approved": False,
            "execution_authority": False,
        }


def publish_exact_owner_observation(
    ledger: Ledger,
    grant: HostCollectionGrant,
    *,
    current_authenticated_owner: str,
    grant_verifier,
    read_current,
    corrects_evidence_id: str | None = None,
    authorize_correction=None,
) -> PublicationResult:
    """Revalidate exact owner/consent/source then atomically insert+attest.

    Only direct, authenticated owner text is accepted, always private and
    kind=observation. Never interpret that text as consent, a personal trait,
    an approval or a trusted command. No unknown/stale source is published.
    """
    if type(ledger) is not Ledger:
        raise TypeError("EXISTING_LEDGER_REQUIRED")
    _assert_prepared(ledger.db)
    source = stage_exact_source(
        grant,
        current_authenticated_owner=current_authenticated_owner,
        grant_verifier=grant_verifier,
        read_current=read_current,
    )
    # Even after two source reads, the grant may have been revoked. This
    # checks current host authority immediately before the SQLite write.
    try:
        current_grant = grant_verifier(grant)
    except Exception:
        raise PermissionError("CURRENT_GRANT_UNAVAILABLE") from None
    if current_grant is not True:
        raise PermissionError("COLLECTION_CONSENT_UNAVAILABLE")

    if corrects_evidence_id is not None:
        if (type(corrects_evidence_id) is not str or
                not 1 <= len(corrects_evidence_id) <= 128 or
                not callable(authorize_correction)):
            raise PermissionError("EXACT_OWNER_CORRECTION_AUTHORITY_REQUIRED")
        try:
            permitted_correction = authorize_correction(
                source.owner_id, corrects_evidence_id, grant)
        except Exception:
            raise PermissionError("OWNER_CORRECTION_UNAVAILABLE") from None
        if permitted_correction is not True:
            raise PermissionError("OWNER_CORRECTION_DENIED")

    owner_hash = _digest(source.owner_id)
    record_hash = _digest(grant.source_record_id)
    consent_hash = _digest(source.consent_id)
    identity = (
        2, owner_hash, grant.source_system, record_hash,
        grant.source_record_id,
        source.source_revision, source.content_sha256,
        consent_hash, source.consent_revision, source.purpose,
        "HOST_VERIFIED_OWNER_SOURCE",
    )
    try:
        with ledger.db:
            existing = ledger.db.execute(
                "SELECT id,kind,scope,privacy,content,content_sha256,"
                "observed_at,supersedes,disputed FROM evidence "
                "WHERE source_uri=? AND source_revision=?",
                (source.source_uri, source.source_revision),
            ).fetchone()
            if existing:
                eid, kind, scope, privacy, text, digest, observed, supersedes, disputed = existing
                if ((kind, scope, privacy, text, digest, observed, supersedes, disputed)
                        != ("observation", source.scope, "private", source.content,
                            source.content_sha256, source.observed_at, corrects_evidence_id, 0)):
                    raise ValueError("SOURCE_REVISION_CONFLICT")
                proof = ledger.db.execute(
                    "SELECT version,owner_binding_sha256,source_system,"
                    "source_record_id_sha256,source_record_id,source_revision,source_sha256,"
                    "consent_id_sha256,consent_revision,purpose,attestation,state "
                    "FROM human_source_admissions WHERE evidence_id=?",
                    (eid,),
                ).fetchone()
                if not proof or proof[:-1] != identity:
                    raise PermissionError("EXISTING_SOURCE_NOT_ATTESTED")
                if proof[-1] == "WITHDRAWN":
                    raise PermissionError("SOURCE_PREVIOUSLY_WITHDRAWN")
                if proof[-1] != "ACTIVE":
                    raise PermissionError("SOURCE_REVISION_STALE")
                return PublicationResult(eid, False)

            if corrects_evidence_id is not None:
                original = ledger.db.execute(
                    "SELECT e.kind,e.scope,e.privacy,a.owner_binding_sha256,a.state "
                    "FROM evidence e LEFT JOIN human_source_admissions a "
                    "ON a.evidence_id=e.id WHERE e.id=?",
                    (corrects_evidence_id,),
                ).fetchone()
                if (not original or original != (
                        "observation", source.scope, "private", owner_hash, "ACTIVE")):
                    raise PermissionError("CORRECTION_SOURCE_NOT_AUTHENTICATED")
                if ledger.db.execute(
                        "SELECT 1 FROM evidence WHERE supersedes=?",
                        (corrects_evidence_id,)).fetchone():
                    raise ValueError("CORRECTION_ALREADY_SUPERSEDED")
            eid = str(uuid4())
            ledger.db.execute(
                "INSERT INTO evidence "
                "(id,source_uri,source_revision,observed_at,captured_at,"
                "kind,scope,privacy,content,content_sha256,supersedes,disputed) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (eid, source.source_uri, source.source_revision, source.observed_at,
                 datetime.now(timezone.utc).isoformat(), "observation", source.scope,
                 "private", source.content, source.content_sha256, corrects_evidence_id, 0),
            )
            ledger.db.execute(
                "INSERT INTO human_source_admissions "
                "(evidence_id,version,owner_binding_sha256,source_system,"
                "source_record_id_sha256,source_record_id,source_revision,source_sha256,"
                "consent_id_sha256,consent_revision,purpose,attestation,recorded_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (eid, *identity, datetime.now(timezone.utc).isoformat()),
            )
            ledger.db.execute(
                "INSERT INTO change_log(evidence_id,action,at) VALUES(?,?,?)",
                (eid, "insert", datetime.now(timezone.utc).isoformat()),
            )
            ledger.db.execute("UPDATE model_views SET stale=1")
            return PublicationResult(eid, True)
    except sqlite3.Error:
        # SQL exceptions may contain private material. Only fixed codes
        # escape the owner-side writer.
        raise RuntimeError("SOURCE_PUBLICATION_UNAVAILABLE") from None


@dataclass(frozen=True)
class WithdrawalResult:
    """Private owner result, not a source-data export."""
    evidence_id: str
    changed: bool

    def safe_receipt(self):
        return {
            "status": "SOURCE_WITHDRAWN" if self.changed else "SOURCE_ALREADY_WITHDRAWN",
            "source_available_to_view": False,
            "original_erasure_proven": False,
            "execution_authority": False,
        }


def withdraw_attested_owner_source(
    ledger: Ledger,
    evidence_id: str,
    *,
    current_authenticated_owner: str,
    authorize_withdrawal,
) -> WithdrawalResult:
    """Host-authorized provision withdrawal, not physical erasure.

    Existing View is invalidated immediately, and the owner-side projection
    excludes this source on rebuild. Raw originals and prior audit log are
    intentionally preserved pending an independent erasure contract.
    Revocation must work even if the original collection grant has expired.
    """
    if type(ledger) is not Ledger:
        raise TypeError("EXISTING_LEDGER_REQUIRED")
    _assert_prepared(ledger.db)
    if (type(evidence_id) is not str or not 1 <= len(evidence_id) <= 128 or
            not isinstance(current_authenticated_owner, str) or
            not current_authenticated_owner.strip() or
            not callable(authorize_withdrawal)):
        raise PermissionError("OWNER_WITHDRAWAL_AUTHORITY_REQUIRED")
    try:
        decision = authorize_withdrawal(
            current_authenticated_owner, evidence_id)
    except Exception:
        raise PermissionError("OWNER_WITHDRAWAL_UNAVAILABLE") from None
    if decision is not True:
        raise PermissionError("OWNER_WITHDRAWAL_DENIED")
    try:
        with ledger.db:
            row = ledger.db.execute(
                "SELECT owner_binding_sha256,state FROM human_source_admissions "
                "WHERE evidence_id=?", (evidence_id,)
            ).fetchone()
            if not row or row[0] != _digest(current_authenticated_owner):
                raise PermissionError("OWNER_SOURCE_NOT_BOUND")
            if row[1] == "WITHDRAWN":
                return WithdrawalResult(evidence_id, False)
            if row[1] not in ("ACTIVE", "STALE"):
                raise RuntimeError("OWNER_SOURCE_UNKNOWN_STATE")
            now = datetime.now(timezone.utc).isoformat()
            ledger.db.execute(
                "UPDATE human_source_admissions SET state='WITHDRAWN',withdrawn_at=? "
                "WHERE evidence_id=? AND state IN ('ACTIVE','STALE')",
                (now, evidence_id),
            )
            ledger.db.execute("UPDATE model_views SET stale=1")
            ledger.db.execute(
                "INSERT INTO change_log(evidence_id,action,at) VALUES(?,?,?)",
                (evidence_id, "withdraw", now),
            )
            return WithdrawalResult(evidence_id, True)
    except sqlite3.Error:
        raise RuntimeError("OWNER_WITHDRAWAL_STORAGE_UNAVAILABLE") from None



@dataclass(frozen=True)
class SourceReconciliation:
    evidence_id: str
    status: str

    def safe_receipt(self):
        return {"status": self.status,
                "source_content_exposed": False,
                "execution_authority": False}


def reconcile_attested_source_revision(
    ledger: Ledger,
    evidence_id: str,
    *,
    current_authenticated_owner: str,
    read_current,
) -> SourceReconciliation:
    """Owner-side source drift check; no model, no Raw projection.

    Called from a trusted source event or the existing KLM audit port. A
    missing/changed source is excluded from future Views. An unavailable
    source is also excluded conservatively until a reviewed fresh update;
    this is not physical deletion or a user withdrawal.
    """
    from human_model_source_admission import TrustedSourceSnapshot
    if type(ledger) is not Ledger:
        raise TypeError("EXISTING_LEDGER_REQUIRED")
    _assert_prepared(ledger.db)
    if (type(evidence_id) is not str or not 1 <= len(evidence_id) <= 128
            or type(current_authenticated_owner) is not str
            or not current_authenticated_owner
            or not callable(read_current)):
        raise PermissionError("OWNER_SOURCE_RECONCILE_AUTHORITY_REQUIRED")
    row = ledger.db.execute(
        "SELECT e.source_uri,e.source_revision,e.content_sha256,"
        "a.source_system,a.source_record_id_sha256,a.source_record_id,"
        "a.owner_binding_sha256,a.state FROM human_source_admissions a "
        "JOIN evidence e ON e.id=a.evidence_id WHERE a.evidence_id=?",
        (evidence_id,),
    ).fetchone()
    if not row or row[6] != _digest(current_authenticated_owner):
        raise PermissionError("OWNER_SOURCE_NOT_BOUND")
    if row[7] != "ACTIVE":
        return SourceReconciliation(evidence_id, "SOURCE_NOT_ACTIVE")
    source_uri, source_revision, source_sha, system, record_id_sha, record_id, _, _ = row
    current = None
    try:
        current = read_current(system, record_id)
    except Exception:
        # A missing source is not proof it is unchanged.
        pass
    still_current = (
        type(current) is TrustedSourceSnapshot
        and current.source_system == system
        and current.source_uri == source_uri
        and type(current.source_record_id) is str
        and current.source_record_id == record_id
        and _digest(current.source_record_id) == record_id_sha
        and current.source_revision == source_revision
        and current.actor_verified is True
        and current.actor_kind == "owner"
        and current.actor_principal_id == current_authenticated_owner
        and current.complete is True
        and type(current.content) is str
        and _digest(current.content) == source_sha
    )
    if still_current:
        return SourceReconciliation(evidence_id, "SOURCE_STILL_CURRENT")
    try:
        with ledger.db:
            changed = ledger.db.execute(
                "UPDATE human_source_admissions SET state='STALE' "
                "WHERE evidence_id=? AND state='ACTIVE'",
                (evidence_id,),
            ).rowcount
            if changed:
                ledger.db.execute("UPDATE model_views SET stale=1")
                ledger.db.execute(
                    "INSERT INTO change_log(evidence_id,action,at) VALUES(?,?,?)",
                    (evidence_id, "source_stale",
                     datetime.now(timezone.utc).isoformat()),
                )
            return SourceReconciliation(
                evidence_id, "SOURCE_STALE" if changed else "SOURCE_NOT_ACTIVE")
    except sqlite3.Error:
        raise RuntimeError("SOURCE_RECONCILE_STORAGE_UNAVAILABLE") from None



@dataclass(frozen=True)
class CollectionConsentRevocation:
    withdrawn_count: int
    def safe_receipt(self):
        return {
            "status": "CONSENT_REVOKED_LOCAL_ONLY",
            "withdrawn_sources": self.withdrawn_count,
            "source_content_exposed": False,
            "original_erasure_proven": False,
            "execution_authority": False,
        }


def reconcile_cancelled_collection_consent(
    ledger: Ledger,
    consent_run_id: str,
    *,
    current_authenticated_owner: str,
    is_guard_cancelled,
) -> CollectionConsentRevocation:
    """Existing Guard cancellation -> local source-service withdrawal.

    The authenticated host supplies the exact cancelled Guard run ID and its
    canonical read-only cancellation checker. This function never approves
    a new collection or imports personal text. Old source rows remain owned
    by HumanModel for audit until a separately authorized erasure path exists.
    """
    if type(ledger) is not Ledger:
        raise TypeError("EXISTING_LEDGER_REQUIRED")
    _assert_prepared(ledger.db)
    if (type(consent_run_id) is not str or not consent_run_id.strip()
            or len(consent_run_id) > 128
            or type(current_authenticated_owner) is not str
            or not current_authenticated_owner.strip()
            or not callable(is_guard_cancelled)):
        raise PermissionError("GUARD_CANCEL_IDENTITY_REQUIRED")
    try:
        cancelled = is_guard_cancelled(consent_run_id)
    except Exception:
        raise PermissionError("GUARD_CANCEL_UNAVAILABLE") from None
    if cancelled is not True:
        raise PermissionError("GUARD_CANCEL_NOT_PROVEN")
    try:
        with ledger.db:
            ids = [x[0] for x in ledger.db.execute(
                "SELECT evidence_id FROM human_source_admissions "
                "WHERE consent_id_sha256=? AND owner_binding_sha256=? "
                "AND state!='WITHDRAWN'",
                (_digest(consent_run_id), _digest(current_authenticated_owner)),
            )]
            for eid in ids:
                ledger.db.execute(
                    "UPDATE human_source_admissions SET state='WITHDRAWN',"
                    "withdrawn_at=? WHERE evidence_id=?",
                    (datetime.now(timezone.utc).isoformat(), eid),
                )
                ledger.db.execute(
                    "INSERT INTO change_log(evidence_id,action,at) VALUES(?,?,?)",
                    (eid, "consent_revoked", datetime.now(timezone.utc).isoformat()),
                )
            if ids:
                ledger.db.execute("UPDATE model_views SET stale=1")
            return CollectionConsentRevocation(len(ids))
    except sqlite3.Error:
        raise RuntimeError("GUARD_CONSENT_REVOKE_STORAGE_UNAVAILABLE") from None



def owner_lifecycle_tick(
    ledger: Ledger,
    *,
    current_authenticated_owner: str,
    consent_current,
    read_current,
    max_records: int = 128,
) -> dict:
    """Bounded, model-free owner maintenance for the existing periodic host.

    The host supplies its CURRENT Guard-derived consent checker and owner-source
    reader. Unknown consent and missing/changed source are STALE, never silently
    approved or re-imported. No inference lease, new daemon or cloud fallback.
    It is safe to replay: each active proof is retired only once.
    """
    if type(ledger) is not Ledger:
        raise TypeError("EXISTING_LEDGER_REQUIRED")
    _assert_prepared(ledger.db)
    if (type(current_authenticated_owner) is not str
            or not current_authenticated_owner.strip()
            or not callable(consent_current) or not callable(read_current)
            or type(max_records) is not int or not 1 <= max_records <= 512):
        raise PermissionError("OWNER_LIFECYCLE_HOST_BINDING_REQUIRED")
    try:
        proofs = ledger.db.execute(
            "SELECT evidence_id,consent_id_sha256 FROM human_source_admissions "
            "WHERE owner_binding_sha256=? AND state='ACTIVE' "
            "ORDER BY evidence_id LIMIT ?",
            (_digest(current_authenticated_owner), max_records + 1),
        ).fetchall()
    except sqlite3.Error:
        return {"status": "OWNER_LIFECYCLE_UNAVAILABLE",
                "execution_authority": False}
    if len(proofs) > max_records:
        return {"status": "OWNER_LIFECYCLE_INCOMPLETE",
                "examined": 0, "source_current": 0,
                "source_stale": 0, "consent_unavailable": 0,
                "execution_authority": False}
    counters = {"examined": 0, "source_current": 0,
                "source_stale": 0, "consent_unavailable": 0}
    for evidence_id, consent_digest in proofs:
        counters["examined"] += 1
        try:
            is_current = consent_current(consent_digest) is True
        except Exception:
            is_current = False
        if is_current:
            evidence = reconcile_attested_source_revision(
                ledger, evidence_id,
                current_authenticated_owner=current_authenticated_owner,
                read_current=read_current,
            )
            # Consent can be revoked while the source is being read; check
            # a second time before letting a source stay ACTIVE.
            if evidence.status == "SOURCE_STILL_CURRENT":
                try:
                    is_current = consent_current(consent_digest) is True
                except Exception:
                    is_current = False
                if is_current:
                    counters["source_current"] += 1
                    continue
            if evidence.status == "SOURCE_STALE":
                counters["source_stale"] += 1
                continue
        # Indeterminate consent is not an owner's explicit withdrawal; keep
        # original for audit while denying serving from future Views.
        try:
            with ledger.db:
                changed = ledger.db.execute(
                    "UPDATE human_source_admissions SET state='STALE' "
                    "WHERE evidence_id=? AND state='ACTIVE'",
                    (evidence_id,),
                ).rowcount
                if changed:
                    ledger.db.execute("UPDATE model_views SET stale=1")
                    ledger.db.execute(
                        "INSERT INTO change_log(evidence_id,action,at) "
                        "VALUES (?,?,?)",
                        (evidence_id, "consent_unavailable",
                         datetime.now(timezone.utc).isoformat()),
                    )
        except sqlite3.Error:
            return {"status": "OWNER_LIFECYCLE_UNAVAILABLE",
                    **counters, "execution_authority": False}
        counters["consent_unavailable"] += 1
    return {"status": "OWNER_LIFECYCLE_VERIFIED"
            if counters["source_stale"] == counters["consent_unavailable"] == 0
            else "OWNER_LIFECYCLE_REVIEW_REQUIRED",
            **counters, "execution_authority": False}
