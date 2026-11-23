import hashlib
import sqlite3

import pytest

from ai_foundation.core import GuardState
from ai_foundation.durable_work import SQLiteWorkStore
from ai_foundation.guard import GuardCore
from ai_foundation.operator_actions import OperatorActions
from ai_foundation.operator_server import OperatorApplication
from ai_foundation.primary_review_events import PrimaryReviewTransitions, primary_review_notices
from ai_foundation.productization import FoundationConfig
from ai_foundation.notification_boundary import project_push
from ai_foundation.push_dispatch import PushDispatch


GENERATION = hashlib.sha256(b"exact-question-generation").hexdigest()
EVIDENCE = hashlib.sha256(b"original-approved-source").hexdigest()


def store(tmp_path):
    existing = tmp_path / "work.db"
    SQLiteWorkStore(existing)
    return existing, PrimaryReviewTransitions(existing)


def test_requires_existing_work_store_and_exact_generation(tmp_path):
    with pytest.raises(FileNotFoundError):
        PrimaryReviewTransitions(tmp_path / "missing.db")
    assert not (tmp_path / "missing.db").exists()
    path, events = store(tmp_path)
    with pytest.raises(ValueError):
        events.started("task-A", "not-a-sha256")
    with pytest.raises(ValueError):
        events.started("../secret", GENERATION)
    assert primary_review_notices(path) == ()


def test_existing_empty_or_symlink_database_is_not_a_second_store(tmp_path):
    empty = tmp_path / "empty.db"
    empty.touch()
    with pytest.raises(ValueError, match="canonical work schema"):
        PrimaryReviewTransitions(empty)
    with sqlite3.connect(empty) as db:
        assert not db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='primary_review_transitions'"
        ).fetchone()
    real, _ = store(tmp_path)
    alias = tmp_path / "alias.db"
    alias.symlink_to(real)
    with pytest.raises(FileNotFoundError, match="non-symlink"):
        PrimaryReviewTransitions(alias)


def test_started_and_resolved_are_durable_independent_deduplicated_transitions(tmp_path):
    path, events = store(tmp_path)
    assert events.started("issue-42", GENERATION)
    assert not events.started("issue-42", GENERATION)
    assert events.resolved("issue-42", GENERATION, "NO_MATCHING_EVIDENCE")
    assert not events.resolved("issue-42", GENERATION, "NO_MATCHING_EVIDENCE")
    before = primary_review_notices(path)
    assert len(before) == 2
    assert {n.status for n in before} == {
        "PRIMARY_REVIEW_STARTED", "PRIMARY_REVIEW_RESOLVED"}
    assert all(n.kind == "primary_review" and n.level == 2 for n in before)
    assert len({n.subject for n in before}) == 2
    assert all("issue-42" in n.detail_ja for n in before)
    assert primary_review_notices(path) == before
    with pytest.raises(ValueError, match="conflicting"):
        events.resolved("issue-42", GENERATION, "MATCHED_EXISTING_DELEGATION")
    assert primary_review_notices(path) == before


def test_only_correlated_started_generation_may_resolve(tmp_path):
    path, events = store(tmp_path)
    with pytest.raises(ValueError, match="has not started"):
        events.resolved("issue-1", GENERATION, "MATCHED_EXISTING_DELEGATION")
    events.started("issue-1", GENERATION)
    different = hashlib.sha256(b"revised-question").hexdigest()
    with pytest.raises(ValueError, match="has not started"):
        events.resolved("issue-1", different, "NO_MATCHING_EVIDENCE")
    with pytest.raises(ValueError, match="invalid"):
        events.resolved("issue-1", GENERATION, "AUTOMATIC_GUARD_APPROVE")
    with pytest.raises(ValueError, match="digest"):
        events.resolved("issue-1", GENERATION, "NO_MATCHING_EVIDENCE",
                        evidence_sha256="raw-private-value")
    assert len(primary_review_notices(path)) == 1


