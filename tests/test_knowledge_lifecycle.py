"""KLM input-side boundaries: adversarial, no network/model/external effects."""
import hashlib
import sqlite3
import pytest

from ai_foundation.knowledge_lifecycle import (
    POLICY_VERSION, DOMAINS, SourcePointer, Meaning, SemanticAtom,
    RelationProposal, OwnerTarget, SourceEvent, ReadonlyReceiptJournal,
    decompose_verified_span, decompose_batch, compare_atoms,
    plan_placement, audit_readonly,
)


def ptr(system="chat", revision="r1", scope="project", privacy="private",
        record_id="msg-7", observed_at=None):
    return SourcePointer(system, "owner-collection", record_id, revision,
                         scope, privacy, observed_at, "unknown")


def meaning(kind="observation", modality="assertion", polarity="positive",
            subject="item", predicate="state", object="pending", **kw):
    return Meaning(kind, modality, polarity, subject, predicate, object, **kw)


def atom(text="未実装タスク", *, source=None, proposal=None, start=0, end=None):
    data = text.encode("utf-8")
    return decompose_verified_span(
        source or ptr(), data, source_sha256=hashlib.sha256(data).hexdigest(),
        start=start, end=len(data) if end is None else end, meaning=proposal or meaning())


def target(system="github", role="canonical", revision="r1",
           scope="project", privacy="private", record="msg-7", resource="owner-collection"):
    return OwnerTarget(system, resource, record, revision, scope, privacy, role)


def event(revision="r1", digest=None, coverage="COMPLETE", record="msg-7"):
    return SourceEvent(ptr("github", revision, record_id=record),
                       digest or "a" * 64, "changed", coverage)


def test_source_pointer_rejects_wildcards_and_invalid_id():
    for p in ({"scope": "*"}, {"record_id": "*"}, {"revision": ""},
              {"system": "unknown"}, {"privacy": "public"}):
        with pytest.raises(ValueError):
            ptr(**p)


def test_unknown_time_is_preserved_not_invented():
    a = atom(source=ptr(observed_at=None))
    assert a.source.observed_at is None
    assert a.source_authentication == "UNVERIFIED_OWNER"
    assert not a.execution_authority


def test_bad_time_rejected_not_normalized_to_current():
    with pytest.raises(ValueError):
        ptr(observed_at="recently")


def test_source_content_hash_is_verified_not_model_supplied():
    data = b"original"
    with pytest.raises(ValueError):
        decompose_verified_span(ptr(), data, source_sha256="f"*64,
                                start=0, end=len(data), meaning=meaning())


def test_source_hash_is_hex_not_arbitrary_receipt():
    with pytest.raises(ValueError):
        decompose_verified_span(ptr(), b"a", source_sha256="not sha",
                                start=0, end=1, meaning=meaning())


def test_exact_multibyte_span_is_byte_positioned():
    content = "前提：費用なし。必要なら再検討。".encode("utf-8")
    selected = "費用なし".encode("utf-8")
    start = content.index(selected)
    a = decompose_verified_span(ptr(), content, source_sha256=hashlib.sha256(content).hexdigest(),
                                start=start, end=start+len(selected),
                                meaning=meaning(modality="conditional", condition="必要なら"))
    assert a.byte_start == start
    assert a.span_sha256 == hashlib.sha256(selected).hexdigest()
    assert a.meaning.condition == "必要なら"


def test_invalid_utf8_span_boundary_rejected():
    with pytest.raises(ValueError):
        atom("判断", end=1)


def test_bool_span_coordinates_not_allowed():
    for begin in (True, False):
        with pytest.raises(ValueError):
            atom("hello", start=begin)


def test_unbounded_raw_source_rejected():
    with pytest.raises(ValueError):
        atom("x"*32769)


def test_empty_or_oversized_atom_batch_rejected():
    with pytest.raises(ValueError):
        decompose_batch(ptr(), b"a", source_sha256=hashlib.sha256(b"a").hexdigest(),
                        proposals=[(0, 1, meaning())]*33)


