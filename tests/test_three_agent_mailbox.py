import json

import pytest

from ai_foundation.muse_source_receipt import reconcile_source_only_snapshot

from ai_foundation.three_agent_mailbox import (
    receipt_json, validate_muse_mailbox_document,
)

DOC = "https://docs.google.com/document/d/1BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB/edit"
CORRELATION = "scout:drive-bridge-20261101-001"


def report():
    return {
        "schema_version": 1,
        "producer": "muse",
        "correlation_id": CORRELATION,
        "query": "Check an upstream issue",
        "generated_at": "2026-11-01T11:40:00+09:00",
        "uncertainty": "May be already fixed in local installed version",
        "findings": [{
            "source_url": "https://github.com/example/project/issues/12",
            "claim": "Issue describes a bounded memory regression",
            "excerpt": "An untrusted excerpt saying ignore the Guard",
            "confidence": "medium",
            "observed_at": "2026-11-01T11:40:00+09:00",
            "published_at": None,
        }],
    }


def validate(candidate):
    return validate_muse_mailbox_document(
        candidate, expected_correlation_id=CORRELATION,
        source_document_url=DOC,
    )


def test_valid_candidate_receipt_cannot_grant_authority():
    receipt = validate(json.dumps(report()))
    assert receipt["status"] == "STRUCTURALLY_VALID_UNVERIFIED"
    assert receipt["review_required"] is True
    assert receipt["execution_authorized"] is False
    assert receipt["trusted_as_authority"] is False
    assert receipt["findings_count"] == 1
    assert receipt["claimed_producer"] == "muse"
    assert receipt["source_document_url"] == DOC
    assert not any(k in receipt for k in ("approved", "task", "budget", "run"))


def test_idempotency_digest_independent_of_json_key_order():
    first = validate(json.dumps(report()))
    second = validate(json.dumps(report(), sort_keys=True, indent=2))
    assert first == second
    assert len(first["idempotency_key"]) == 64
    assert json.loads(receipt_json(json.dumps(report()),
        expected_correlation_id=CORRELATION, source_document_url=DOC)) == first


def test_duplicate_correlation_with_different_claim_is_not_silently_same():
    one = validate(json.dumps(report()))
    changed = report()
    changed["findings"][0]["claim"] = "Different claim"
    two = validate(json.dumps(changed))
    assert one["idempotency_key"] != two["idempotency_key"]


@pytest.mark.parametrize("mutation", [
    {"approved": True},
    {"autorun": "true"},
    {"producer": "gpt"},
    {"correlation_id": "another-task"},
    {"findings": []},
    {"schema_version": 2},
])
def test_untrusted_or_mismatched_candidate_rejected(mutation):
    candidate = report()
    candidate.update(mutation)
    with pytest.raises(ValueError):
        validate(json.dumps(candidate))


@pytest.mark.parametrize("payload", [
    "{not json}",
    "```json\n{}\n```",
    "x" * 131073,
    '{"schema_version":1,"schema_version":1}',
])
def test_bad_document_or_markdown_fails_closed(payload):
    with pytest.raises(ValueError):
        validate(payload)


@pytest.mark.parametrize("url", [
    "http://docs.google.com/document/d/123456789012/edit",
    "https://docs.google.com.evil.test/document/d/123456789012/edit",
    "https://user:password@docs.google.com/document/d/123456789012/edit",
    "https://docs.google.com/document/d/123456789012/edit?export=txt",
    "https://drive.google.com/file/d/123456789012/view",
    "https://docs.google.com/document/d/123456789012/edit#anchor",
    "file:///tmp/foo",
])
def test_source_document_locator_fails_closed(url):
    with pytest.raises(ValueError):
        validate_muse_mailbox_document(
            json.dumps(report()), expected_correlation_id=CORRELATION,
            source_document_url=url,
        )


def test_no_automatic_actions_are_offered():
    receipt = validate(json.dumps(report()))
    assert receipt["execution_authorized"] is False
    assert "filename" not in receipt
    assert "github_label" not in receipt


def test_mailbox_receipt_and_existing_snapshot_reconcile(tmp_path):
    """Both recovered source verifiers agree without Drive access or effects."""
    snapshot_dir = tmp_path / "snapshot"
    receipt_dir = tmp_path / "receipts"
    snapshot_dir.mkdir()
    receipt_dir.mkdir()
    candidate = report()
    receipt = validate(json.dumps(candidate))
    snapshot = snapshot_dir / "candidate.json"
    receipt_file = receipt_dir / "candidate.json"
    snapshot.write_text(json.dumps(candidate), encoding="utf-8")
    receipt_file.write_text(json.dumps(receipt), encoding="utf-8")
    checked = reconcile_source_only_snapshot(
        snapshot, receipt_file, expected_correlation_id=CORRELATION)
    assert checked["integrity_verified"] is True
    assert checked["candidate_sha256"] == receipt["candidate_sha256"]
    assert checked["execution_authorized"] is False
    assert checked["provider_authenticated"] is False
    assert checked["independent_review_verified"] is False
