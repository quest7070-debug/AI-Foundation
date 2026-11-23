from dataclasses import FrozenInstanceError

import pytest

from ai_foundation.code_intelligence import (
    CodeIntelligenceKind,
    CodeIntelligenceQuery,
    CodeIntelligenceRelation,
    CodeIntelligenceResult,
    CodeIntelligenceStatus,
    CodeIntelligenceSubjectKind,
)


class FakeCodeIntelligence:
    def __init__(
        self,
        *,
        status=CodeIntelligenceStatus.OK,
        fresh=True,
        uncertainty="",
    ):
        self.status = status
        self.fresh = fresh
        self.uncertainty = uncertainty
        self.queries = []

    def inspect(self, query):
        self.queries.append(query)

        relations = ()
        if self.status is CodeIntelligenceStatus.OK:
            relations = (
                CodeIntelligenceRelation(
                    target="tests/test_example.py::test_run",
                    relation="TESTED_BY",
                    file="tests/test_example.py",
                    line=12,
                ),
            )

        return CodeIntelligenceResult(
            kind=query.kind,
            subject=query.subject,
            status=self.status,
            relations=relations,
            backend="fake",
            backend_version="1",
            index_revision="rev-1",
            fresh=self.fresh,
            uncertainty=self.uncertainty,
        )


def reference():
    from ai_foundation.semantic_linker import CanonicalReference

    return CanonicalReference(
        source_path="docs/FUTURE_POST_COMPLETION_ARCHITECTURE.md",
        locator="11.2 Required architecture boundary",
        claim_kind="ARCHITECTURE_CONSTRAINT",
    )


def link():
    from ai_foundation.semantic_linker import SemanticLink

    return SemanticLink(
        canonical_reference=reference(),
        code_subject=(
            "src/ai_foundation/compute_routing.py"
            "::ComputeRouter::choose"
        ),
        subject_kind=CodeIntelligenceSubjectKind.SYMBOL,
        evidence_refs=("physical:compute-router",),
        provenance="owner-verified",
    )


def test_semantic_models_are_immutable_derived_references():
    item = link()

    assert item.canonical_reference.source_path.startswith("docs/")
    assert item.provenance == "owner-verified"

    with pytest.raises(FrozenInstanceError):
        item.provenance = "mutated"


def test_linker_does_not_store_canonical_claim_body():
    item = link()

    fields = set(item.canonical_reference.__dataclass_fields__)

    assert fields == {"source_path", "locator", "claim_kind"}
    assert "text" not in fields
    assert "claim" not in fields
    assert "content" not in fields


def test_linker_observes_explicit_link_without_minting_authority():
    from ai_foundation.semantic_linker import FoundationSemanticLinker

    backend = FakeCodeIntelligence()
    subject = FoundationSemanticLinker(backend)

    result = subject.inspect(link(), CodeIntelligenceKind.TESTS)

    assert result.link == link()
    assert result.status is CodeIntelligenceStatus.OK
    assert result.fresh is True
    assert result.index_revision == "rev-1"
    assert len(result.relations) == 1
    assert result.authoritative is False

    assert backend.queries == [
        CodeIntelligenceQuery(
            CodeIntelligenceKind.TESTS,
            link().code_subject,
            CodeIntelligenceSubjectKind.SYMBOL,
        )
    ]


@pytest.mark.parametrize(
    "status",
    [
        CodeIntelligenceStatus.UNKNOWN,
        CodeIntelligenceStatus.UNAVAILABLE,
    ],
)
def test_linker_preserves_backend_failure_semantics(status):
    from ai_foundation.semantic_linker import FoundationSemanticLinker

    backend = FakeCodeIntelligence(
        status=status,
        fresh=False,
        uncertainty="backend evidence incomplete",
    )

    result = FoundationSemanticLinker(backend).inspect(
        link(),
        CodeIntelligenceKind.TESTS,
    )

    assert result.status is status
    assert result.relations == ()
    assert result.fresh is False
    assert result.authoritative is False
    assert "backend evidence incomplete" in result.uncertainty


def test_linker_preserves_stale_observation():
    from ai_foundation.semantic_linker import FoundationSemanticLinker

    backend = FakeCodeIntelligence(
        fresh=False,
        uncertainty="source identity no longer matches explicit refresh",
    )

    result = FoundationSemanticLinker(backend).inspect(
        link(),
        CodeIntelligenceKind.TESTS,
    )

    assert result.status is CodeIntelligenceStatus.OK
    assert result.fresh is False
    assert "source identity" in result.uncertainty