def test_duplicate_exact_atom_rejected_in_batch():
    with pytest.raises(ValueError):
        decompose_batch(ptr(), b"a", source_sha256=hashlib.sha256(b"a").hexdigest(),
                        proposals=[(0, 1, meaning()), (0, 1, meaning())])


def test_replay_same_evidence_is_stable():
    assert atom().atom_id == atom().atom_id
    assert compare_atoms(atom(), atom()) == "EXACT_DUPLICATE"


def test_changed_revision_preserves_historical_identity():
    old = atom(source=ptr(revision="r1"))
    new = atom(source=ptr(revision="r2"))
    assert old.atom_id != new.atom_id
    assert compare_atoms(old, new) == "REVISION_CHANGE_REVIEW"


def test_same_source_revision_with_changed_content_needs_review():
    assert compare_atoms(atom("one"), atom("two")) == "SOURCE_REVISION_CONFLICT"


def test_negation_proposes_contradiction_not_silent_convergence():
    a = atom(source=ptr(record_id="a"), proposal=meaning(polarity="negative"))
    b = atom(source=ptr(record_id="b"), proposal=meaning(polarity="positive"))
    assert compare_atoms(a, b) == "POTENTIAL_CONTRADICTION"


def test_different_condition_is_not_forced_into_contradiction():
    a = atom(source=ptr(record_id="a"),
             proposal=meaning(modality="conditional", condition="予算あり"))
    b = atom(source=ptr(record_id="b"),
             proposal=meaning(modality="conditional", condition="予算なし"))
    assert compare_atoms(a, b) == "CONDITION_OR_TIME_SCOPE_REVIEW"


def test_historical_time_difference_is_not_overwritten():
    a = atom(source=ptr(record_id="a"),
             proposal=meaning(valid_from="2026-01-01T00:00:00+09:00"))
    b = atom(source=ptr(record_id="b"),
             proposal=meaning(valid_from="2027-01-01T00:00:00+09:00"))
    assert compare_atoms(a, b) == "CONDITION_OR_TIME_SCOPE_REVIEW"


def test_invalid_time_interval_is_rejected():
    with pytest.raises(ValueError):
        meaning(valid_from="2027-01-01", valid_until="2026-01-01")


def test_quote_speaker_is_not_automatically_the_owner():
    a = atom(proposal=meaning(kind="quote", speaker_claim="other speaker"))
    assert a.meaning.speaker_claim == "other speaker"
    assert a.source.actor_claim == "unknown"
    assert a.source_authentication == "UNVERIFIED_OWNER"


def test_inference_cannot_automatically_become_person_decision():
    a = atom(source=ptr("chat"), proposal=meaning(kind="inference"))
    t = target("humanmodel", "canonical")
    plan = plan_placement(a, "personal_judgment", t)
    assert plan.status == "NEEDS_OWNER_REVIEW"
    assert not plan.effect_authorized


def test_chat_quote_cannot_be_promoted_as_owner_decision():
    a = atom(source=ptr("chat"), proposal=meaning(kind="decision"))
    plan = plan_placement(a, "personal_judgment", target("humanmodel"))
    assert plan.status == "NEEDS_OWNER_REVIEW"


def test_same_owner_humanmodel_evidence_still_needs_guard_review():
    a = atom(source=ptr("humanmodel",scope="project"), proposal=meaning(kind="decision"))
    plan = plan_placement(a, "personal_judgment", target("humanmodel"))
    assert plan.status == "PROPOSED_NO_EFFECT"
    assert plan.effect_authorized is False


def test_development_task_can_have_github_canonical_only():
    a = atom(source=ptr("github"))
    assert DOMAINS["development_task"] == "github"
    assert plan_placement(a, "development_task", target("github")).status == "PROPOSED_NO_EFFECT"
    assert plan_placement(a, "development_task", target("gdrive")).reason == "WRONG_CANONICAL_OWNER"


def test_cross_project_todo_remains_drive_owned():
    a = atom(source=ptr("gdrive"))
    assert DOMAINS["cross_project_task"] == "gdrive"
    assert plan_placement(a, "cross_project_task", target("gdrive")).status == "PROPOSED_NO_EFFECT"


