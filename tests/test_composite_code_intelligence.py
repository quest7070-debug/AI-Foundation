from dataclasses import dataclass, field

import pytest

from ai_foundation.code_intelligence import (
    CodeIntelligenceCompleteness,
    CodeIntelligenceKind,
    CodeIntelligenceQuery,
    CodeIntelligenceRelation,
    CodeIntelligenceResult,
    CodeIntelligenceStatus,
    CodeIntelligenceSubjectKind,
)
from ai_foundation.composite_code_intelligence import (
    CompositeCodeIntelligence,
)


@dataclass
class FakePort:
    name: str
    calls: list[CodeIntelligenceQuery] = field(default_factory=list)

    def inspect(self, query):
        self.calls.append(query)

        return CodeIntelligenceResult(
            kind=query.kind,
            subject=query.subject,
            status=CodeIntelligenceStatus.OK,
            relations=(),
            backend=self.name,
            backend_version="1",
            index_revision="revision",
            fresh=True,
        )


@pytest.mark.parametrize(
    "kind",
    [
        CodeIntelligenceKind.SCOPED_VARIABLES,
        CodeIntelligenceKind.READS,
        CodeIntelligenceKind.WRITES,
    ],
)
def test_scoped_name_queries_route_to_libcst_sidecar(kind):
    structural = FakePort("infigraph")
    scoped = FakePort("libcst")

    composite = CompositeCodeIntelligence(
        structural=structural,
        scoped_names=scoped,
    )

    query = CodeIntelligenceQuery(
        kind=kind,
        subject="src/ai_foundation/example.py",
        subject_kind=CodeIntelligenceSubjectKind.FILE,
    )

    result = composite.inspect(query)

    assert result.backend == "libcst"
    assert scoped.calls == [query]
    assert structural.calls == []


@pytest.mark.parametrize(
    "kind",
    [
        CodeIntelligenceKind.REFERENCES,
        CodeIntelligenceKind.IMPACT,
        CodeIntelligenceKind.TESTS,
        CodeIntelligenceKind.DEPENDENCIES,
        CodeIntelligenceKind.CALLS,
    ],
)
def test_existing_queries_remain_owned_by_structural_backend(kind):
    structural = FakePort("infigraph")
    scoped = FakePort("libcst")

    composite = CompositeCodeIntelligence(
        structural=structural,
        scoped_names=scoped,
    )

    query = CodeIntelligenceQuery(
        kind=kind,
        subject="src/ai_foundation/example.py",
        subject_kind=CodeIntelligenceSubjectKind.FILE,
    )

    result = composite.inspect(query)

    assert result.backend == "infigraph"
    assert structural.calls == [query]
    assert scoped.calls == []


def test_composite_contract_covers_every_query_kind_without_overlap():
    from ai_foundation.infigraph_adapter import InfigraphCodeIntelligence
    from ai_foundation.libcst_adapter import LibCSTCodeIntelligence

    structural = InfigraphCodeIntelligence.SUPPORTED_KINDS
    scoped = LibCSTCodeIntelligence.SUPPORTED_KINDS

    assert structural & scoped == {CodeIntelligenceKind.INVENTORY}
    assert structural | scoped == frozenset(CodeIntelligenceKind)
    assert (
        CompositeCodeIntelligence.SUPPORTED_KINDS
        == frozenset(CodeIntelligenceKind)
    )


def test_canonical_libcst_class_identity_translates_only_at_structural_boundary():
    structural = FakePort("infigraph")
    scoped = FakePort("libcst")
    composite = CompositeCodeIntelligence(
        structural=structural,
        scoped_names=scoped,
    )
    canonical = CodeIntelligenceQuery(
        kind=CodeIntelligenceKind.REFERENCES,
        subject="src/ai_foundation/example.py::CLASS::Example@12:4",
        subject_kind=CodeIntelligenceSubjectKind.SYMBOL,
    )

    result = composite.inspect(canonical)

    assert result.backend == "infigraph"
    assert scoped.calls == []
    assert structural.calls == [
        CodeIntelligenceQuery(
            kind=CodeIntelligenceKind.REFERENCES,
            subject="src/ai_foundation/example.py::Example",
            subject_kind=CodeIntelligenceSubjectKind.SYMBOL,
        )
    ]


@dataclass
class FixedInventoryPort:
    name: str
    status: CodeIntelligenceStatus
    relations: tuple[CodeIntelligenceRelation, ...]
    completeness: CodeIntelligenceCompleteness
    fresh: bool = True
    calls: list[CodeIntelligenceQuery] = field(default_factory=list)

    def inspect(self, query):
        self.calls.append(query)
        return CodeIntelligenceResult(
            kind=query.kind,
            subject=query.subject,
            status=self.status,
            relations=self.relations,
            backend=self.name,
            backend_version="3.2.16" if self.name == "infigraph" else "1.9.0",
            index_revision=self.name + "-revision",
            fresh=self.fresh,
            completeness=self.completeness,
        )