def test_event_contains_hash_only_not_humanmodel_evidence(tmp_path):
    path, events = store(tmp_path)
    events.started("job-1", GENERATION)
    events.resolved("job-1", GENERATION, "MATCHED_EXISTING_DELEGATION",
                    evidence_sha256=EVIDENCE)
    with sqlite3.connect(path) as db:
        rows = db.execute("SELECT evidence_sha256,outcome FROM primary_review_transitions").fetchall()
    assert rows[1] == (EVIDENCE, "MATCHED_EXISTING_DELEGATION")
    notices = primary_review_notices(path)
    assert all("original-approved-source" not in repr(n) for n in notices)
    assert any("Guard" in n.detail_ja for n in notices)
    assert any(GENERATION in n.detail_ja for n in notices)
    assert any(EVIDENCE in n.detail_ja for n in notices if n.status == "PRIMARY_REVIEW_RESOLVED")


def test_unavailable_view_is_not_authority_and_technical_failure_is_lv3(tmp_path):
    path, events = store(tmp_path)
    events.started("job-unavailable", GENERATION)
    events.resolved("job-unavailable", GENERATION, "APPROVED_VIEW_UNAVAILABLE")
    other_generation = hashlib.sha256(b"second-question").hexdigest()
    events.started("job-technical", other_generation)
    events.resolved("job-technical", other_generation, "REVIEW_TECHNICAL_FAILURE")
    notices = primary_review_notices(path)
    assert any(n.level == 3 for n in notices)
    assert any("承認は発行" in n.detail_ja or "権限判断は停止" in n.detail_ja
               for n in notices if n.status == "PRIMARY_REVIEW_RESOLVED")
    # Persisting a review result is NEVER an approval grant.
    guard = GuardCore(GuardState())
    assert not guard.state.approvals


class _Transport:
    def __init__(self):
        self.sent = []

    def deliver(self, payload):
        self.sent.append(payload)
        return {"complete": True}


def test_existing_operator_api_and_webpush_share_two_lv2_events(tmp_path):
    path = tmp_path / "data" / "work.db"
    path.parent.mkdir()
    SQLiteWorkStore(path)
    events = PrimaryReviewTransitions(path)
    events.started("task-123", GENERATION)
    events.resolved("task-123", GENERATION, "NO_MATCHING_EVIDENCE")
    guard = GuardCore(GuardState())
    app = OperatorApplication(
        FoundationConfig(str(path.parent.resolve())),
        OperatorActions(guard),
        operational_notices=lambda: primary_review_notices(path),
    )
    payload = app.human_payload()
    target = [n for n in payload["notices"] if n["kind"] == "primary_review"]
    assert len(target) == 2
    assert {n["status"] for n in target} == {
        "PRIMARY_REVIEW_STARTED", "PRIMARY_REVIEW_RESOLVED"}
    assert [n["level"] for n in target] == [2, 2]
    transport = _Transport()
    dispatch = PushDispatch(transport, tmp_path / "seen.json")
    assert dispatch.dispatch(payload)["sent_notices"] == 2
    assert dispatch.dispatch(app.human_payload())["sent_notices"] == 0
    assert len(transport.sent) == 2
    assert all("task-123" not in str(p) for p in transport.sent)


def test_ordinary_lv2_not_push_and_forged_lv2_type_not_push():
    rows = [
        {"kind": "work", "subject": "normal", "status": "RUNNING",
         "level": 2, "summary_ja": "ordinary"},
        {"kind": "primary_review", "subject": "unrecognized", "status": "RUNNING",
         "level": 2, "summary_ja": "unrecognized"},
        {"kind": "primary_review", "subject": "known", "status": "PRIMARY_REVIEW_STARTED",
         "level": 2, "summary_ja": "SECRET_PRIVATE_CONTENT"},
        {"kind": "primary_review", "subject": "known-result", "status": "PRIMARY_REVIEW_RESOLVED",
         "level": 2, "summary_ja": "SECRET_PRIVATE_CONTENT"},
    ]
    got = project_push({"notices": rows})
    assert len(got) == 2
    assert all("SECRET_PRIVATE_CONTENT" not in repr(n) for n in got)
    assert {n.level for n in got} == {2}


