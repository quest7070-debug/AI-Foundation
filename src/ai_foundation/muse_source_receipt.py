"""Read-only integrity reconciliation for existing Muse source-only intake.

This validates locally preserved snapshots and receipts, NOT Muse execution,
Drive provider identity, independent factual review or execution authority.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .muse_delivery_state import EvidenceError
from .external_research_handoff import parse_external_research_handoff


def _unique_receipt_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Fail closed on ambiguous receipt identity/authorization fields."""
    receipt: dict[str, Any] = {}
    for key, value in pairs:
        if key in receipt:
            raise ValueError("duplicate receipt JSON key")
        receipt[key] = value
    return receipt


def canonical_sha256(document: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, ensure_ascii=False,
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def reconcile_source_only_snapshot(
    snapshot_path: Path, receipt_path: Path, *,
    expected_correlation_id: str,
) -> dict[str, Any]:
    if not expected_correlation_id:
        raise EvidenceError("explicit correlation ID required")
    if snapshot_path.is_symlink() or receipt_path.is_symlink():
        raise EvidenceError("symlink evidence is not allowed")
    if snapshot_path.stem != receipt_path.stem:
        raise EvidenceError("snapshot/receipt identity mismatch")
    try:
        if snapshot_path.stat().st_size > 2_000_000 or receipt_path.stat().st_size > 50_000:
            raise EvidenceError("oversized source evidence")
        source_text = snapshot_path.read_text(encoding="utf-8-sig")
        snapshot = json.loads(source_text)
        receipt = json.loads(
            receipt_path.read_text(encoding="utf-8-sig"),
            object_pairs_hook=_unique_receipt_keys,
        )
    except (OSError, ValueError, UnicodeError) as exc:
        raise EvidenceError("unreadable or malformed source evidence") from exc
    if not isinstance(snapshot, dict) or not isinstance(receipt, dict):
        raise EvidenceError("invalid evidence shape")
    if snapshot.get("schema_version") != 1 or snapshot.get("producer") != "muse":
        raise EvidenceError("unexpected candidate schema")
    if snapshot.get("correlation_id") != expected_correlation_id:
        raise EvidenceError("candidate correlation mismatch")
    if receipt.get("correlation_id") != expected_correlation_id:
        raise EvidenceError("receipt correlation mismatch")
    if receipt.get("type") != "foundation_candidate_validation_receipt":
        raise EvidenceError("wrong receipt type")
    if receipt.get("status") != "STRUCTURALLY_VALID_UNVERIFIED":
        raise EvidenceError("receipt must be source-only and unverified")
    if (receipt.get("execution_authorized") is not False or
            receipt.get("trusted_as_authority") is not False or
            receipt.get("review_required") is not True):
        raise EvidenceError("source-only authorization boundary violated")
    findings = snapshot.get("findings")
    if not isinstance(findings, list) or not findings:
        raise EvidenceError("missing source findings")
    if receipt.get("findings_count") != len(findings):
        raise EvidenceError("findings count mismatch")
    # Matching two unauthenticated JSON files is not proof the source had
    # the approved handoff schema. Reuse the strict no-authority parser,
    # including duplicate-key rejection, before labeling integrity verified.
    try:
        digest = parse_external_research_handoff(source_text).content_sha256
    except (ValueError, TypeError, UnicodeError) as exc:
        raise EvidenceError("invalid source-only handoff schema") from exc
    if receipt.get("candidate_sha256") != digest:
        raise EvidenceError("canonical candidate hash mismatch")
    return {
        "correlation_id": expected_correlation_id,
        "candidate_sha256": digest,
        "findings_count": len(findings),
        "integrity_verified": True,
        "provider_authenticated": False,
        "muse_run_verified": False,
        "independent_review_verified": False,
        "execution_authorized": False,
        "classification": "SOURCE_ONLY_INTEGRITY_MATCH",
    }
