"""Synthetic-only owner answer fidelity metrics; no personal source or model."""
import hashlib
import json
import pytest

from ai_foundation.human_model_fidelity import evaluate_owner_answer_fidelity


def entry(case, ref, digest, expected="ANSWER", model="ANSWER",
          agreement="MATCH", **kw):
    return {
        "case_id": case, "review_ref": ref, "reference_sha256": digest,
        "expected_behavior": expected, "model_behavior": model,
        "agreement": agreement, "reason_preserved": kw.get("reason", True),
        "exception_preserved": kw.get("exception", True),
        "uncertainty_appropriate": kw.get("uncertainty", True),
        "citation_valid": kw.get("citation", True),
        "false_owner_approval_claim": kw.get("fake_approval", False),
    }


def test_owner_reviewed_answers_count_reason_exceptions_and_abstentions():
    one = entry("case-one", "a"*64, "1"*64, reason=True, exception=False,
                fake_approval=True)
    two = entry("case-two", "b"*64, "2"*64, expected="ABSTAIN",
                model="ABSTAIN", agreement="NOT_APPLICABLE",
                reason=None, exception=None, uncertainty=None, citation=None)
    result = evaluate_owner_answer_fidelity(
        [one, two], trusted_review_refs={"a"*64, "b"*64})
    assert result["status"] == "OWNER_REVIEWED_SAMPLE"
    assert result["reviewed_questions"] == 2
    assert result["correct_abstentions"] == 1
    assert result["false_owner_approval_claims"] == 1
    assert result["aspects"]["exception_preserved"]["false"] == 1
    assert result["answer_agreement"]["MATCH"] == 1
    assert result["representative_fidelity_verified"] is False
    assert result["execution_authority"] is False
    assert "case-one" not in json.dumps(result)
    assert "a"*64 not in json.dumps(result)


def test_untrusted_review_refs_and_duplicate_cases_never_infer_truth():
    row = entry("same", "a"*64, "3"*64)
    with pytest.raises(PermissionError, match="OWNER_ADJUDICATION_NOT_VERIFIED"):
        evaluate_owner_answer_fidelity([row], trusted_review_refs=[])
    with pytest.raises(ValueError, match="REVIEW_IDENTITY_OR_REFERENCE_INVALID"):
        evaluate_owner_answer_fidelity([row, dict(row, review_ref="b"*64)],
                                      trusted_review_refs={"a"*64, "b"*64})


def test_false_unknowns_malformed_reviews_and_raw_content_fail_closed():
    ref = "c"*64
    row = entry("one", ref, "4"*64, expected="ABSTAIN", model="ANSWER",
                agreement="NOT_APPLICABLE", reason=None,
                exception=None, uncertainty=False, citation=False)
    result = evaluate_owner_answer_fidelity([row], trusted_review_refs={ref})
    assert result["unsupported_answers"] == 1
    invalid = [dict(row, agreement="MATCH"),
               dict(row, reason_preserved="yes"),
               dict(row, reason_preserved=True),
               dict(row, source_text="SECRET_PRIVATE_SOURCE"),
               dict(row, model_behavior="ABSTAIN", reason_preserved=True)]
    for sample in invalid:
        with pytest.raises(ValueError):
            evaluate_owner_answer_fidelity([sample], trusted_review_refs={ref})
    assert "SECRET_PRIVATE_SOURCE" not in json.dumps(result)


def contract(row):
    return hashlib.sha256(json.dumps(
        row, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode()).hexdigest()


def test_allowed_reference_alone_does_not_verify_review_labels_or_source():
    row = entry("one", "a"*64, "1"*64)
    legacy = evaluate_owner_answer_fidelity([row], trusted_review_refs={"a"*64})
    assert legacy["review_binding_verified"] is False
    assert legacy["evaluated_questions"] == 0
    assert legacy["fidelity_evaluation_status"] == "REVIEW_BINDING_REQUIRED"
    trusted = {row["review_ref"]: contract(row)}
    result = evaluate_owner_answer_fidelity(
        [row], trusted_review_refs={"a"*64}, trusted_review_contracts=trusted)
    assert result["review_binding_verified"] is True
    assert result["evaluated_questions"] == 1
    assert result["fully_reviewed_answers"] == 1
    assert result["representative_fidelity_verified"] is False
    for changed in (dict(row, reference_sha256="2"*64),
                    dict(row, agreement="MISMATCH"),
                    dict(row, citation_valid=False),
                    dict(row, false_owner_approval_claim=True)):
        with pytest.raises(PermissionError, match="OWNER_REVIEW_CONTRACT_CHANGED"):
            evaluate_owner_answer_fidelity([changed], trusted_review_refs={"a"*64},
                                          trusted_review_contracts=trusted)


def test_unreviewed_and_incomplete_samples_are_explicit_without_exporting_refs():
    empty = evaluate_owner_answer_fidelity([], trusted_review_refs=[],
                                           trusted_review_contracts={})
    assert empty["fidelity_evaluation_status"] == "NOT_EVALUATED"
    assert empty["evaluated_questions"] == 0
    assert empty["review_binding_verified"] is False
    row = entry("one", "b"*64, "2"*64, citation=None)
    result = evaluate_owner_answer_fidelity(
        [row], trusted_review_refs={"b"*64},
        trusted_review_contracts={row["review_ref"]: contract(row)})
    assert result["fidelity_evaluation_status"] == "INCOMPLETE_OWNER_REVIEW"
    assert result["fully_reviewed_answers"] == 0
    assert result["incomplete_answer_reviews"] == 1
    assert "b"*64 not in json.dumps(result)
    assert "2"*64 not in json.dumps(result)
    with pytest.raises(PermissionError, match="OWNER_REVIEW_CONTRACT_CHANGED"):
        evaluate_owner_answer_fidelity([row], trusted_review_refs={"b"*64},
                                      trusted_review_contracts={})