def test_unknown_owner_target_is_a_review_candidate_not_a_guess():
    a = atom()
    assert plan_placement(a, "new_domain", target()).status == "NEEDS_OWNER_MAPPING"
    assert plan_placement(a, "project_plan", None).status == "NEEDS_OWNER_BINDING"


def test_cross_owner_reference_can_be_proposed_but_not_written():
    a = atom(source=ptr("github"))
    t = target("gdrive", "reference")
    p = plan_placement(a, "development_task", t)
    assert p.status == "PROPOSED_NO_EFFECT" and not p.effect_authorized


def test_privacy_downgrade_is_blocked_even_for_references():
    a = atom(source=ptr("humanmodel",privacy="private"))
    p = plan_placement(a, "personal_judgment", target(
        "gdrive", "reference", privacy="shareable"))
    assert p.status == "BLOCKED"
    assert p.reason == "PRIVACY_SCOPE_MISMATCH"


def test_cross_scope_placement_is_blocked():
    a = atom(source=ptr("github",scope="project"))
    p = plan_placement(a, "development_task", target("github",scope="career"))
    assert p.status == "BLOCKED"


def test_stale_canonical_revision_is_blocked():
    a = atom(source=ptr("github",revision="r1"))
    assert plan_placement(a, "development_task",
                          target("github", revision="r2")).reason == "REVISION_MISMATCH"


def test_mismatched_canonical_record_needs_explicit_owner_review():
    a = atom(source=ptr("github"))
    p = plan_placement(a, "development_task", target("github", record="other"))
    assert p.reason == "CANONICAL_RECORD_ID_MISMATCH"


def test_relation_assertions_remain_proposals():
    a,b=atom("one"),atom("two")
    with pytest.raises(ValueError):
        RelationProposal("supersedes",a.atom_id,b.atom_id,status="verified")
    assert RelationProposal("contradicts",a.atom_id,b.atom_id).status == "proposed"


def test_audit_detects_revision_change():
    result = audit_readonly((event("r1"),), (event("r2"),), inventory_complete=True)
    assert [f.kind for f in result] == ["REVISION_MISMATCH"]


def test_audit_detects_same_revision_content_mutation():
    result = audit_readonly((event(),), (event(digest="b"*64),), inventory_complete=True)
    assert [f.kind for f in result] == ["OWNER_CONFLICT"]


def test_partial_listing_does_not_claim_absent_source():
    result = audit_readonly((event(),), (), inventory_complete=False)
    assert [x.kind for x in result] == ["UNKNOWN_COVERAGE"]


def test_complete_listing_can_identify_absent_source():
    result = audit_readonly((event(),), (), inventory_complete=True)
    assert [f.kind for f in result] == ["MISSING_SOURCE"]


def test_observed_partial_coverage_prevents_false_absence():
    result = audit_readonly((event(record="missing"),),
                            (event(record="other",coverage="PARTIAL"),),
                            inventory_complete=True)
    assert "UNKNOWN_COVERAGE" in [f.kind for f in result]
    assert "MISSING_SOURCE" not in [f.kind for f in result]


def test_duplicate_current_revisions_are_conflicts_in_both_orders():
    old = event("r1")
    updated = event("r2")  # identical bytes, changed revision
    for observed in ((old, updated), (updated, old)):
        findings = audit_readonly((old,), observed, inventory_complete=True)
        assert [finding.kind for finding in findings] == ["OWNER_CONFLICT"]
        assert len({finding.source_key for finding in findings}) == 1


def test_conflicting_privacy_in_duplicate_inventory_fails_closed():
    old = event()
    source = SourcePointer("github", "owner-collection", "msg-7", "r1",
                           "project", "shareable", None, "unknown")
    divergent = SourceEvent(source, "a" * 64, "changed", "COMPLETE")
    for observed in ((old, divergent), (divergent, old)):
        findings = audit_readonly((old,), observed, inventory_complete=True)
        assert [finding.kind for finding in findings] == ["PRIVACY_SCOPE_MISMATCH"]


def test_exact_audit_no_change_is_quiet():
    assert audit_readonly((event(),), (event(),), inventory_complete=True) == ()


