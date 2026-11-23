from ai_foundation.code_intelligence import (
    CodeIntelligenceKind,
    CodeIntelligenceRelation,
    CodeIntelligenceResult,
    CodeIntelligenceStatus,
    CodeIntelligenceSubjectKind,
)
from ai_foundation.explainability import (
    ExplainabilityClosure,
    ExplainabilityGate,
    CanonicalReferenceDisposition,
    CanonicalReferenceIndex,
)
from ai_foundation.semantic_linker import (
    CanonicalReference,
    FoundationSemanticLinker,
    SemanticClassification,
    SemanticLink,
)


SUBJECT = "src/ai_foundation/example.py::Example::run"


class Backend:
    def __init__(self, *, fresh=True):
        self.fresh = fresh

    def inspect(self, query):
        relations = ()

        if query.kind is CodeIntelligenceKind.TESTS:
            relations = (
                CodeIntelligenceRelation(
                    "tests/test_example.py::test_run",
                    "TESTED_BY",
                    "tests/test_example.py",
                    10,
                ),
            )
        elif query.kind is CodeIntelligenceKind.IMPACT:
            relations = (
                CodeIntelligenceRelation(
                    "src/consumer.py::run",
                    "IMPACT",
                    "src/consumer.py",
                    4,
                ),
            )
        elif query.kind is CodeIntelligenceKind.REFERENCES:
            relations = (
                CodeIntelligenceRelation(
                    "docs/example.md",
                    "REFERENCE",
                    "docs/example.md",
                    3,
                ),
            )

        return CodeIntelligenceResult(
            kind=query.kind,
            subject=query.subject,
            status=CodeIntelligenceStatus.OK,
            relations=relations,
            backend="fake",
            backend_version="1",
            index_revision="rev-1",
            fresh=self.fresh,
            uncertainty="" if self.fresh else "stale",
        )


def grounded_link(**overrides):
    values = dict(
        canonical_reference=CanonicalReference(
            "docs/END_GOAL.md",
            "Example invariant",
            "INVARIANT",
        ),
        code_subject=SUBJECT,
        subject_kind=CodeIntelligenceSubjectKind.SYMBOL,
        evidence_refs=("runtime:example",),
        provenance="owner-verified",
        purpose="perform bounded example behavior",
        ownership="Foundation Example boundary",
        rationale="required by Example invariant",
        failure_semantics="failure is explicit",
        side_effects="none",
        change_impact="rerun affected deterministic test and evidence",
    )
    values.update(overrides)
    return SemanticLink(**values)


def closure(*, fresh=True):
    return ExplainabilityClosure(
        FoundationSemanticLinker(Backend(fresh=fresh))
    )


def test_explicit_grounding_can_be_mapped_without_semantic_inference():
    item = closure().rebuild((grounded_link(),))

    assert item.fresh is True
    assert item.conflicts == ()
    assert item.orphans == ()
    assert len(item.traces) == 1
    assert item.traces[0].classification is SemanticClassification.MAPPED
    assert item.traces[0].missing_fields == ()
    assert item.authoritative is False


def test_file_grounding_uses_file_compatible_dependency_observation():
    file_subject = "src/ai_foundation/example.py"
    item = closure().rebuild((
        grounded_link(
            code_subject=file_subject,
            subject_kind=CodeIntelligenceSubjectKind.FILE,
        ),
    ))

    trace = item.traces[0]
    assert trace.classification is SemanticClassification.MAPPED
    assert tuple(observation.kind for observation in trace.observations) == (
        CodeIntelligenceKind.DEPENDENCIES,
    )
    preflight = closure().preflight(item, (file_subject,))
    assert preflight.gate is ExplainabilityGate.READY
    assert preflight.tests == ()
    assert preflight.evidence_refs == ("runtime:example",)


def test_missing_semantic_field_remains_explicit_and_blocks_preflight():
    item = closure().rebuild((
        grounded_link(ownership=""),
    ))

    trace = item.traces[0]
    assert trace.classification is SemanticClassification.PARTIAL
    assert "ownership" in trace.missing_fields
    assert SUBJECT in item.orphans

    preflight = closure().preflight(item, (SUBJECT,))
    assert preflight.gate is ExplainabilityGate.BLOCKED
    assert any("ownership" in x for x in preflight.blockers)


