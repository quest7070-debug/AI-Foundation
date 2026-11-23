"""Real synthetic HumanModel ledger -> approved View -> Guard/Ingress integration.

No user evidence, model calls, cloud, Native, deployment or Guard.approve.
"""
from __future__ import annotations

from functools import partial
import hashlib
import importlib
import json
from pathlib import Path

import pytest

from ai_foundation.core import CanonContract, GuardState, TaskPlan
from ai_foundation.durable_work import SQLiteWorkStore
from ai_foundation.guard import GuardCore
from ai_foundation.human_model_context import HumanModelBinding, HumanModelContext, _source_reader
from ai_foundation.human_model_primary_review import HumanModelPrimaryReview
from ai_foundation.primary_review_events import PrimaryReviewTransitions, primary_review_notices
from ai_foundation.question_bridge import question_identity
from ai_foundation.question_ingress import resolve_ingress

REPOSITORY = Path(__file__).parents[1]


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def answer_digest(answers):
    return sha(json.dumps(answers, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":")))


@pytest.fixture
def source(tmp_path):
    volumes = tmp_path / "Volumes"
    root = volumes / "USB" / "HumanModel"
    (root / "ledger").mkdir(parents=True)
    read = _source_reader(REPOSITORY)
    module = importlib.import_module(read.__module__.rsplit(".", 1)[0] + ".human_model_ledger")
    ledger = module.Ledger(root / "ledger" / "human_model.sqlite3")
    ledger.define_view(view_id="review-approved", purpose="synthetic exact delegation",
                       audience="foundation", allowed_scopes=["foundation"],
                       max_privacy="private")
    work_db = tmp_path / "work.db"
    SQLiteWorkStore(work_db)
    transitions = PrimaryReviewTransitions(work_db)
    guard = GuardCore(GuardState())
    reader = partial(read, volumes_dir=volumes,
                     mount_check=lambda p: p == str(volumes / "USB"))
    context = HumanModelContext(
        HumanModelBinding("owner", str(root), "review-approved", ("foundation",), "private"),
        reader, guard=guard, run_id="human-model-read",
    )
    plan = TaskPlan("task-1", "write", "src/ai_foundation/example.py",
                    canon_revision="revision-1", effect_id="task-1:effect-1")
    canon = CanonContract("canonical:synthetic", "revision-1")
    bundle = {
        "pending_id": "pending-1", "task_id": "task-1", "session_id": "session-1",
        "questions": [{
            "question_id": "question-1", "prompt": "Approve the selected bounded change?",
            "options": [{"option_id": "opt-a", "label": "A"},
                        {"option_id": "opt-b", "label": "B"}],
        }],
    }
    answers = [{"question_id": "question-1", "selected_options": ["opt-a"]}]
    counter = 0

    def publish(*, changes=None, kind="decision", disputed=False,
                privacy="private", rebuild=True):
        nonlocal counter
        counter += 1
        payload = {
            "schema": "foundation-explicit-delegation/v1",
            "question_digest": question_identity(bundle).digest,
            "answers": answers,
            "answer_sha256": answer_digest(answers),
            "action": plan.action,
            "target_sha256": sha(plan.target),
            "effect_id": plan.effect_id,
            "canon_revision": plan.canon_revision,
        }
        payload.update(changes or {})
        eid = ledger.add(source_uri=f"synthetic:owner-decision:{counter}", source_revision="1",
                         kind=kind, scope="foundation", content=json.dumps(payload),
                         observed_at="2026-11-08T00:00:00Z", privacy=privacy,
                         disputed=disputed)
        if rebuild:
            ledger.rebuild_view(view_id="review-approved")
        return eid

    def reviewer(*, current_context=context, current_guard=guard,
                 current_plan=plan, current_owner="owner"):
        return HumanModelPrimaryReview(
            owner_id=current_owner, context=current_context, scope="foundation",
            guard=current_guard, plan=current_plan, canon=canon,
            transitions=transitions,
        )

    yield {
        "context": context, "guard": guard, "plan": plan, "canon": canon,
        "bundle": bundle, "answers": answers, "work_db": work_db,
        "transitions": transitions, "ledger": ledger, "publish": publish,
        "reviewer": reviewer,
    }
    ledger.close()