def test_journal_duplicate_event_is_idempotent(tmp_path):
    store = ReadonlyReceiptJournal(tmp_path/"klm.sqlite")
    first = event()
    assert store.record_event(first) == "RECORDED"
    assert store.record_event(first) == "ALREADY_RECORDED"
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM klm_observations").fetchone()[0] == 1


def test_journal_same_event_identity_conflicting_content_fails(tmp_path):
    store = ReadonlyReceiptJournal(tmp_path/"klm.sqlite")
    store.record_event(event())
    with pytest.raises(ValueError):
        store.record_event(event(digest="c"*64))


def test_journal_plan_never_stores_source_original_text(tmp_path):
    store = ReadonlyReceiptJournal(tmp_path/"klm.sqlite")
    a = atom("人間モデル本人判断（private original）",source=ptr("humanmodel"),
             proposal=meaning(kind="decision"))
    p = plan_placement(a, "personal_judgment", target("humanmodel"))
    assert store.record_atom(a) == "RECORDED"
    assert store.record_plan(p) == "RECORDED"
    assert store.record_plan(p) == "ALREADY_RECORDED"
    raw = store.path.read_bytes()
    assert b"private original" not in raw
    assert a.atom_id.encode() in raw


def test_journal_rejects_missing_target_or_forged_effect_grant(tmp_path):
    store = ReadonlyReceiptJournal(tmp_path/"klm.sqlite")
    a = atom()
    with pytest.raises(ValueError):
        store.record_plan(plan_placement(a,"project_plan",None))
    p = plan_placement(a,"project_plan",target("gdrive","reference"))
    from dataclasses import replace
    with pytest.raises(ValueError):
        replace(p, effect_authorized=True)




def test_existing_symlinked_journal_is_rejected(tmp_path):
    other = tmp_path/"owned.sqlite"
    other.write_bytes(b"unrelated")
    link = tmp_path/"link.sqlite"
    link.symlink_to(other)
    with pytest.raises(PermissionError):
        ReadonlyReceiptJournal(link)
    assert other.read_bytes() == b"unrelated"


def test_receipt_capacity_is_bounded_not_silently_pruned(tmp_path, monkeypatch):
    from ai_foundation import knowledge_lifecycle as klm
    monkeypatch.setattr(klm, "MAX_RECEIPTS", 1)
    store = ReadonlyReceiptJournal(tmp_path/"bounded.sqlite")
    assert store.record_event(event(record="first")) == "RECORDED"
    assert store.record_event(event(record="first")) == "ALREADY_RECORDED"
    with pytest.raises(RuntimeError):
        store.record_event(event(record="second"))
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM klm_observations").fetchone()[0] == 1



def test_semantic_atom_cannot_forge_source_or_execution_admission():
    from dataclasses import replace
    a = atom()
    for forged in (
        {"semantic_status":"reviewed"},
        {"source_authentication":"VERIFIED_OWNER"},
        {"execution_authority":True},
    ):
        with pytest.raises(ValueError):
            replace(a, **forged)