def test_bidirectional_trace_uses_same_derived_snapshot():
    engine = closure()
    item = engine.rebuild((grounded_link(),))

    down = engine.descend(
        item,
        "docs/END_GOAL.md",
        "Example invariant",
    )
    up = engine.ascend(item, SUBJECT)

    assert down == up
    assert down[0].link.code_subject == SUBJECT
    assert down[0].link.purpose == "perform bounded example behavior"
    assert down[0].link.ownership == "Foundation Example boundary"


def test_rebuild_is_deterministic_for_same_inputs_and_source_revision():
    engine = closure()

    first = engine.rebuild((grounded_link(),))
    second = engine.rebuild((grounded_link(),))

    assert first == second
    assert first.revision == second.revision


def test_preflight_returns_canon_tests_and_evidence_before_mutation():
    engine = closure()
    item = engine.rebuild((grounded_link(),))

    result = engine.preflight(item, (SUBJECT,))

    assert result.gate is ExplainabilityGate.READY
    assert result.affected_subjects == (SUBJECT,)
    assert result.canonical_references == (
        "docs/END_GOAL.md::Example invariant::INVARIANT",
    )
    assert result.tests == ("tests/test_example.py::test_run",)
    assert result.evidence_refs == ("runtime:example",)
    assert result.blockers == ()


def test_preflight_fails_closed_for_unexplained_subject():
    engine = closure()
    item = engine.rebuild((grounded_link(),))

    result = engine.preflight(
        item,
        ("src/unknown.py::run",),
    )

    assert result.gate is ExplainabilityGate.BLOCKED
    assert any(
        "unexplained behavior-defining element" in x
        for x in result.blockers
    )


def test_preflight_fails_closed_on_stale_required_source_evidence():
    engine = closure(fresh=False)
    item = engine.rebuild((grounded_link(),))

    assert item.fresh is False

    result = engine.preflight(item, (SUBJECT,))
    assert result.gate is ExplainabilityGate.BLOCKED
    assert any("stale" in x for x in result.blockers)


def test_explicit_conflict_is_surfaced_and_blocks_gate():
    engine = closure()
    item = engine.rebuild((
        grounded_link(
            uncertainty=(
                "CONFLICT: canonical invariant disagrees "
                "with verified runtime evidence"
            ),
        ),
    ))

    assert item.implementation_driving_conflict_count == 1
    assert (
        item.traces[0].classification
        is SemanticClassification.CONFLICT
    )

    result = engine.preflight(item, (SUBJECT,))
    assert result.gate is ExplainabilityGate.BLOCKED
    assert any("conflict" in x.lower() for x in result.blockers)


def test_post_change_drift_rechecks_same_trace_and_reports_orphan():
    engine = closure()

    before = engine.rebuild((grounded_link(),))
    after = engine.rebuild(())

    result = engine.drift_check(before, after, (SUBJECT,))

    assert result.gate is ExplainabilityGate.BLOCKED
    assert any("orphaned" in x for x in result.blockers)


def test_post_change_drift_passes_for_rebuilt_unchanged_trace():
    engine = closure()

    before = engine.rebuild((grounded_link(),))
    after = engine.rebuild((grounded_link(),))

    result = engine.drift_check(before, after, (SUBJECT,))

    assert result.gate is ExplainabilityGate.READY
    assert result.before_revision == result.after_revision
    assert result.blockers == ()
    assert result.authoritative is False


class RepositoryBackend(Backend):
    def __init__(self, *, fresh=True, complete=True):
        super().__init__(fresh=fresh)
        self.complete = complete

    def inspect(self, query):
        from ai_foundation.code_intelligence import (
            CodeIntelligenceCompleteness,
        )

        if query.kind is CodeIntelligenceKind.INVENTORY:
            completeness = CodeIntelligenceCompleteness(
                expected_files=1,
                analyzed_files=1 if self.complete else 0,
                failed_files=() if self.complete else ("example.py",),
                unresolved_observations=0,
            )

            return CodeIntelligenceResult(
                kind=query.kind,
                subject=query.subject,
                status=CodeIntelligenceStatus.OK,
                relations=(
                    CodeIntelligenceRelation(
                        SUBJECT,
                        "METHOD",
                        "src/ai_foundation/example.py",
                        10,
                    ),
                    CodeIntelligenceRelation(
                        "src/ai_foundation/example.py::local@12:4",
                        "SCOPED_VARIABLE",
                        "src/ai_foundation/example.py",
                        12,
                    ),
                ),
                backend="fake",
                backend_version="1",
                index_revision="inventory-rev-1",
                fresh=self.fresh,
                uncertainty="" if self.fresh else "stale inventory",
                completeness=completeness,
            )

        return super().inspect(query)