@pytest.mark.parametrize(
    ("source_path", "locator", "provenance"),
    [
        ("", "section", "owner-verified"),
        ("docs/x.md", "", "owner-verified"),
        ("docs/x.md", "section", ""),
    ],
)
def test_link_validation_fails_closed(
    source_path,
    locator,
    provenance,
):
    from ai_foundation.semantic_linker import (
        CanonicalReference,
        FoundationSemanticLinker,
        SemanticLink,
    )

    bad = SemanticLink(
        canonical_reference=CanonicalReference(
            source_path=source_path,
            locator=locator,
            claim_kind="CONSTRAINT",
        ),
        code_subject="src/example.py::Example::run",
        subject_kind=CodeIntelligenceSubjectKind.SYMBOL,
        provenance=provenance,
    )

    backend = FakeCodeIntelligence()
    result = FoundationSemanticLinker(backend).inspect(
        bad,
        CodeIntelligenceKind.TESTS,
    )

    assert result.status is CodeIntelligenceStatus.UNAVAILABLE
    assert result.relations == ()
    assert result.authoritative is False
    assert backend.queries == []
    assert result.uncertainty


def test_link_result_preserves_query_kind():
    from ai_foundation.semantic_linker import FoundationSemanticLinker

    backend = FakeCodeIntelligence()

    result = FoundationSemanticLinker(backend).inspect(
        link(),
        CodeIntelligenceKind.TESTS,
    )

    assert result.kind is CodeIntelligenceKind.TESTS


def test_semantic_classification_contract_is_explicit_and_non_authoritative():
    from ai_foundation.semantic_linker import (
        FoundationSemanticLinker,
        SemanticClassification,
    )

    assert {x.value for x in SemanticClassification} == {
        "MAPPED",
        "PARTIAL",
        "UNMAPPED",
        "CONFLICT",
        "DERIVED_ONLY",
    }

    result = FoundationSemanticLinker(FakeCodeIntelligence()).inspect(
        link(),
        CodeIntelligenceKind.TESTS,
    )

    assert result.classification is SemanticClassification.PARTIAL
    assert result.missing_fields == (
        "purpose",
        "ownership",
        "rationale",
        "failure_semantics",
        "side_effects",
        "change_impact",
    )
    assert result.authoritative is False


def test_invalid_semantic_link_is_unmapped_with_explicit_missing_fields():
    from ai_foundation.semantic_linker import (
        CanonicalReference,
        FoundationSemanticLinker,
        SemanticClassification,
        SemanticLink,
    )

    bad = SemanticLink(
        canonical_reference=CanonicalReference(
            source_path="",
            locator="Required architecture boundary",
            claim_kind="ARCHITECTURE_CONSTRAINT",
        ),
        code_subject=(
            "src/ai_foundation/compute_routing.py"
            "::ComputeRouter::choose"
        ),
        subject_kind=CodeIntelligenceSubjectKind.SYMBOL,
        provenance="owner-verified",
    )

    result = FoundationSemanticLinker(FakeCodeIntelligence()).inspect(
        bad,
        CodeIntelligenceKind.TESTS,
    )

    assert result.classification is SemanticClassification.UNMAPPED
    assert "canonical_reference.source_path" in result.missing_fields
    assert "purpose" in result.missing_fields
    assert "change_impact" in result.missing_fields
    assert result.authoritative is False


def test_backend_failure_keeps_semantic_gap_explicit():
    from ai_foundation.semantic_linker import (
        FoundationSemanticLinker,
        SemanticClassification,
    )

    backend = FakeCodeIntelligence(
        status=CodeIntelligenceStatus.UNAVAILABLE,
        fresh=False,
        uncertainty="backend unavailable",
    )

    result = FoundationSemanticLinker(backend).inspect(
        link(),
        CodeIntelligenceKind.TESTS,
    )

    assert result.classification is SemanticClassification.PARTIAL
    assert "source_relationships" in result.missing_fields
    assert "purpose" in result.missing_fields
    assert result.authoritative is False


class RepositoryInventoryBackend:
    def __init__(
        self,
        *,
        status=CodeIntelligenceStatus.OK,
        fresh=True,
        complete=True,
    ):
        from ai_foundation.code_intelligence import (
            CodeIntelligenceCompleteness,
        )

        self.status = status
        self.fresh = fresh
        self.queries = []
        self.completeness = (
            CodeIntelligenceCompleteness(
                expected_files=2,
                analyzed_files=2 if complete else 1,
                failed_files=() if complete else ("broken.py",),
                unresolved_observations=0,
            )
            if status is CodeIntelligenceStatus.OK
            else None
        )

    def inspect(self, query):
        self.queries.append(query)

        relations = ()
        if self.status is CodeIntelligenceStatus.OK:
            relations = (
                CodeIntelligenceRelation(
                    target="src/ai_foundation/example.py",
                    relation="MODULE",
                    file="src/ai_foundation/example.py",
                    line=1,
                ),
                CodeIntelligenceRelation(
                    target=(
                        "src/ai_foundation/example.py"
                        "::CLASS::Example@3:0"
                    ),
                    relation="CLASS",
                    file="src/ai_foundation/example.py",
                    line=3,
                ),
                # Same source identity may legitimately carry another
                # inventory role; coverage must not silently collapse it.
                CodeIntelligenceRelation(
                    target=(
                        "src/ai_foundation/example.py"
                        "::CLASS::Example@3:0"
                    ),
                    relation="INTERFACE",
                    file="src/ai_foundation/example.py",
                    line=3,
                ),
            )

        return CodeIntelligenceResult(
            kind=query.kind,
            subject=query.subject,
            status=self.status,
            relations=relations,
            backend="inventory-fake",
            backend_version="1",
            index_revision="inventory-revision",
            fresh=self.fresh,
            uncertainty="",
            completeness=self.completeness,
        )