@pytest.mark.parametrize("valid_sibling", [False, True])
def test_duplicate_json_owner_decision_never_grants_delegation(source, valid_sibling):
    # json.loads normally keeps the LAST value of a duplicated key, which
    # would make an ambiguous historical record look like a valid grant.
    if valid_sibling:
        source["publish"]()
    plan = source["plan"]
    answers = source["answers"]
    body = {
        "schema": "foundation-explicit-delegation/v1",
        "question_digest": question_identity(source["bundle"]).digest,
        "answers": answers,
        "answer_sha256": answer_digest(answers),
        "action": plan.action,
        "target_sha256": sha(plan.target),
        "effect_id": plan.effect_id,
        "canon_revision": plan.canon_revision,
    }
    original = json.dumps(body)
    ambiguous = original.replace(
        '"effect_id":', '"effect_id": "old-effect", "effect_id":', 1
    )
    assert ambiguous != original
    source["ledger"].add(
        source_uri="synthetic:ambiguous-owner-decision",
        source_revision="1", kind="decision", scope="foundation",
        content=ambiguous, observed_at="2026-11-08T00:00:00Z",
        privacy="private", disputed=False,
    )
    source["ledger"].rebuild_view(view_id="review-approved")
    result = source["reviewer"]().review(source["bundle"])
    assert result.status == "WAITING_HUMAN"
    assert result.answer is None
    assert not source["guard"].state.approvals
    assert not source["guard"].state.effects


def test_exact_non_disputed_current_owner_decision_and_guard_allow(source):
    source["publish"]()
    result = source["reviewer"]().review(source["bundle"])
    assert result.status == "RESOLVED_DELEGATED"
    assert result.answer == source["answers"]
    assert len(result.evidence_sha256) == 64
    assert source["guard"].state.approvals == set()
    assert source["guard"].state.effects == {}
    notices = primary_review_notices(source["work_db"])
    assert {n.status for n in notices} == {
        "PRIMARY_REVIEW_STARTED", "PRIMARY_REVIEW_RESOLVED"}
    assert all(n.level == 2 for n in notices)
    assert any(result.evidence_sha256 in n.detail_ja for n in notices)
    assert all("synthetic:owner-decision" not in repr(n) for n in notices)


def test_real_ingress_uses_primary_only_when_host_injects_it(source):
    source["publish"]()
    reviewer = source["reviewer"]()
    output = resolve_ingress(source["bundle"], primary_review=reviewer)
    assert output["route"] == "DETERMINISTIC"
    assert output["review_status"] == "RESOLVED_DELEGATED"
    assert output["answer"] == source["answers"]
    no_hook = resolve_ingress(source["bundle"])
    assert no_hook["route"] == "HUMAN_GATE" and no_hook["requires_human"]
    # Existing Canon conclusion wins before HumanModel; routine tasks skip it.
    old = len(primary_review_notices(source["work_db"]))
    deterministic = resolve_ingress(source["bundle"],
        deterministic_resolver=lambda _b: [{"question_id":"question-1","selected_options":["opt-b"]}],
        primary_review=reviewer)
    assert deterministic["answer"][0]["selected_options"] == ["opt-b"]
    assert len(primary_review_notices(source["work_db"])) == old
    routine = {**source["bundle"],
        "questions":[{**source["bundle"]["questions"][0],
                      "prompt":"Choose a code style"}]}
    assert resolve_ingress(routine, primary_review=reviewer)["route"] == "REASONING"


@pytest.mark.parametrize("changes,kind,disputed", [
    ({"target_sha256": "0" * 64}, "decision", False),
    ({"effect_id": "another-effect"}, "decision", False),
    ({"canon_revision": "old-revision"}, "decision", False),
    ({"question_digest": "1" * 64}, "decision", False),
    ({"answers": [{"question_id": "question-1", "selected_options": ["missing"]}]}, "decision", False),
    ({"answers": [{"question_id": "question-1", "selected_options": ["opt-b"]}]}, "decision", False),
    ({}, "inference", False),
    ({}, "observation", False),
    ({}, "decision", True),
])
def test_unsafe_or_inferred_evidence_never_resolves(source, changes, kind, disputed):
    source["publish"](changes=changes, kind=kind, disputed=disputed)
    result = source["reviewer"]().review(source["bundle"])
    assert result.status == "WAITING_HUMAN"
    assert result.answer is None
    assert source["guard"].state.approvals == set()
    assert not source["guard"].state.effects


