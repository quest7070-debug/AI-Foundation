from dataclasses import FrozenInstanceError

import pytest

from ai_foundation.code_intelligence import (
    CodeIntelligenceKind,
    CodeIntelligencePort,
    CodeIntelligenceQuery,
    CodeIntelligenceRelation,
    CodeIntelligenceResult,
    CodeIntelligenceStatus,
    CodeIntelligenceSubjectKind,
)


class FakeCodeIntelligence:
    def inspect(self, query: CodeIntelligenceQuery) -> CodeIntelligenceResult:
        return CodeIntelligenceResult(
            kind=query.kind,
            subject=query.subject,
            status=CodeIntelligenceStatus.OK,
            relations=(
                CodeIntelligenceRelation(
                    target="tests/test_example.py::test_subject",
                    relation="TEST",
                    file="tests/test_example.py",
                    line=12,
                ),
            ),
            backend="fake",
            backend_version="1",
            index_revision="index-1",
            fresh=True,
        )


def test_port_is_backend_neutral():
    port: CodeIntelligencePort = FakeCodeIntelligence()

    result = port.inspect(
        CodeIntelligenceQuery(
            CodeIntelligenceKind.TESTS,
            "src/ai_foundation/example.py::Example::run",
                    CodeIntelligenceSubjectKind.SYMBOL,
)
    )

    assert result.status is CodeIntelligenceStatus.OK
    assert result.relations == (
        CodeIntelligenceRelation(
            target="tests/test_example.py::test_subject",
            relation="TEST",
            file="tests/test_example.py",
            line=12,
        ),
    )
    assert result.backend == "fake"
    assert result.backend_version == "1"
    assert result.index_revision == "index-1"
    assert result.fresh is True


@pytest.mark.parametrize(
    "kind",
    [
        CodeIntelligenceKind.REFERENCES,
        CodeIntelligenceKind.IMPACT,
        CodeIntelligenceKind.TESTS,
        CodeIntelligenceKind.DEPENDENCIES,
    ],
)
def test_initial_query_surface_is_explicit(kind):
    query = CodeIntelligenceQuery(
        kind,
        "src/ai_foundation/example.py",
            CodeIntelligenceSubjectKind.SYMBOL,
)
    assert query.kind is kind


def test_reference_can_preserve_source_location():
    relation = CodeIntelligenceRelation(
        target="tests/test_compute_routing.py::test_example",
        relation="REFERENCE",
        file="tests/test_compute_routing.py",
        line=41,
    )

    assert relation.file == "tests/test_compute_routing.py"
    assert relation.line == 41


def test_dependency_can_preserve_direction():
    imported = CodeIntelligenceRelation(
        target="src/ai_foundation/routing_capabilities.py",
        relation="IMPORTS",
    )
    importer = CodeIntelligenceRelation(
        target="src/ai_foundation/inference_composition.py",
        relation="IMPORTED_BY",
    )

    assert imported.relation == "IMPORTS"
    assert importer.relation == "IMPORTED_BY"


def test_known_subject_with_no_relations_is_distinct_from_unknown():
    known = CodeIntelligenceResult(
        kind=CodeIntelligenceKind.REFERENCES,
        subject="src/example.py::known",
        status=CodeIntelligenceStatus.OK,
        relations=(),
        backend="fake",
        backend_version="1",
        index_revision="index-1",
        fresh=True,
    )

    unknown = CodeIntelligenceResult(
        kind=CodeIntelligenceKind.REFERENCES,
        subject="src/example.py::missing",
        status=CodeIntelligenceStatus.UNKNOWN,
        relations=(),
        backend="fake",
        backend_version="1",
        index_revision="index-1",
        fresh=True,
        uncertainty="subject not present in backend index",
    )

    assert known.status is CodeIntelligenceStatus.OK
    assert unknown.status is CodeIntelligenceStatus.UNKNOWN
    assert known.relations == unknown.relations == ()


def test_backend_unavailable_is_not_unknown_subject():
    result = CodeIntelligenceResult(
        kind=CodeIntelligenceKind.IMPACT,
        subject="src/example.py::subject",
        status=CodeIntelligenceStatus.UNAVAILABLE,
        relations=(),
        backend="fake",
        backend_version="",
        index_revision="",
        fresh=False,
        uncertainty="backend unavailable",
    )

    assert result.status is CodeIntelligenceStatus.UNAVAILABLE
    assert result.fresh is False


def test_query_relation_and_result_are_immutable():
    query = CodeIntelligenceQuery(
        CodeIntelligenceKind.REFERENCES,
        "src/example.py",
            CodeIntelligenceSubjectKind.SYMBOL,
)
    relation = CodeIntelligenceRelation(
        target="tests/test_example.py",
        relation="REFERENCE",
    )
    result = CodeIntelligenceResult(
        kind=query.kind,
        subject=query.subject,
        status=CodeIntelligenceStatus.OK,
        relations=(relation,),
        backend="fake",
        backend_version="1",
        index_revision="index-1",
        fresh=False,
        uncertainty="index freshness not established",
    )

    with pytest.raises(FrozenInstanceError):
        query.subject = "other"

    with pytest.raises(FrozenInstanceError):
        relation.target = "other"

    with pytest.raises(FrozenInstanceError):
        result.fresh = True


def test_query_requires_explicit_symbol_subject_kind():
    from ai_foundation.code_intelligence import CodeIntelligenceSubjectKind

    query = CodeIntelligenceQuery(
        CodeIntelligenceKind.REFERENCES,
        "src/example.py::Example::run",
        CodeIntelligenceSubjectKind.SYMBOL,
    )

    assert query.subject_kind is CodeIntelligenceSubjectKind.SYMBOL


def test_query_requires_explicit_file_subject_kind():
    from ai_foundation.code_intelligence import CodeIntelligenceSubjectKind

    query = CodeIntelligenceQuery(
        CodeIntelligenceKind.DEPENDENCIES,
        "src/example.py",
        CodeIntelligenceSubjectKind.FILE,
    )

    assert query.subject_kind is CodeIntelligenceSubjectKind.FILE