def _waiting_primary_task(path, job_id="owner-exception-1"):
    from ai_foundation.orchestration import WorkStatus
    work = SQLiteWorkStore(path)
    work.ensure(job_id, ("review",))
    work.set(job_id, 0, WorkStatus.WAITING_HUMAN)
    return work


def test_unresolved_current_primary_review_projects_one_lv4_handoff_without_grant(tmp_path):
    path, events = store(tmp_path)
    work = _waiting_primary_task(path)
    events.started("owner-exception-1", GENERATION)
    events.resolved("owner-exception-1", GENERATION, "NO_MATCHING_EVIDENCE")
    notices = primary_review_notices(path)
    primary = [n for n in notices if n.kind == "primary_review"]
    escalations = [n for n in notices if n.kind == "primary_review_escalation"]
    assert len(primary) == 2
    assert [n.level for n in primary] == [2, 2]
    assert len(escalations) == 1
    handoff = escalations[0]
    assert handoff.level == 4 and handoff.status == "OWNER_REVIEW_REQUIRED"
    assert not handoff.actionable and not handoff.input_required
    assert handoff.approval_ref == ""
    assert "Guard" in handoff.detail_ja
    assert primary_review_notices(path) == notices
    transport = _Transport()
    app = OperatorApplication(
        FoundationConfig(str(tmp_path.resolve())),
        OperatorActions(GuardCore(GuardState())),
        operational_notices=lambda: primary_review_notices(path))
    payload = app.human_payload()
    selected = [n for n in payload["notices"]
                if n["kind"] == "primary_review_escalation"]
    assert len(selected) == 1
    dispatch = PushDispatch(transport, tmp_path / "lv4-seen.json")
    # The existing work WAITING_HUMAN notice remains a distinct input
    # requirement. The HumanModel LV4 decision notice cannot silently
    # replace or authorize that separate work transition.
    assert dispatch.dispatch(payload)["sent_notices"] == 4
    assert dispatch.dispatch(app.human_payload())["sent_notices"] == 0
    assert len(transport.sent) == 4
    # Existing work notices retain their established job-key contract.
    # Only the new HumanModel escalation must have a fixed anonymous push.
    owner_push = [n for n in transport.sent
                  if n["body"].startswith("HumanModelの一次判断が未解決")]
    assert len(owner_push) == 1
    assert "owner-exception-1" not in repr(owner_push)
    assert GENERATION not in repr(owner_push)
    from ai_foundation.orchestration import WorkStatus
    work.set("owner-exception-1", 0, WorkStatus.VERIFIED)
    assert not [n for n in primary_review_notices(path)
                if n.kind == "primary_review_escalation"]


def test_stale_generation_and_guard_denial_are_never_new_lv4_requests(tmp_path):
    path, events = store(tmp_path)
    _waiting_primary_task(path)
    events.started("owner-exception-1", GENERATION)
    events.resolved("owner-exception-1", GENERATION, "NO_MATCHING_EVIDENCE")
    assert len([n for n in primary_review_notices(path)
                if n.kind == "primary_review_escalation"]) == 1
    newer = hashlib.sha256(b"revised-active-question").hexdigest()
    events.started("owner-exception-1", newer)
    assert not [n for n in primary_review_notices(path)
                if n.kind == "primary_review_escalation"]
    events.resolved("owner-exception-1", newer, "EXISTING_GUARD_DENIED")
    assert not [n for n in primary_review_notices(path)
                if n.kind == "primary_review_escalation"]


def test_unavailable_view_handoff_is_not_auth_and_technical_failure_is_not_lv4(tmp_path):
    path, events = store(tmp_path)
    _waiting_primary_task(path)
    events.started("owner-exception-1", GENERATION)
    events.resolved("owner-exception-1", GENERATION, "APPROVED_VIEW_UNAVAILABLE")
    handoffs = [n for n in primary_review_notices(path)
                if n.kind == "primary_review_escalation"]
    assert len(handoffs) == 1
    assert not handoffs[0].actionable
    assert not GuardCore(GuardState()).state.approvals
    next_generation = hashlib.sha256(b"technical-error").hexdigest()
    events.started("owner-exception-1", next_generation)
    events.resolved("owner-exception-1", next_generation, "REVIEW_TECHNICAL_FAILURE")
    notices = primary_review_notices(path)
    assert not [n for n in notices if n.kind == "primary_review_escalation"]
    assert any(n.level == 3 for n in notices)


