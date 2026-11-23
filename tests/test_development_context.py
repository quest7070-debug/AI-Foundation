from ai_foundation.code_intelligence import (
    CodeIntelligenceKind,
    CodeIntelligenceRelation,
    CodeIntelligenceResult,
    CodeIntelligenceStatus,
    CodeIntelligenceSubjectKind,
)
from ai_foundation.semantic_linker import (
    CanonicalReference,
    FoundationSemanticLinker,
    SemanticLink,
)


SUBJECT = (
    "src/ai_foundation/compute_routing.py"
    "::ComputeRouter::choose"
)


class ContextBackend:
    def __init__(self, *, fresh=True, fail_kind=None):
        self.fresh = fresh
        self.fail_kind = fail_kind
        self.queries = []

    def inspect(self, query):
        self.queries.append(query)

        if query.kind is self.fail_kind:
            return CodeIntelligenceResult(
                kind=query.kind,
                subject=query.subject,
                status=CodeIntelligenceStatus.UNAVAILABLE,
                relations=(),
                backend="fake",
                backend_version="1",
                index_revision="rev-1",
                fresh=False,
                uncertainty=f"{query.kind.value} unavailable",
            )

        mapping = {
            CodeIntelligenceKind.TESTS: (
                CodeIntelligenceRelation(
                    "tests/test_compute_routing.py::test_b",
                    "TESTED_BY",
                    "tests/test_compute_routing.py",
                    20,
                ),
                CodeIntelligenceRelation(
                    "tests/test_compute_routing.py::test_a",
                    "TESTED_BY",
                    "tests/test_compute_routing.py",
                    10,
                ),
            ),
            CodeIntelligenceKind.IMPACT: (
                CodeIntelligenceRelation(
                    "src/consumer.py::Consumer::run",
                    "IMPACT",
                    "src/consumer.py",
                    None,
                ),
            ),
            CodeIntelligenceKind.DEPENDENCIES: (
                CodeIntelligenceRelation(
                    "src/dep.py",
                    "IMPORTS",
                    "src/dep.py",
                    None,
                ),
            ),
        }

        uncertainty = (
            ""
            if self.fresh
            else "source identity no longer matches explicit refresh"
        )

        return CodeIntelligenceResult(
            kind=query.kind,
            subject=query.subject,
            status=CodeIntelligenceStatus.OK,
            relations=mapping.get(query.kind, ()),
            backend="fake",
            backend_version="1",
            index_revision="rev-1",
            fresh=self.fresh,
            uncertainty=uncertainty,
        )


def semantic_link():
    return SemanticLink(
        canonical_reference=CanonicalReference(
            "docs/FUTURE_POST_COMPLETION_ARCHITECTURE.md",
            "11.2 Required architecture boundary",
            "ARCHITECTURE_CONSTRAINT",
        ),
        code_subject=SUBJECT,
        subject_kind=CodeIntelligenceSubjectKind.SYMBOL,
        evidence_refs=(
            "physical:compute-router",
            "test:test_compute_routing",
        ),
        provenance="owner-verified",
    )


def request(max_relations=20):
    from ai_foundation.development_context import DevelopmentRequest

    return DevelopmentRequest(
        text="Safely change ComputeRouter.choose",
        semantic_links=(semantic_link(),),
        max_relations=max_relations,
    )



def test_compiler_uses_file_compatible_queries_for_file_obligation():
    from ai_foundation.development_context import (
        DevelopmentContextCompiler,
        DevelopmentRequest,
    )

    backend = ContextBackend()
    compiler = DevelopmentContextCompiler(
        FoundationSemanticLinker(backend),
        backend,
    )
    link = SemanticLink(
        canonical_reference=CanonicalReference(
            "docs/FUTURE_POST_COMPLETION_ARCHITECTURE.md",
            "file boundary",
            "ARCHITECTURE_CONSTRAINT",
        ),
        code_subject="src/ai_foundation/development_context.py",
        subject_kind=CodeIntelligenceSubjectKind.FILE,
        evidence_refs=("tests/test_development_context.py",),
        provenance="canon",
    )

    result = compiler.compile(
        DevelopmentRequest("Repair the bounded file obligation", (link,))
    )

    assert result.fresh is True
    assert result.uncertainties == ()
    assert [query.kind for query in backend.queries] == [
        CodeIntelligenceKind.DEPENDENCIES,
    ]


def test_compiler_builds_bounded_task_local_context():
    from ai_foundation.development_context import (
        DevelopmentContextCompiler,
    )

    backend = ContextBackend()
    compiler = DevelopmentContextCompiler(
        FoundationSemanticLinker(backend),
        backend,
    )

    result = compiler.compile(request())

    assert result.request == "Safely change ComputeRouter.choose"
    assert result.canonical_references == (
        semantic_link().canonical_reference,
    )
    assert result.code_subjects == (SUBJECT,)

    assert [x.target for x in result.affected_tests] == [
        "tests/test_compute_routing.py::test_a",
        "tests/test_compute_routing.py::test_b",
    ]

    assert [x.target for x in result.impacts] == [
        "src/consumer.py::Consumer::run",
    ]

    assert [x.target for x in result.dependencies] == [
        "src/dep.py",
    ]

    assert result.evidence_refs == (
        "physical:compute-router",
        "test:test_compute_routing",
    )

    assert result.index_revisions == ("rev-1",)
    assert result.fresh is True
    assert result.uncertainties == ()
    assert result.authoritative is False