def test_missing_empty_or_stale_approved_view_never_grants(source):
    result = source["reviewer"]().review(source["bundle"])
    assert result.status == "WAITING_HUMAN"
    # The next *generation* may see a new source. Do not reuse a consumed one.
    source["publish"](rebuild=False)
    changed = {**source["bundle"], "pending_id": "pending-2"}
    assert source["reviewer"]().review(changed).status == "WAITING_HUMAN"
    assert source["guard"].state.approvals == set()


def test_guard_cancellation_blocks_even_a_matching_prior_delegation(source):
    source["publish"]()
    cancelled = GuardCore(GuardState(cancellations={"task-1"}))
    result = source["reviewer"](current_guard=cancelled).review(source["bundle"])
    assert result.status == "WAITING_HUMAN"
    assert result.reason == "GUARD_SCOPE_NOT_AUTHORIZED"
    assert "EXISTING_GUARD_DENIED" in [
        n.detail_ja for n in primary_review_notices(source["work_db"])
        if n.status == "PRIMARY_REVIEW_RESOLVED"
    ][0]


def test_duplicate_matching_current_decisions_are_conflict(source):
    source["publish"]()
    source["publish"]()
    result = source["reviewer"]().review(source["bundle"])
    assert result.status == "WAITING_HUMAN"
    assert result.answer is None


def test_authorized_view_change_during_review_fails_closed(source):
    source["publish"]()
    class Changing:
        owner_id = "owner"
        def __init__(self):
            self.calls = 0
        def read(self, owner, scope):
            self.calls += 1
            if self.calls == 2:
                source["publish"](changes={"question_digest": "9" * 64}, rebuild=False)
            return source["context"].read(owner, scope)
    result = source["reviewer"](current_context=Changing()).review(source["bundle"])
    assert result.status == "WAITING_HUMAN"
    assert result.answer is None


def test_private_source_respects_shareable_ceiling(source):
    source["publish"]()
    private = source["context"]
    context = HumanModelContext(
        HumanModelBinding("owner", private.binding.root, "review-approved",
                          ("foundation",), "shareable"),
        private._reader, guard=source["guard"], run_id="human-model-read",
    )
    result = source["reviewer"](current_context=context).review(source["bundle"])
    assert result.status == "WAITING_HUMAN"


def test_owner_task_and_effect_identity_cannot_be_spoofed(source):
    source["publish"]()
    with pytest.raises(PermissionError, match="owner mismatch"):
        source["reviewer"](current_owner="intruder")
    changed = {**source["bundle"], "task_id": "another-task"}
    with pytest.raises(PermissionError, match="exact Guard run"):
        source["reviewer"]().review(changed)
    assert primary_review_notices(source["work_db"]) == ()


def test_technical_source_failure_is_lv3_no_fake_permission(source):
    class Broken:
        owner_id = "owner"
        def read(self, owner, scope):
            raise RuntimeError("PRIVATE ORIGINALS SHOULD NOT APPEAR")
    result = source["reviewer"](current_context=Broken()).review(source["bundle"])
    assert result.status == "REVIEW_FAILED"
    assert result.answer is None
    notices = primary_review_notices(source["work_db"])
    assert len(notices) == 2
    assert any(n.level == 3 for n in notices)
    assert "PRIVATE ORIGINALS" not in repr(notices)


def test_value_priority_exception_needs_host_gate_not_bundle_flag(source):
    # Ordinary questions stay on the ordinary route even with an unsolicited
    # field from a question producer. Only the authenticated host can opt in.
    q = {**source["bundle"],
        "exception_requires_owner": True,
        "questions": [{
            "question_id": "question-1",
            "prompt": "Which creative direction should take priority?",
            "options": [{"option_id": "opt-a", "label": "A"},
                        {"option_id": "opt-b", "label": "B"}],
        }]}
    reviewer = source["reviewer"]()
    normal = resolve_ingress(q, primary_review=reviewer)
    assert normal["route"] == "REASONING" and "review_status" not in normal
    assert primary_review_notices(source["work_db"]) == ()
    required_no_binding = resolve_ingress(q, exception_requires_owner=True)
    assert required_no_binding["route"] == "HUMAN_GATE"
    assert required_no_binding["requires_human"] is True
    actual = resolve_ingress(q, primary_review=reviewer,
                            exception_requires_owner=True)
    assert actual["route"] == "HUMAN_GATE"
    assert actual["review_status"] == "WAITING_HUMAN"
    assert len(primary_review_notices(source["work_db"])) == 2