def test_forged_lv4_push_summary_is_fixed_and_never_contains_owner_data():
    secret = "PRIVATE_OWNER_DECISION_CONTENT"
    rendered = project_push({"notices": [{
        "kind": "primary_review_escalation",
        "subject": "hashed-task",
        "status": "OWNER_REVIEW_REQUIRED",
        "level": 4,
        "summary_ja": secret,
        "detail_ja": "path/SECRET",
    }]})
    assert len(rendered) == 1
    assert rendered[0].level == 4
    assert secret not in str(rendered[0])
    assert "path/SECRET" not in str(rendered[0])
    assert "HumanModel" in rendered[0].body


def test_source_backed_primary_answer_roundtrip_into_existing_operator_api(tmp_path):
    path, events = store(tmp_path)
    events.started("hm-job-1", GENERATION)
    assert events.resolved(
        "hm-job-1", GENERATION, "MATCHED_EXISTING_DELEGATION",
        evidence_sha256=EVIDENCE, answer_text="本人の暫定回答（根拠あり）"
    )
    rows = primary_review_notices(path)
    answer = next(x for x in rows if x.status == "PRIMARY_REVIEW_RESOLVED")
    assert answer.automatic_answer == "本人の暫定回答（根拠あり）"
    assert answer.answer_reference == {
        "task_id": "hm-job-1", "question_digest": GENERATION,
        "evidence_sha256": EVIDENCE, "current_generation": True,
        "related_work_status": "UNVERIFIED",
    }
    app = OperatorApplication(
        FoundationConfig(str(tmp_path.resolve())),
        OperatorActions(GuardCore(GuardState())),
        operational_notices=lambda: primary_review_notices(path),
    )
    payload = app.human_payload()
    matches = [row for row in payload["notices"]
               if row["kind"] == "primary_review"
               and row["status"] == "PRIMARY_REVIEW_RESOLVED"]
    assert len(matches) == 1
    assert matches[0]["automatic_answer"] == "本人の暫定回答（根拠あり）"
    assert matches[0]["answer_reference"]["question_digest"] == GENERATION
    assert not any(
        "automatic_answer" in row or "answer_reference" in row
        for row in app.echo_human_payload()["notices"]
    )


def test_historical_answer_without_evidence_is_not_projected_or_pushed_as_answer(tmp_path):
    path, events = store(tmp_path)
    events.started("old-no-evidence", GENERATION)
    assert events.resolved(
        "old-no-evidence", GENERATION, "MATCHED_EXISTING_DELEGATION",
        answer_text="PRIVATE_UNGROUNDED_TEXT"
    )
    result = next(x for x in primary_review_notices(path)
                  if x.status == "PRIMARY_REVIEW_RESOLVED")
    assert result.automatic_answer == ""
    assert result.answer_reference is None
    assert "PRIVATE_UNGROUNDED_TEXT" not in repr(result)
    assert "自動回答を記録しました" not in result.summary_ja


def test_older_evidence_bound_result_stays_visible_as_noncurrent_history(tmp_path):
    path, events = store(tmp_path)
    events.started("review-job", GENERATION)
    assert events.resolved("review-job", GENERATION,
                           "MATCHED_EXISTING_DELEGATION",
                           evidence_sha256=EVIDENCE,
                           answer_text="historical answer")
    current = hashlib.sha256(b"newer primary review generation").hexdigest()
    events.started("review-job", current)
    old = next(n for n in primary_review_notices(path)
               if n.automatic_answer == "historical answer")
    assert old.answer_reference["current_generation"] is False
    assert old.answer_reference["question_digest"] == GENERATION