def test_concurrent_exact_replays_preserve_one_event(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    store = ReadonlyReceiptJournal(tmp_path/"concurrent.sqlite")
    with ThreadPoolExecutor(max_workers=6) as pool:
        outcomes=list(pool.map(store.record_event,[event() for _ in range(12)]))
    assert outcomes.count("RECORDED") == 1
    assert outcomes.count("ALREADY_RECORDED") == 11
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM klm_observations").fetchone()[0] == 1


def test_concurrent_different_events_cannot_overflow_capacity(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from ai_foundation import knowledge_lifecycle as klm
    monkeypatch.setattr(klm, "MAX_RECEIPTS", 1)
    store = ReadonlyReceiptJournal(tmp_path/"concurrent-cap.sqlite")

    def attempt(num):
        try:
            return store.record_event(event(record="record-"+str(num)))
        except RuntimeError:
            return "BOUNDED"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes=list(pool.map(attempt, [1,2]))
    assert sorted(outcomes)==["BOUNDED","RECORDED"]
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM klm_observations").fetchone()[0] == 1



def test_atom_receipt_retains_identity_hashes_not_private_semantic_text(tmp_path):
    store = ReadonlyReceiptJournal(tmp_path/"atoms.sqlite")
    a = atom("Owner confidential fact is not a new Canon",
             source=ptr("humanmodel"), proposal=meaning(kind="decision"))
    assert store.record_atom(a) == "RECORDED"
    assert store.record_atom(a) == "ALREADY_RECORDED"
    assert b"Owner confidential fact" not in store.path.read_bytes()
    with sqlite3.connect(store.path) as db:
        row = db.execute(
            "SELECT atom_id,source_sha256,span_sha256,meaning_sha256 "
            "FROM klm_atoms WHERE atom_id=?", (a.atom_id,)).fetchone()
    assert row[:3] == (a.atom_id, a.source_sha256, a.span_sha256)
    assert len(row[3]) == 64


def test_journal_rejects_atom_with_forged_composite_identity(tmp_path):
    from dataclasses import replace
    store = ReadonlyReceiptJournal(tmp_path/"atoms.sqlite")
    a = atom()
    with pytest.raises(ValueError):
        store.record_atom(replace(a, atom_id="e"*64))
    with pytest.raises(ValueError):
        store.record_atom(replace(a, span_sha256="e"*64))


def test_orphan_placement_cannot_be_persisted(tmp_path):
    store = ReadonlyReceiptJournal(tmp_path/"orphan.sqlite")
    a = atom(source=ptr("github"))
    with pytest.raises(ValueError):
        store.record_plan(plan_placement(a, "development_task", target("github")))


def test_relation_receipt_is_scoped_and_exactly_idempotent(tmp_path):
    store = ReadonlyReceiptJournal(tmp_path/"links.sqlite")
    a = atom("first", source=ptr("github",record_id="first"))
    b = atom("second", source=ptr("github",record_id="second"))
    assert store.record_atom(a) == store.record_atom(b) == "RECORDED"
    relation = RelationProposal("contradicts",a.atom_id,b.atom_id)
    assert store.record_relation(relation) == "RECORDED"
    assert store.record_relation(relation) == "ALREADY_RECORDED"
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM klm_relations").fetchone()[0] == 1


def test_relation_fails_closed_on_nonexistent_atom(tmp_path):
    store = ReadonlyReceiptJournal(tmp_path/"links.sqlite")
    a = atom("first",source=ptr("github",record_id="first"))
    b = atom("second",source=ptr("github",record_id="second"))
    store.record_atom(a)
    with pytest.raises(ValueError):
        store.record_relation(RelationProposal("supports",a.atom_id,b.atom_id))


def test_relation_may_not_link_different_scope_or_privacy_without_review(tmp_path):
    store = ReadonlyReceiptJournal(tmp_path/"links.sqlite")
    a = atom("first",source=ptr("github",record_id="first"))
    b = atom("second",source=ptr("github",record_id="second",scope="career"))
    c = atom("third",source=ptr("github",record_id="third",privacy="shareable"))
    for v in (a,b,c):
        store.record_atom(v)
    for other in (b,c):
        with pytest.raises(PermissionError):
            store.record_relation(RelationProposal("depends_on",a.atom_id,other.atom_id))


def test_relation_capacity_preserves_existing_provenance(tmp_path, monkeypatch):
    from ai_foundation import knowledge_lifecycle as klm
    store = ReadonlyReceiptJournal(tmp_path/"links.sqlite")
    ids=[]
    for number in range(3):
        a=atom(f"row-{number}",source=ptr("github",record_id=f"row-{number}"))
        store.record_atom(a)
        ids.append(a.atom_id)
    monkeypatch.setattr(klm, "MAX_RECEIPTS", 1)
    assert store.record_relation(RelationProposal("supports",ids[0],ids[1])) == "RECORDED"
    with pytest.raises(RuntimeError):
        store.record_relation(RelationProposal("supports",ids[0],ids[2]))
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM klm_relations").fetchone()[0] == 1

def test_policy_version_is_explicit_stable_string():
    assert POLICY_VERSION == "klm-input-semantics/v1"