def test_credentials_never_enter_primary_review_even_when_exception_flagged(source):
    q = {**source["bundle"],
        "questions": [{
            "question_id": "question-1",
            "prompt": "Which API key should be used?",
            "options": [{"option_id": "opt-a", "label": "A"},
                        {"option_id": "opt-b", "label": "B"}],
        }]}
    response = resolve_ingress(q, primary_review=source["reviewer"](),
                               exception_requires_owner=True)
    assert response["route"] == "CREDENTIAL_BOUNDARY"
    assert response["requires_human"] and "review_status" not in response
    assert primary_review_notices(source["work_db"]) == ()


@pytest.mark.parametrize("second", [
    {"changes": {"target_sha256": "0" * 64}, "disputed": False},
    {"changes": {}, "disputed": True},
])
def test_conflicting_or_disputed_same_question_blocks_favorable_record(source, second):
    # One matching earlier record is insufficient if an additional current
    # explicit decision contradicts it or has an unresolved dispute.
    source["publish"]()
    source["publish"](**second)
    decision = source["reviewer"]().review(source["bundle"])
    assert decision.status == "WAITING_HUMAN"
    assert decision.answer is None
    assert source["guard"].state.approvals == set()


# Host-only resolver: real existing synthetic HumanModel originals, not an HTTP
# or model-owned owner identity. No new authority or production transport.
from ai_foundation.host_question_review import (
    HostQuestionAuthority, resolve_host_question,
)


def _host_authority(source, bundle=None, *, owner="owner", confined=True,
                    semantic=False):
    target = bundle if bundle is not None else source["bundle"]
    ident = question_identity(target)
    return HostQuestionAuthority(
        owner_id=owner, pending_id=ident.pending_id,
        task_id=ident.task_id, session_id=ident.session_id,
        question_digest=ident.digest, scope="foundation",
        plan=source["plan"], canon=source["canon"],
        local_confined=confined, semantic_owner_required=semantic,
    )


def _host_resolve(source, bundle=None, *, authority=None, context_builder=None,
                  deterministic_resolver=None):
    q = bundle if bundle is not None else source["bundle"]
    a = authority if authority is not None else _host_authority(source, q)
    builder = context_builder if context_builder is not None else (
        lambda *args, **kwargs: source["context"]
    )
    return resolve_host_question(
        q, a, guard=source["guard"], work_db=source["work_db"],
        binding_path="host-existing-config", repository_root=REPOSITORY,
        context_builder=builder, deterministic_resolver=deterministic_resolver,
    )


def test_host_question_review_exact_bound_producer_uses_current_explicit_decision(source):
    source["publish"]()
    calls = []
    def context_builder(path, owner, *, repository_root, guard, run_id):
        calls.append((owner, run_id))
        return source["context"]
    # An untrusted JSON owner is not selected; the in-process host owner wins.
    q = {**source["bundle"], "owner_id": "attacker", "local_confined": False}
    out = _host_resolve(source, q, context_builder=context_builder)
    assert calls == [("owner", "task-1")]
    assert out["route"] == "DETERMINISTIC"
    assert out["answer"] == source["answers"]
    assert out["review_status"] == "RESOLVED_DELEGATED"
    assert source["guard"].state.approvals == set()
    assert not source["guard"].state.effects
    assert len(primary_review_notices(source["work_db"])) == 2


def test_host_question_rejects_changed_generation_before_private_context(source):
    called = []
    original = _host_authority(source)
    stale = {**source["bundle"], "pending_id": "other"}
    with pytest.raises(PermissionError, match="question changed"):
        _host_resolve(source, stale, authority=original,
                      context_builder=lambda *a, **k: called.append(1))
    with pytest.raises(PermissionError, match="question changed"):
        _host_resolve(source, {**source["bundle"], "session_id": "other"},
                      authority=original,
                      context_builder=lambda *a, **k: called.append(1))
    with pytest.raises(PermissionError, match="host-authenticated"):
        _host_resolve(source, authority=original.__dict__)
    assert called == []
    assert primary_review_notices(source["work_db"]) == ()