def repository_closure(*, fresh=True, complete=True):
    return ExplainabilityClosure(
        FoundationSemanticLinker(
            RepositoryBackend(
                fresh=fresh,
                complete=complete,
            )
        )
    )


def test_repository_rebuild_preserves_inventory_without_inventing_meaning():
    engine = repository_closure()

    snapshot = engine.rebuild_repository(())

    assert snapshot.fresh is True
    assert len(snapshot.coverage) == 2
    assert snapshot.traces == ()

    assert all(
        item.classification is SemanticClassification.UNMAPPED
        for item in snapshot.coverage
    )

    assert all(
        item.authoritative is False
        for item in snapshot.coverage
    )


def test_repository_rebuild_enriches_only_explicitly_grounded_subject():
    engine = repository_closure()

    snapshot = engine.rebuild_repository((grounded_link(),))

    by_subject = {
        item.code_subject: item
        for item in snapshot.coverage
    }

    assert (
        by_subject[SUBJECT].classification
        is SemanticClassification.MAPPED
    )

    assert (
        by_subject[
            "src/ai_foundation/example.py::local@12:4"
        ].classification
        is SemanticClassification.UNMAPPED
    )


def test_repository_rebuild_is_deterministic():
    engine = repository_closure()

    first = engine.rebuild_repository((grounded_link(),))
    second = engine.rebuild_repository((grounded_link(),))

    assert first == second
    assert first.revision == second.revision


def test_repository_rebuild_fails_closed_on_stale_inventory():
    engine = repository_closure(fresh=False)

    snapshot = engine.rebuild_repository((grounded_link(),))

    assert snapshot.fresh is False
    assert snapshot.coverage == ()


def test_repository_rebuild_fails_closed_on_incomplete_inventory():
    engine = repository_closure(complete=False)

    snapshot = engine.rebuild_repository((grounded_link(),))

    assert snapshot.fresh is False
    assert snapshot.coverage == ()


def test_repository_preflight_blocks_derived_only_target():
    engine = repository_closure()
    snapshot = engine.rebuild_repository(())

    result = engine.repository_preflight(
        snapshot,
        (SUBJECT,),
    )

    assert result.gate is ExplainabilityGate.BLOCKED
    assert any(
        "grounded canonical lineage" in item
        or "unexplained behavior-defining element" in item
        for item in result.blockers
    )


def test_repository_preflight_allows_grounded_inventory_target():
    engine = repository_closure()
    snapshot = engine.rebuild_repository((grounded_link(),))

    result = engine.repository_preflight(
        snapshot,
        (SUBJECT,),
    )

    assert result.gate is ExplainabilityGate.READY
    assert result.blockers == ()



def test_canonical_reference_index_is_exact_and_deterministic(tmp_path):
    from ai_foundation.explainability import CanonicalReferenceIndex

    docs = tmp_path / "docs"
    docs.mkdir()

    (docs / "A.md").write_text(
        "Authority lives in `src/ai_foundation/guard.py`.\n"
        "Also see src/ai_foundation/capability_request.py.\n"
        "Not a source path: ai_foundation/guard.py\n"
    )

    first = CanonicalReferenceIndex.rebuild(tmp_path)
    second = CanonicalReferenceIndex.rebuild(tmp_path)

    assert first == second
    assert first.revision == second.revision
    assert tuple(
        item.source_path
        for item in first.references
    ) == (
        "src/ai_foundation/capability_request.py",
        "src/ai_foundation/guard.py",
    )
    assert all(item.authoritative is False for item in first.references)


