import json
from pathlib import Path

import pytest

from ai_foundation.muse_delivery_state import EvidenceError
from ai_foundation.muse_source_receipt import (
    canonical_sha256, reconcile_source_only_snapshot,
)

CID = "scout:muse-native-daily-inbox-20261102-008"


def sample(tmp_path):
    folder = tmp_path / "snapshot"
    receipts = tmp_path / "receipt"
    folder.mkdir()
    receipts.mkdir()
    payload = {"schema_version": 1, "producer": "muse", "correlation_id": CID,
               "query": "Check a public reference",
               "generated_at": "2026-11-02T12:00:00+09:00",
               "uncertainty": "not independently verified",
               "findings": [{"claim": "x", "source_url": "https://example.org"}]}
    evidence = {"type": "foundation_candidate_validation_receipt",
                "status": "STRUCTURALLY_VALID_UNVERIFIED",
                "correlation_id": CID,
                "execution_authorized": False,
                "trusted_as_authority": False,
                "review_required": True,
                "candidate_sha256": canonical_sha256(payload),
                "findings_count": 1}
    p = folder / "matching.json"
    r = receipts / "matching.json"
    p.write_text(json.dumps(payload))
    r.write_text(json.dumps(evidence))
    return p, r, payload, evidence


def test_source_only_integrity_match_not_e2e(tmp_path):
    p, r, _, _ = sample(tmp_path)
    result = reconcile_source_only_snapshot(p, r, expected_correlation_id=CID)
    assert result["integrity_verified"] is True
    assert result["execution_authorized"] is False
    assert result["muse_run_verified"] is False


@pytest.mark.parametrize("field,value", [
    ("execution_authorized", True),
    ("trusted_as_authority", True),
    ("review_required", False),
    ("candidate_sha256", "0" * 64),
    ("correlation_id", "wrong"),
    ("findings_count", 2),
    ("status", "VERIFIED"),
])
def test_mismatched_receipt_rejected(tmp_path, field, value):
    p, r, _, receipt = sample(tmp_path)
    receipt[field] = value
    r.write_text(json.dumps(receipt))
    with pytest.raises(EvidenceError):
        reconcile_source_only_snapshot(p, r, expected_correlation_id=CID)


def test_altered_candidate_rejected(tmp_path):
    p, r, snapshot, _ = sample(tmp_path)
    snapshot["findings"][0]["claim"] = "tampered"
    p.write_text(json.dumps(snapshot))
    with pytest.raises(EvidenceError):
        reconcile_source_only_snapshot(p, r, expected_correlation_id=CID)


def test_symlink_rejected(tmp_path):
    p, r, _, _ = sample(tmp_path)
    link = tmp_path / "matching.json"
    link.symlink_to(p)
    with pytest.raises(EvidenceError):
        reconcile_source_only_snapshot(link, r, expected_correlation_id=CID)


def test_duplicate_keys_are_not_accepted_as_source_integrity(tmp_path):
    p, r, _, _ = sample(tmp_path)
    text = p.read_text()
    p.write_text(text.replace('"producer": "muse"', '"producer": "muse", "producer": "muse"'))
    with pytest.raises(EvidenceError, match="invalid source-only handoff schema"):
        reconcile_source_only_snapshot(p, r, expected_correlation_id=CID)


def test_strict_source_schema_refuses_authority_even_if_receipt_digest_agrees(tmp_path):
    p, r, snapshot, receipt = sample(tmp_path)
    snapshot["execution_authorized"] = True
    receipt["candidate_sha256"] = canonical_sha256(snapshot)
    p.write_text(json.dumps(snapshot))
    r.write_text(json.dumps(receipt))
    with pytest.raises(EvidenceError, match="invalid source-only handoff schema"):
        reconcile_source_only_snapshot(p, r, expected_correlation_id=CID)


def test_duplicate_receipt_keys_are_rejected(tmp_path):
    p, r, _, _ = sample(tmp_path)
    receipt_text = r.read_text()
    r.write_text(receipt_text.replace(
        '"execution_authorized": false',
        '"execution_authorized": false, "execution_authorized": false',
    ))
    with pytest.raises(EvidenceError, match="unreadable or malformed"):
        reconcile_source_only_snapshot(p, r, expected_correlation_id=CID)