def test_repository_coverage_preserves_every_inventory_observation():
    from ai_foundation.semantic_linker import (
        FoundationSemanticLinker,
        REQUIRED_SEMANTIC_FIELDS,
        SemanticClassification,
    )

    backend = RepositoryInventoryBackend()
    result = FoundationSemanticLinker(backend).repository_coverage()

    assert backend.queries == [
        CodeIntelligenceQuery(
            CodeIntelligenceKind.INVENTORY,
            ".",
            CodeIntelligenceSubjectKind.FILE,
        )
    ]

    assert result.status is CodeIntelligenceStatus.OK
    assert result.fresh is True
    assert result.completeness is not None
    assert result.completeness.complete is True
    assert len(result.records) == 3

    assert [item.inventory_kind for item in result.records] == [
        "MODULE",
        "CLASS",
        "INTERFACE",
    ]

    assert all(
        item.classification is SemanticClassification.UNMAPPED
        for item in result.records
    )
    assert all(
        item.missing_fields == REQUIRED_SEMANTIC_FIELDS
        for item in result.records
    )
    assert all(item.authoritative is False for item in result.records)


def test_repository_coverage_does_not_collapse_duplicate_source_roles():
    from ai_foundation.semantic_linker import FoundationSemanticLinker

    result = FoundationSemanticLinker(
        RepositoryInventoryBackend()
    ).repository_coverage()

    example = [
        item
        for item in result.records
        if item.code_subject.endswith("::CLASS::Example@3:0")
    ]

    assert len(example) == 2
    assert {item.inventory_kind for item in example} == {
        "CLASS",
        "INTERFACE",
    }


def test_repository_coverage_fails_closed_when_inventory_is_incomplete():
    from ai_foundation.semantic_linker import FoundationSemanticLinker

    result = FoundationSemanticLinker(
        RepositoryInventoryBackend(complete=False)
    ).repository_coverage()

    assert result.status is CodeIntelligenceStatus.UNKNOWN
    assert result.records
    assert result.completeness is not None
    assert result.completeness.complete is False
    assert "incomplete" in result.uncertainty


def test_repository_coverage_fails_closed_when_inventory_is_stale():
    from ai_foundation.semantic_linker import FoundationSemanticLinker

    result = FoundationSemanticLinker(
        RepositoryInventoryBackend(fresh=False)
    ).repository_coverage()

    assert result.status is CodeIntelligenceStatus.UNKNOWN
    assert result.records
    assert result.fresh is False
    assert "stale" in result.uncertainty


def test_repository_coverage_propagates_unavailable_inventory():
    from ai_foundation.semantic_linker import FoundationSemanticLinker

    result = FoundationSemanticLinker(
        RepositoryInventoryBackend(
            status=CodeIntelligenceStatus.UNAVAILABLE,
            fresh=False,
        )
    ).repository_coverage()

    assert result.status is CodeIntelligenceStatus.UNAVAILABLE
    assert result.records == ()
    assert result.authoritative is False


def _semantic_block(**overrides):
    import json
    data = {
        "source": "src/ai_foundation/example.py",
        "subject": "src/ai_foundation/example.py::Example::run",
        "subject_kind": "SYMBOL",
        "claim_kind": "ARCHITECTURE_CONSTRAINT",
        "purpose": "run the canonical example",
        "ownership": "Example owner",
        "rationale": "NOT_APPLICABLE",
        "failure_semantics": "fail closed",
        "side_effects": "NONE",
        "change_impact": "requires semantic revalidation",
        "evidence": ["tests/test_example.py::test_run"],
    }
    data.update(overrides)
    return "```foundation-semantic\n" + json.dumps(data) + "\n```\n"