def test_canonical_reference_index_does_not_infer_semantics(tmp_path):
    from ai_foundation.explainability import CanonicalReferenceIndex

    docs = tmp_path / "docs"
    docs.mkdir()

    (docs / "A.md").write_text(
        "src/ai_foundation/guard.py owns important behavior.\n"
    )

    index = CanonicalReferenceIndex.rebuild(tmp_path)

    refs = index.for_source("src/ai_foundation/guard.py")

    assert len(refs) == 1
    assert refs[0].canonical_path == "docs/A.md"
    assert refs[0].line == 1

    # The observation intentionally has no semantic-field properties.
    for field in (
        "purpose",
        "ownership",
        "rationale",
        "failure_semantics",
        "side_effects",
        "change_impact",
    ):
        assert not hasattr(refs[0], field)


def test_canonical_reference_index_rejects_fuzzy_paths(tmp_path):
    from ai_foundation.explainability import CanonicalReferenceIndex

    docs = tmp_path / "docs"
    docs.mkdir()

    (docs / "A.md").write_text(
        "guard.py\n"
        "ai_foundation/guard.py\n"
        "src/ai_foundation/guard.py\n"
    )

    index = CanonicalReferenceIndex.rebuild(tmp_path)

    assert tuple(
        item.source_path
        for item in index.references
    ) == ("src/ai_foundation/guard.py",)


def test_unlinked_repository_inventory_remains_unmapped():
    engine = repository_closure()

    snapshot = engine.rebuild_repository(())

    assert snapshot.coverage
    assert all(
        item.classification is SemanticClassification.UNMAPPED
        for item in snapshot.coverage
    )


def test_exact_canonical_reference_does_not_mint_mapped_semantics(tmp_path):
    from ai_foundation.explainability import CanonicalReferenceIndex

    docs = tmp_path / "docs"
    docs.mkdir()

    (docs / "A.md").write_text(
        "See src/ai_foundation/example.py for implementation.\n"
    )

    index = CanonicalReferenceIndex.rebuild(tmp_path)

    assert index.for_source("src/ai_foundation/example.py")
    # Canon navigation evidence and semantic grounding remain separate.
    snapshot = repository_closure().rebuild_repository(())
    by_subject = {
        item.code_subject: item
        for item in snapshot.coverage
    }
    assert by_subject[SUBJECT].classification is SemanticClassification.UNMAPPED



def test_repository_canon_rebuild_consumes_explicit_semantic_declaration(tmp_path):
    import json

    docs = tmp_path / "docs"
    docs.mkdir()
    source = tmp_path / "src" / "ai_foundation"
    source.mkdir(parents=True)
    (source / "example.py").write_text("VALUE = 1\n")

    declaration = {
        "source": "src/ai_foundation/example.py",
        "subject": SUBJECT,
        "subject_kind": "SYMBOL",
        "claim_kind": "INVARIANT",
        "purpose": "perform bounded example behavior",
        "ownership": "Foundation Example boundary",
        "rationale": "required by Example invariant",
        "failure_semantics": "failure is explicit",
        "side_effects": "NONE",
        "change_impact": "rerun deterministic evidence",
        "evidence": ["runtime:example"],
    }
    (docs / "A.md").write_text(
        "Example invariant.\n" +
        "```foundation-semantic\n" +
        json.dumps(declaration) +
        "\n```\n"
    )

    snapshot = repository_closure().rebuild_repository_with_canon(
        tmp_path, ()
    )

    assert len(snapshot.traces) == 1
    assert snapshot.traces[0].classification is SemanticClassification.MAPPED
    assert snapshot.traces[0].link.code_subject == SUBJECT
    assert snapshot.traces[0].link.canonical_reference.locator == "docs/A.md:2"
    assert snapshot.authoritative is False