def test_host_question_routine_canon_credential_never_loads_context(source):
    def forbidden(*_a, **_kw):
        raise AssertionError("unneeded HumanModel context read")
    deterministic = _host_resolve(
        source, context_builder=forbidden,
        deterministic_resolver=lambda _q: source["answers"])
    assert deterministic["route"] == "DETERMINISTIC"
    ordinary = {**source["bundle"], "questions": [
        {**source["bundle"]["questions"][0], "prompt": "Choose code style"}]}
    assert _host_resolve(source, ordinary,
                         context_builder=forbidden)["route"] == "REASONING"
    secret = {**source["bundle"], "questions": [
        {**source["bundle"]["questions"][0], "prompt": "Which API key?"}]}
    assert _host_resolve(source, secret,
                         context_builder=forbidden)["route"] == "CREDENTIAL_BOUNDARY"
    # A harmless prompt can still have raw secret-bearing option labels.
    labelled = {**source["bundle"], "questions": [
        {**source["bundle"]["questions"][0], "prompt": "Choose integration mode",
         "options": [
             {"option_id": "a", "label": "API key: raw-secret"},
             {"option_id": "b", "label": "Do not use"}]}]}
    assert _host_resolve(source, labelled,
                         context_builder=forbidden)["route"] == "CREDENTIAL_BOUNDARY"
    assert primary_review_notices(source["work_db"]) == ()


def test_host_question_private_source_requires_local_confined_output(source):
    source["publish"]()
    auth = _host_authority(source, confined=False)
    result = _host_resolve(source, authority=auth)
    assert result["route"] == "HUMAN_GATE"
    assert result["reason"] == "PRIVATE_VIEW_REQUIRES_LOCAL_HOST"
    assert "answer" not in result
    assert primary_review_notices(source["work_db"]) == ()
    assert source["guard"].state.approvals == set()


def test_host_question_missing_real_view_escalates_without_grant(source):
    result = _host_resolve(source, context_builder=lambda *a, **k: None)
    assert result["route"] == "HUMAN_GATE"
    assert result["review_status"] == "WAITING_HUMAN"
    assert result["requires_human"] is True
    assert len(primary_review_notices(source["work_db"])) == 2
    assert source["guard"].state.approvals == set()


def test_host_question_semantic_owner_gate_only_from_host(source):
    ordinary = {**source["bundle"], "questions": [
        {**source["bundle"]["questions"][0],
         "prompt": "Which project direction should take priority?"}],
        "semantic_owner_required": True}
    no_gate = _host_resolve(source, ordinary)
    assert no_gate["route"] == "REASONING"
    assert primary_review_notices(source["work_db"]) == ()
    trusted = _host_authority(source, ordinary, semantic=True)
    result = _host_resolve(source, ordinary, authority=trusted)
    assert result["route"] == "HUMAN_GATE"
    assert result["review_status"] == "WAITING_HUMAN"
    assert len(primary_review_notices(source["work_db"])) == 2


def test_operator_attested_review_is_separate_from_untrusted_http_route(source):
    from ai_foundation.operator_server import OperatorApplication
    from ai_foundation.operator_actions import OperatorActions
    from ai_foundation.productization import FoundationConfig
    source["publish"]()
    config = FoundationConfig(str(source["work_db"].parent.resolve()))
    app = OperatorApplication(
        config, OperatorActions(source["guard"]),
        question_resolver=lambda _bundle: {"route": "HUMAN_GATE"},
        host_question_resolver=lambda bundle, authority: _host_resolve(
            source, bundle, authority=authority),
    )
    # Existing loopback HTTP handler uses question_resolver, NOT this callback.
    assert app.question_resolver(source["bundle"]) == {"route": "HUMAN_GATE"}
    assert primary_review_notices(source["work_db"]) == ()
    result = app.resolve_attested_question(
        source["bundle"], _host_authority(source))
    assert result["route"] == "DETERMINISTIC"
    assert result["answer"] == source["answers"]
    assert len(primary_review_notices(source["work_db"])) == 2
    cold = OperatorApplication(config, OperatorActions(source["guard"]))
    with pytest.raises(RuntimeError, match="host question producer unavailable"):
        cold.resolve_attested_question(source["bundle"], _host_authority(source))
    source_script = (REPOSITORY / "scripts/operator_server.py").read_text()
    assert "host_question_resolver=host_question_resolver" in source_script
    # The unauthenticated legacy question route must not be a live Kandev
    # adapter. Only the authenticated host-bound resolver remains wired.
    assert "question_resolver=None" in source_script
    assert "question_resolver=lambda bundle: resolve_ingress" not in source_script