def test_foundation_semantic_parser_produces_exact_existing_semantic_link():
    from ai_foundation.semantic_linker import parse_foundation_semantic
    parsed = parse_foundation_semantic(
        "Canon prose\n" + _semantic_block(),
        "docs/CANON.md",
    )
    assert len(parsed) == 1
    link = parsed[0]
    assert link.code_source_path == "src/ai_foundation/example.py"
    assert link.code_subject == "src/ai_foundation/example.py::Example::run"
    assert link.subject_kind is CodeIntelligenceSubjectKind.SYMBOL
    assert link.canonical_reference.source_path == "docs/CANON.md"
    assert link.canonical_reference.locator == "docs/CANON.md:2"
    assert link.provenance == "docs/CANON.md:2"
    assert link.evidence_refs == ("tests/test_example.py::test_run",)


@pytest.mark.parametrize("text", [
    "```foundation-semantic\n{}\n```\n",
    "```foundation-semantic\nnot-json\n```\n",
    "```foundation-semantic\n{\"source\":\"../escape.py\"}\n```\n",
])
def test_foundation_semantic_parser_fails_closed_on_malformed_declarations(text):
    from ai_foundation.semantic_linker import (
        FoundationSemanticParseError,
        parse_foundation_semantic,
    )
    with pytest.raises(FoundationSemanticParseError):
        parse_foundation_semantic(text, "docs/CANON.md")


def test_foundation_semantic_parser_rejects_duplicate_json_key():
    from ai_foundation.semantic_linker import (
        FoundationSemanticParseError,
        parse_foundation_semantic,
    )
    body = _semantic_block()
    body = body.replace(
        '"purpose": "run the canonical example"',
        '"purpose": "one", "purpose": "two"',
    )
    with pytest.raises(FoundationSemanticParseError, match="duplicate"):
        parse_foundation_semantic(body, "docs/CANON.md")


def test_foundation_semantic_parser_rejects_source_subject_identity_mismatch():
    from ai_foundation.semantic_linker import (
        FoundationSemanticParseError,
        parse_foundation_semantic,
    )
    with pytest.raises(FoundationSemanticParseError, match="identities do not match"):
        parse_foundation_semantic(
            _semantic_block(subject="src/ai_foundation/other.py::Other::run"),
            "docs/CANON.md",
        )


def test_foundation_semantic_parser_rejects_duplicate_identity():
    from ai_foundation.semantic_linker import (
        FoundationSemanticParseError,
        parse_foundation_semantic,
    )
    with pytest.raises(FoundationSemanticParseError, match="duplicate"):
        parse_foundation_semantic(
            _semantic_block() + _semantic_block(purpose="conflicting"),
            "docs/CANON.md",
        )


def test_foundation_semantic_parser_does_not_infer_from_prose_or_other_fences():
    from ai_foundation.semantic_linker import parse_foundation_semantic
    text = (
        "src/ai_foundation/example.py::Example::run purpose ownership\n"
        "```json\n" + _semantic_block().split("\n", 1)[1]
    )
    assert parse_foundation_semantic(text, "docs/CANON.md") == ()


def test_foundation_semantic_parser_requires_exact_unindented_fence():
    from ai_foundation.semantic_linker import parse_foundation_semantic
    assert parse_foundation_semantic(
        "  " + _semantic_block(),
        "docs/CANON.md",
    ) == ()


def test_foundation_semantic_repository_fails_closed_without_docs_root(tmp_path):
    from ai_foundation.semantic_linker import (
        FoundationSemanticParseError,
        parse_foundation_semantic_repository,
    )
    with pytest.raises(FoundationSemanticParseError, match="docs root"):
        parse_foundation_semantic_repository(tmp_path)


def test_repository_coverage_preserves_observed_records_when_inventory_is_incomplete():
    from ai_foundation.code_intelligence import (
        CodeIntelligenceCompleteness,
        CodeIntelligenceRelation,
    )
    from ai_foundation.semantic_linker import FoundationSemanticLinker

    class PartialInventory:
        def inspect(self, query):
            return CodeIntelligenceResult(
                kind=query.kind,
                subject=query.subject,
                status=CodeIntelligenceStatus.UNKNOWN,
                relations=(
                    CodeIntelligenceRelation(
                        target="src/example.ts::start",
                        relation="FUNCTION",
                        file="src/example.ts",
                        line=12,
                    ),
                ),
                backend="infigraph+libcst",
                backend_version="3.2.16;1.9.0",
                index_revision="partial-revision",
                fresh=True,
                uncertainty="one native artifact is not indexed",
                completeness=CodeIntelligenceCompleteness(
                    expected_files=4,
                    analyzed_files=3,
                    failed_files=("native/libfoundation.dylib",),
                ),
            )

    coverage = FoundationSemanticLinker(PartialInventory()).repository_coverage()

    assert coverage.status is CodeIntelligenceStatus.UNKNOWN
    assert coverage.fresh is True
    assert coverage.completeness.complete is False
    assert len(coverage.records) == 1
    assert coverage.records[0].code_subject == "src/example.ts::start"
    assert coverage.records[0].inventory_kind == "FUNCTION"
