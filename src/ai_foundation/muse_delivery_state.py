"""Evidence-gated Muse delivery lifecycle. Standalone, never dispatches or authorizes work.

Legacy dispatched rows mean *UI submission attempted*, NOT success.
All transitions require event evidence, and the terminal verified state
requires independently supplied report verification evidence.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import sqlite3
from typing import Optional

STAGES = ("DISCOVERED", "UI_SUBMISSION_ATTEMPTED", "MUSE_ACCEPTED", "REPORT_CREATED", "REPORT_VERIFIED")
NEXT = {STAGES[i]: STAGES[i + 1] for i in range(len(STAGES) - 1)}
REQUEST = re.compile(r"^REQ-\d{8}-\d{3}$")
UTC = dt.timezone.utc


class EvidenceError(ValueError):
    pass


def initialize(db: sqlite3.Connection) -> None:
    db.execute("""
      CREATE TABLE IF NOT EXISTS muse_delivery_events (
        request_id TEXT NOT NULL,
        stage TEXT NOT NULL,
        evidence_ref TEXT NOT NULL,
        event_time TEXT NOT NULL,
        PRIMARY KEY (request_id, stage),
        CHECK (stage IN ('DISCOVERED','UI_SUBMISSION_ATTEMPTED','MUSE_ACCEPTED',
                         'REPORT_CREATED','REPORT_VERIFIED'))
      )""")
    db.execute("""
      CREATE TABLE IF NOT EXISTS muse_report_verification (
        request_id TEXT PRIMARY KEY,
        correlation_id TEXT NOT NULL,
        report_sha256 TEXT NOT NULL,
        report_source_ref TEXT NOT NULL,
        evidence_ref TEXT NOT NULL UNIQUE
      )""")
    db.execute("""
      CREATE TABLE IF NOT EXISTS muse_stage_receipts (
        request_id TEXT NOT NULL,
        stage TEXT NOT NULL,
        evidence_ref TEXT NOT NULL,
        correlation_id TEXT NOT NULL,
        PRIMARY KEY(request_id, stage)
      )""")
    db.execute("""
      CREATE TABLE IF NOT EXISTS muse_independent_reviews (
        request_id TEXT PRIMARY KEY,
        correlation_id TEXT NOT NULL,
        report_sha256 TEXT NOT NULL,
        reviewer_id TEXT NOT NULL,
        review_evidence_ref TEXT NOT NULL,
        decision TEXT NOT NULL CHECK(decision IN ('ACCEPT','REJECT'))
      )""")
    db.commit()


def attest_stage(db: sqlite3.Connection, request_id: str, stage: str,
                 evidence_ref: str, correlation_id: str) -> None:
    """Bind verified adapter readback to a stage before state advancement.

    This is a local consistency gate, NOT provider authentication.
    """
    if stage not in ("MUSE_ACCEPTED", "REPORT_CREATED"):
        raise EvidenceError("stage is not adapter-attestable")
    if not REQUEST.fullmatch(request_id) or not evidence_ref or not correlation_id:
        raise EvidenceError("missing receipt identity")
    existing = db.execute(
        "SELECT evidence_ref, correlation_id FROM muse_stage_receipts "
        "WHERE request_id=? AND stage=?", (request_id, stage)
    ).fetchone()
    if existing and existing != (evidence_ref, correlation_id):
        raise EvidenceError("stage attestation immutable")
    if not existing:
        with db:
            db.execute("INSERT INTO muse_stage_receipts VALUES (?,?,?,?)",
                       (request_id, stage, evidence_ref, correlation_id))


def verify_report(db: sqlite3.Connection, request_id: str,
                  expected_correlation_id: str, report_content: str,
                  source_ref: str) -> str:
    """Verify observed Drive report content and bind a receipt to its exact hash.

    Caller must independently establish source_ref from a Drive readback.
    This validates identity and structure, not the truth of research claims.
    """
    if not REQUEST.fullmatch(request_id) or not expected_correlation_id.strip():
        raise EvidenceError("invalid report identity")
    if not source_ref.startswith("drive-file-id:") or len(source_ref) <= 14:
        raise EvidenceError("Drive provenance reference required")
    try:
        payload = json.loads(report_content.lstrip("\ufeff"))
    except (ValueError, TypeError) as exc:
        raise EvidenceError("invalid report JSON") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise EvidenceError("unexpected report schema")
    if payload.get("producer") != "muse" or payload.get("correlation_id") != expected_correlation_id:
        raise EvidenceError("report identity mismatch")
    if not isinstance(payload.get("findings"), list) or not payload["findings"]:
        raise EvidenceError("report findings missing")
    if not all(isinstance(f, dict) and isinstance(f.get("source_url"), str)
               and isinstance(f.get("claim"), str) for f in payload["findings"]):
        raise EvidenceError("invalid findings structure")
    digest = hashlib.sha256(report_content.encode("utf-8")).hexdigest()
    ref = "independent:drive-content-sha256:" + digest
    existing = db.execute("SELECT evidence_ref FROM muse_report_verification WHERE request_id=?",
                          (request_id,)).fetchone()
    if existing:
        if existing[0] != ref:
            raise EvidenceError("report revision differs from verification receipt")
        return ref
    with db:
        db.execute("INSERT INTO muse_report_verification VALUES (?,?,?,?,?)",
                   (request_id, expected_correlation_id, digest, source_ref, ref))
    return ref


def record_independent_review(
    db: sqlite3.Connection, request_id: str, expected_correlation_id: str,
    report_sha256: str, *, reviewer_id: str, review_evidence_ref: str,
    decision: str,
) -> None:
    """Persist an explicit external review decision.

    Review provenance must be checked by a trusted host before calling.
    This module never asserts the reviewer actually examined the claims.
    """
    if decision not in ("ACCEPT", "REJECT"):
        raise EvidenceError("explicit ACCEPT or REJECT decision required")
    if not reviewer_id.strip() or reviewer_id.strip().lower() == "muse":
        raise EvidenceError("an independent reviewer identity is required")
    if not review_evidence_ref.startswith("review-id:") or len(review_evidence_ref) <= 10:
        raise EvidenceError("review artifact reference required")
    row = db.execute(
        "SELECT correlation_id, report_sha256 FROM muse_report_verification WHERE request_id=?",
        (request_id,),
    ).fetchone()
    if row != (expected_correlation_id, report_sha256):
        raise EvidenceError("independent review must bind existing report hash and identity")
    current = db.execute(
        "SELECT correlation_id,report_sha256,reviewer_id,review_evidence_ref,decision "
        "FROM muse_independent_reviews WHERE request_id=?", (request_id,),
    ).fetchone()
    payload = (expected_correlation_id, report_sha256, reviewer_id, review_evidence_ref, decision)
    if current and current != payload:
        raise EvidenceError("independent decision is immutable")
    if not current:
        with db:
            db.execute(
                "INSERT INTO muse_independent_reviews VALUES (?,?,?,?,?,?)",
                (request_id,) + payload,
            )


def record(db: sqlite3.Connection, request_id: str, stage: str,
           evidence_ref: str, *, event_time: Optional[str] = None,
           signed_review=None, trusted_public_key_bytes: bytes | None = None,
           expected_reviewer_id: str | None = None,
           signed_muse_run=None,
           trusted_scheduler_public_key: bytes | None = None,
           expected_scheduler_id: str | None = None) -> None:
    if not REQUEST.fullmatch(request_id) or stage not in STAGES:
        raise EvidenceError("invalid request or stage")
    if not isinstance(evidence_ref, str) or not evidence_ref.strip():
        raise EvidenceError("evidence reference is mandatory")
    if stage in ("MUSE_ACCEPTED", "REPORT_CREATED"):
        receipt = db.execute(
            "SELECT 1 FROM muse_stage_receipts WHERE request_id=? AND stage=? AND evidence_ref=?",
            (request_id, stage, evidence_ref)
        ).fetchone()
        if not receipt:
            raise EvidenceError("verified adapter stage receipt required")
    if stage == "MUSE_ACCEPTED":
        # A local stage receipt or caller-supplied origin is not authentication.
        from .muse_signed_run import verify_signed_muse_run
        if (signed_muse_run is None or trusted_scheduler_public_key is None
                or not expected_scheduler_id):
            raise EvidenceError("signed scheduler verification context required")
        if (signed_muse_run.request_id != request_id
                or "muse-run-readback:" + signed_muse_run.run_id != evidence_ref):
            raise EvidenceError("signed scheduler evidence does not bind this stage")
        verify_signed_muse_run(
            signed_muse_run,
            trusted_public_key_bytes=trusted_scheduler_public_key,
            expected_scheduler_id=expected_scheduler_id,
        )
    if stage == "REPORT_VERIFIED":
        receipt = db.execute("SELECT 1 FROM muse_report_verification WHERE request_id=? AND evidence_ref=?",
                             (request_id, evidence_ref)).fetchone()
        if not receipt:
            raise EvidenceError("verified report receipt required; reference alone is insufficient")
        independent = db.execute(
            "SELECT 1 FROM muse_independent_reviews r "
            "JOIN muse_report_verification v ON v.request_id=r.request_id "
            "AND v.correlation_id=r.correlation_id AND v.report_sha256=r.report_sha256 "
            "WHERE r.request_id=? AND r.decision='ACCEPT' AND v.evidence_ref=?",
            (request_id, evidence_ref),
        ).fetchone()
        if not independent:
            raise EvidenceError("independent acceptance decision required")
        try:
            signature_receipt = db.execute(
                "SELECT 1 FROM muse_signed_review_receipts s "
                "JOIN muse_report_verification v ON v.request_id=s.request_id "
                "AND v.correlation_id=s.correlation_id AND v.report_sha256=s.report_sha256 "
                "JOIN muse_independent_reviews r ON r.request_id=s.request_id "
                "AND r.reviewer_id=s.reviewer_id AND r.review_evidence_ref='review-id:' || s.review_id "
                "AND r.decision='ACCEPT' "
                "WHERE s.request_id=? AND v.evidence_ref=?", (request_id, evidence_ref)
            ).fetchone()
        except sqlite3.OperationalError:
            signature_receipt = None
        if not signature_receipt:
            raise EvidenceError("operator-pinned signed review receipt required")
        # A mutable SQLite receipt is not a trust boundary. Verify the
        # exact signed assertion under the operator-pinned key *again*
        # at the point of final state transition.
        if (signed_review is None or trusted_public_key_bytes is None
                or not expected_reviewer_id):
            raise EvidenceError("live signed review verification context required")
        from .muse_signed_review import verify_and_register_signed_review
        if signed_review.request_id != request_id or signed_review.report_sha256 != evidence_ref.rsplit(":", 1)[-1]:
            raise EvidenceError("finalization review identity mismatch")
        verify_and_register_signed_review(
            db, signed_review,
            trusted_public_key_bytes=trusted_public_key_bytes,
            expected_reviewer_id=expected_reviewer_id,
        )
    previous = db.execute(
        "SELECT stage FROM muse_delivery_events WHERE request_id=? "
        "ORDER BY CASE stage WHEN 'DISCOVERED' THEN 1 WHEN 'UI_SUBMISSION_ATTEMPTED' THEN 2 "
        "WHEN 'MUSE_ACCEPTED' THEN 3 WHEN 'REPORT_CREATED' THEN 4 "
        "WHEN 'REPORT_VERIFIED' THEN 5 END DESC LIMIT 1", (request_id,)
    ).fetchone()
    if previous:
        if stage == previous[0]:
            old = db.execute("SELECT evidence_ref FROM muse_delivery_events WHERE request_id=? AND stage=?",
                             (request_id, stage)).fetchone()[0]
            if old == evidence_ref:
                return
            raise EvidenceError("existing evidence cannot be overwritten")
        scheduled_acceptance = (
            previous[0] == "DISCOVERED"
            and stage == "MUSE_ACCEPTED"
            and evidence_ref.startswith("muse-run-readback:")
        )
        if NEXT.get(previous[0]) != stage and not scheduled_acceptance:
            raise EvidenceError("stage cannot be skipped or reversed")
    elif stage != "DISCOVERED":
        raise EvidenceError("first stage must be DISCOVERED")
    ts = event_time or dt.datetime.now(UTC).isoformat()
    if dt.datetime.fromisoformat(ts).tzinfo is None:
        raise EvidenceError("timestamp must include timezone")
    with db:
        db.execute("INSERT INTO muse_delivery_events VALUES (?,?,?,?)",
                   (request_id, stage, evidence_ref, ts))


def review_legacy(db: sqlite3.Connection, request_id: str) -> dict:
    """Read legacy evidence; do not mutate original DB or infer completion."""
    dispatched = False
    try:
        dispatched = db.execute("SELECT 1 FROM dispatched WHERE request_id=?",
                                (request_id,)).fetchone() is not None
    except sqlite3.OperationalError:
        pass
    rows = db.execute("SELECT stage,evidence_ref,event_time FROM muse_delivery_events "
                      "WHERE request_id=?", (request_id,)).fetchall()
    stages = {row[0]: {"evidence_ref":row[1], "event_time":row[2]} for row in rows}
    return {
        "request_id": request_id,
        "legacy_ui_submission_attempt_recorded": dispatched,
        "stage_evidence": stages,
        "completed": "REPORT_VERIFIED" in stages,
        "next_required": (
            None if "REPORT_VERIFIED" in stages
            else "REPORT_VERIFIED" if "REPORT_CREATED" in stages
            else "REPORT_CREATED" if "MUSE_ACCEPTED" in stages
            else "MUSE_ACCEPTED" if "UI_SUBMISSION_ATTEMPTED" in stages
            else "UI_SUBMISSION_ATTEMPTED" if "DISCOVERED" in stages
            else "DISCOVERED"
        ),
        "legacy_semantics": "UI submission attempt; not proof of Muse acceptance or report creation",
    }
