"""No-private-data contract tests for owner-only actual View acceptance."""
from scripts import m1_owner_humanmodel_real_e2e as subject


def test_exact_owner_issue_required():
    issue = {"number": 123, "title": subject.TITLE, "body": subject.BODY,
             "state": "open", "user": {"login": subject.OWNER}}
    event = {"action": "opened", "repository": {"full_name": subject.REPO},
             "sender": {"login": subject.OWNER}, "issue": issue}
    assert subject.exact_owner_event(event, issue)
    assert not subject.exact_owner_event(
        {**event, "sender": {"login": "not-owner"}}, issue)
    assert not subject.exact_owner_event(event, {**issue, "body": "change"})
    assert not subject.exact_owner_event(
        {**event, "issue": {**issue, "title": "synthetic owner answer"}}, issue)


def test_private_answer_is_never_exported():
    diagnosis = {"model_calls": 1, "model_state": "MODEL_REPLY_VALID"}
    answer = {
        "status": "SIMULATED_PROVISIONAL",
        "citation_reference_status": "MATCHED_IDS_ONLY",
        "cited_evidence_ids": ["PRIVATE_EVIDENCE_ID"],
        "answer": "SECRET_PRIVATE_ANSWER",
        "scope": "private-scope",
        "execution_authority": False,
        "owner_statement_verified": False,
        "source_scan_complete": True, "omitted_records": 0, "needs_review": False,
    }
    result = subject.redacted_result(answer, diagnosis)
    assert result["status"] == "LIVE_PRIVATE_VIEW_CITED_PROVISIONAL"
    assert result["cited_count"] == 1
    assert result["source_scan_complete"] is True
    assert result["owner_fidelity"] == "NOT_EVALUATED"
    assert "SECRET_PRIVATE_ANSWER" not in repr(result)
    assert "PRIVATE_EVIDENCE_ID" not in repr(result)
    assert "private-scope" not in repr(result)
    assert result["execution_authority"] is False


def test_uncited_owner_answer_not_accepted():
    diagnosis = {"model_calls": 1, "model_state": "MODEL_REPLY_VALID"}
    result = subject.redacted_result({
        "status": "UNAVAILABLE",
        "reason": "OWNER_ANSWER_WITHOUT_SOURCE_CITATION",
        "cited_evidence_ids": [], "answer": "SECRET_UNSUPPORTED_CLAIM",
        "source_scan_complete": True, "evidence_selection_complete": False,
        "omitted_records": 3,
    }, diagnosis)
    assert result["status"] == "NOT_ACCEPTED"
    assert result["reason"] == "OWNER_ANSWER_WITHOUT_SOURCE_CITATION"
    assert result["source_scan_complete"] is True
    assert result["evidence_selection_complete"] is False
    assert result["omitted_records_present"] is True
    assert result["owner_fidelity"] == "NOT_EVALUATED"
    assert "SECRET_UNSUPPORTED_CLAIM" not in repr(result)


def test_fidelity_is_not_claimed_even_with_citation():
    diagnosis = {"model_calls": 1, "model_state": "MODEL_REPLY_VALID"}
    fake = {"status": "SIMULATED_PROVISIONAL", "citation_reference_status": "MATCHED_IDS_ONLY",
            "cited_evidence_ids": ["X"], "owner_statement_verified": True,
            "execution_authority": False}
    assert subject.redacted_result(fake, diagnosis)["status"] == "NOT_ACCEPTED"


def test_rejected_citation_retains_observed_coverage_without_accepting_answer():
    diagnosis = {"model_calls": 1, "model_state": "MODEL_REPLY_VALID"}
    result = subject.redacted_result({
        "status": "UNAVAILABLE", "reason": "UNSUPPORTED_EVIDENCE_CITATION",
        "citation_failure_kind": "UNKNOWN_EVIDENCE_ID",
        "source_scan_complete": True, "evidence_selection_complete": False,
        "omitted_records": 3, "answer": "SECRET_INVALID_CITATION",
        "candidate_evidence_ids": ["PRIVATE_SOURCE_ID"],
    }, diagnosis)
    assert result["status"] == "NOT_ACCEPTED"
    assert result["reason"] == "UNSUPPORTED_EVIDENCE_CITATION"
    assert result["source_scan_complete"] is True
    assert result["evidence_selection_complete"] is False
    assert result["omitted_records_present"] is True
    assert result["cited_count"] == 0
    assert result["citation_failure_kind"] == "UNKNOWN_EVIDENCE_ID"
    assert result["owner_fidelity"] == "NOT_EVALUATED"
    assert "SECRET_INVALID_CITATION" not in repr(result)
    assert "PRIVATE_SOURCE_ID" not in repr(result)


def test_unknown_or_malformed_coverage_stays_unknown():
    diagnosis = {"model_calls": 1, "model_state": "MODEL_REPLY_VALID"}
    for observed in ({}, {"source_scan_complete": "true",
                          "evidence_selection_complete": 1, "omitted_records": True},
                     {"source_scan_complete": None,
                      "evidence_selection_complete": None, "omitted_records": -1}):
        result = subject.redacted_result({"status": "UNAVAILABLE", **observed}, diagnosis)
        assert result["status"] == "NOT_ACCEPTED"
        assert result["source_scan_complete"] is None
        assert result["evidence_selection_complete"] is None
        assert result["omitted_records_present"] is None


def test_only_fixed_citation_failure_categories_leave_private_boundary():
    diagnosis = {"model_calls": 1, "model_state": "MODEL_REPLY_VALID"}
    for failure in ("MALFORMED_MARKER", "UNKNOWN_EVIDENCE_ID", "VIEW_REVISION_MISMATCH"):
        assert subject.redacted_result({"citation_failure_kind": failure}, diagnosis)[
            "citation_failure_kind"] == failure
    for failure in (None, "SECRET_RAW_MODEL_ANSWER", ["PRIVATE_SOURCE_ID"]):
        result = subject.redacted_result({"citation_failure_kind": failure}, diagnosis)
        assert result["citation_failure_kind"] == "NOT_APPLICABLE"
        assert "SECRET_RAW_MODEL_ANSWER" not in repr(result)
        assert "PRIVATE_SOURCE_ID" not in repr(result)