def test_repository_canon_lineage_is_deterministic(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()

    source = tmp_path / "src" / "ai_foundation"
    source.mkdir(parents=True)

    (source / "example.py").write_text("VALUE = 1\n")
    (docs / "A.md").write_text(
        "See src/ai_foundation/example.py.\n"
    )

    engine = repository_closure()

    first = engine.rebuild_repository_with_canon(
        tmp_path,
        (),
    )
    second = engine.rebuild_repository_with_canon(
        tmp_path,
        (),
    )

    assert first == second
    assert first.revision == second.revision
    assert first.canonical_revision
    assert tuple(
        item.source_path
        for item in first.canonical_references
    ) == ("src/ai_foundation/example.py",)
    assert first.orphans == ()


def test_exact_canon_reference_does_not_change_semantic_classification(
    tmp_path,
):
    docs = tmp_path / "docs"
    docs.mkdir()

    source = tmp_path / "src" / "ai_foundation"
    source.mkdir(parents=True)

    (source / "example.py").write_text("VALUE = 1\n")
    (docs / "A.md").write_text(
        "This explicitly names src/ai_foundation/example.py.\n"
    )

    snapshot = repository_closure().rebuild_repository_with_canon(
        tmp_path,
        (),
    )

    assert snapshot.canonical_references
    assert snapshot.coverage
    assert all(
        item.classification is SemanticClassification.UNMAPPED
        for item in snapshot.coverage
    )


def test_missing_exact_canonical_source_is_orphan(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()

    (docs / "A.md").write_text(
        "See src/ai_foundation/missing.py.\n"
    )

    snapshot = repository_closure().rebuild_repository_with_canon(
        tmp_path,
        (),
    )

    assert (
        "canonical-source-missing:"
        "src/ai_foundation/missing.py"
    ) in snapshot.orphans


def test_canonical_change_changes_repository_revision(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()

    source = tmp_path / "src" / "ai_foundation"
    source.mkdir(parents=True)

    (source / "example.py").write_text("VALUE = 1\n")

    canon = docs / "A.md"
    canon.write_text(
        "See src/ai_foundation/example.py.\n"
    )

    engine = repository_closure()

    before = engine.rebuild_repository_with_canon(
        tmp_path,
        (),
    )

    canon.write_text(
        "Changed exact lineage: "
        "src/ai_foundation/example.py.\n"
    )

    after = engine.rebuild_repository_with_canon(
        tmp_path,
        (),
    )

    assert before.canonical_revision != after.canonical_revision
    assert before.revision != after.revision


def test_canonical_lineage_never_mints_authority(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()

    source = tmp_path / "src" / "ai_foundation"
    source.mkdir(parents=True)

    (source / "example.py").write_text("VALUE = 1\n")
    (docs / "A.md").write_text(
        "Authority implementation: "
        "src/ai_foundation/example.py.\n"
    )

    snapshot = repository_closure().rebuild_repository_with_canon(
        tmp_path,
        (),
    )

    assert snapshot.authoritative is False
    assert all(
        item.authoritative is False
        for item in snapshot.canonical_references
    )


def test_suggested_module_reference_is_proposed_not_orphan(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()

    (docs / "future.md").write_text(
        "Suggested new module: "
        "src/ai_foundation/not_yet_created.py\n"
    )

    index = CanonicalReferenceIndex.rebuild(tmp_path)

    assert len(index.references) == 1
    assert (
        index.references[0].disposition
        is CanonicalReferenceDisposition.PROPOSED
    )
    assert index.missing_sources(tmp_path) == ()


def test_suggested_module_reference_remains_observable(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()

    (docs / "future.md").write_text(
        "Suggested module: "
        "src/ai_foundation/future.py\n"
    )

    index = CanonicalReferenceIndex.rebuild(tmp_path)

    refs = index.for_source(
        "src/ai_foundation/future.py"
    )

    assert len(refs) == 1
    assert (
        refs[0].disposition
        is CanonicalReferenceDisposition.PROPOSED
    )


def test_current_missing_reference_remains_missing(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()

    (docs / "current.md").write_text(
        "Implementation: "
        "src/ai_foundation/missing_current.py\n"
    )

    index = CanonicalReferenceIndex.rebuild(tmp_path)

    assert (
        index.references[0].disposition
        is CanonicalReferenceDisposition.IMPLEMENTATION
    )
    assert index.missing_sources(tmp_path) == (
        "src/ai_foundation/missing_current.py",
    )


def test_disposition_participates_in_canonical_revision(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()

    path = docs / "A.md"

    path.write_text(
        "Suggested module: "
        "src/ai_foundation/example.py\n"
    )
    proposed = CanonicalReferenceIndex.rebuild(tmp_path)

    path.write_text(
        "Implementation: "
        "src/ai_foundation/example.py\n"
    )
    implementation = CanonicalReferenceIndex.rebuild(tmp_path)

    assert proposed.revision != implementation.revision