def test_compiler_is_deterministic():
    from ai_foundation.development_context import (
        DevelopmentContextCompiler,
    )

    backend = ContextBackend()
    compiler = DevelopmentContextCompiler(
        FoundationSemanticLinker(backend),
        backend,
    )

    first = compiler.compile(request())
    second = compiler.compile(request())

    assert first == second


def test_compiler_enforces_global_relation_bound():
    from ai_foundation.development_context import (
        DevelopmentContextCompiler,
    )

    backend = ContextBackend()
    compiler = DevelopmentContextCompiler(
        FoundationSemanticLinker(backend),
        backend,
    )

    result = compiler.compile(request(max_relations=2))

    total = (
        len(result.affected_tests)
        + len(result.impacts)
        + len(result.dependencies)
    )

    assert total == 2
    assert "relation limit reached" in result.uncertainties


def test_compiler_propagates_partial_backend_failure():
    from ai_foundation.development_context import (
        DevelopmentContextCompiler,
    )

    backend = ContextBackend(
        fail_kind=CodeIntelligenceKind.IMPACT,
    )

    result = DevelopmentContextCompiler(
        FoundationSemanticLinker(backend),
        backend,
    ).compile(request())

    assert result.impacts == ()
    assert result.affected_tests
    assert result.dependencies
    assert result.fresh is False
    assert any(
        "IMPACT unavailable" in x
        for x in result.uncertainties
    )


def test_compiler_never_hides_stale_index():
    from ai_foundation.development_context import (
        DevelopmentContextCompiler,
    )

    backend = ContextBackend(fresh=False)

    result = DevelopmentContextCompiler(
        FoundationSemanticLinker(backend),
        backend,
    ).compile(request())

    assert result.fresh is False
    assert any(
        "source identity" in x
        for x in result.uncertainties
    )


def test_empty_request_fails_closed_without_backend_calls():
    from ai_foundation.development_context import (
        DevelopmentContextCompiler,
        DevelopmentRequest,
    )

    backend = ContextBackend()

    result = DevelopmentContextCompiler(
        FoundationSemanticLinker(backend),
        backend,
    ).compile(
        DevelopmentRequest(
            text="",
            semantic_links=(semantic_link(),),
        )
    )

    assert result.fresh is False
    assert result.code_subjects == ()
    assert result.affected_tests == ()
    assert result.impacts == ()
    assert result.dependencies == ()
    assert "development request is empty" in result.uncertainties
    assert backend.queries == []


def test_compiler_classifies_by_query_kind_not_relation_spelling():
    from ai_foundation.development_context import (
        DevelopmentContextCompiler,
    )

    class NonConventionalRelationBackend(ContextBackend):
        def inspect(self, query):
            result = super().inspect(query)

            if (
                query.kind is CodeIntelligenceKind.TESTS
                and result.status is CodeIntelligenceStatus.OK
            ):
                return CodeIntelligenceResult(
                    kind=result.kind,
                    subject=result.subject,
                    status=result.status,
                    relations=(
                        CodeIntelligenceRelation(
                            "tests/test_weird.py::test_x",
                            "BACKEND_SPECIFIC_TEST_EDGE",
                            "tests/test_weird.py",
                            1,
                        ),
                    ),
                    backend=result.backend,
                    backend_version=result.backend_version,
                    index_revision=result.index_revision,
                    fresh=result.fresh,
                    uncertainty=result.uncertainty,
                )

            if (
                query.kind is CodeIntelligenceKind.IMPACT
                and result.status is CodeIntelligenceStatus.OK
            ):
                return CodeIntelligenceResult(
                    kind=result.kind,
                    subject=result.subject,
                    status=result.status,
                    relations=(
                        CodeIntelligenceRelation(
                            "src/weird.py::run",
                            "BACKEND_SPECIFIC_IMPACT_EDGE",
                            "src/weird.py",
                            1,
                        ),
                    ),
                    backend=result.backend,
                    backend_version=result.backend_version,
                    index_revision=result.index_revision,
                    fresh=result.fresh,
                    uncertainty=result.uncertainty,
                )

            return result

    backend = NonConventionalRelationBackend()

    result = DevelopmentContextCompiler(
        FoundationSemanticLinker(backend),
        backend,
    ).compile(request())

    assert [x.target for x in result.affected_tests] == [
        "tests/test_weird.py::test_x",
    ]
    assert [x.target for x in result.impacts] == [
        "src/weird.py::run",
    ]