def test_inventory_merges_multilanguage_symbols_with_python_scope_inventory():
    structural = FixedInventoryPort(
        name="infigraph",
        status=CodeIntelligenceStatus.OK,
        relations=(
            CodeIntelligenceRelation("src/a.py::main", "FUNCTION", "src/a.py", 1),
            CodeIntelligenceRelation("src/a.py", "MODULE", "src/a.py", 1),
            CodeIntelligenceRelation("src/a.ts::start", "FUNCTION", "src/a.ts", 2),
            CodeIntelligenceRelation("src/a.ts", "MODULE", "src/a.ts", 1),
            CodeIntelligenceRelation("tests/helper.py::check", "FUNCTION", "tests/helper.py", 4),
            CodeIntelligenceRelation("tests/helper.py", "MODULE", "tests/helper.py", 1),
        ),
        completeness=CodeIntelligenceCompleteness(3, 3),
    )
    scoped = FixedInventoryPort(
        name="libcst",
        status=CodeIntelligenceStatus.OK,
        relations=(
            CodeIntelligenceRelation("src/a.py", "MODULE", "src/a.py", 1),
            CodeIntelligenceRelation("src/a.py::FUNCTION::main@1:0", "FUNCTION", "src/a.py", 1),
            CodeIntelligenceRelation("src/a.py::SCOPED_VARIABLE::value@2:4", "SCOPED_VARIABLE", "src/a.py", 2),
        ),
        completeness=CodeIntelligenceCompleteness(1, 1),
    )
    composite = CompositeCodeIntelligence(structural=structural, scoped_names=scoped)

    result = composite.inspect(CodeIntelligenceQuery(
        CodeIntelligenceKind.INVENTORY,
        ".",
        CodeIntelligenceSubjectKind.FILE,
    ))

    assert result.status is CodeIntelligenceStatus.OK
    assert result.backend == "infigraph+libcst"
    assert result.completeness.complete
    assert {item.file for item in result.relations if item.relation == "MODULE"} == {
        "src/a.py", "src/a.ts", "tests/helper.py",
    }
    assert {item.file for item in result.relations if item.relation == "FUNCTION"} == {
        "src/a.py", "src/a.ts", "tests/helper.py",
    }
    assert any(item.relation == "SCOPED_VARIABLE" for item in result.relations)
    assert structural.calls and scoped.calls


def test_inventory_retains_structural_fallback_when_python_inventory_is_incomplete():
    structural = FixedInventoryPort(
        name="infigraph",
        status=CodeIntelligenceStatus.OK,
        relations=(
            CodeIntelligenceRelation("src/a.py::main", "FUNCTION", "src/a.py", 1),
            CodeIntelligenceRelation("src/a.ts::start", "FUNCTION", "src/a.ts", 2),
        ),
        completeness=CodeIntelligenceCompleteness(2, 2),
    )
    scoped = FixedInventoryPort(
        name="libcst",
        status=CodeIntelligenceStatus.UNKNOWN,
        relations=(),
        completeness=CodeIntelligenceCompleteness(
            1, 0, failed_files=("src/a.py: parser failed",)
        ),
    )
    result = CompositeCodeIntelligence(
        structural=structural,
        scoped_names=scoped,
    ).inspect(CodeIntelligenceQuery(
        CodeIntelligenceKind.INVENTORY,
        ".",
        CodeIntelligenceSubjectKind.FILE,
    ))

    assert result.status is CodeIntelligenceStatus.UNKNOWN
    assert {item.file for item in result.relations} == {"src/a.py", "src/a.ts"}
    assert "src/a.py: parser failed" in result.completeness.failed_files


def test_inventory_keeps_structural_rows_when_scoped_slice_is_unresolved():
    structural = FixedInventoryPort(
        name="infigraph",
        status=CodeIntelligenceStatus.OK,
        relations=(
            CodeIntelligenceRelation("src/a.py", "MODULE", "src/a.py", 1),
            CodeIntelligenceRelation("src/a.py::main", "FUNCTION", "src/a.py", 2),
        ),
        completeness=CodeIntelligenceCompleteness(1, 1),
    )
    scoped = FixedInventoryPort(
        name="libcst",
        status=CodeIntelligenceStatus.UNKNOWN,
        relations=(
            CodeIntelligenceRelation("src/a.py", "MODULE", "src/a.py", 1),
        ),
        completeness=CodeIntelligenceCompleteness(
            1, 1, unresolved_observations=1
        ),
    )
    result = CompositeCodeIntelligence(
        structural=structural,
        scoped_names=scoped,
    ).inspect(CodeIntelligenceQuery(
        CodeIntelligenceKind.INVENTORY,
        ".",
        CodeIntelligenceSubjectKind.FILE,
    ))

    assert result.status is CodeIntelligenceStatus.UNKNOWN
    assert any(
        item.target == "src/a.py::main" and item.relation == "FUNCTION"
        for item in result.relations
    )
