"""Bounded task-local development context over verified semantic links.

The compiler is not a memory system, coding-agent framework, canonical store,
or authority source.  It selects derived repository observations for a
bounded development request.
"""

from __future__ import annotations

from dataclasses import dataclass

from .code_intelligence import (
    CodeIntelligenceKind,
    CodeIntelligencePort,
    CodeIntelligenceQuery,
    CodeIntelligenceRelation,
    CodeIntelligenceStatus,
    CodeIntelligenceSubjectKind,
)
from .semantic_linker import (
    CanonicalReference,
    FoundationSemanticLinker,
    SemanticLink,
)


@dataclass(frozen=True)
class DevelopmentRequest:
    text: str
    semantic_links: tuple[SemanticLink, ...]
    max_relations: int = 100


@dataclass(frozen=True)
class DevelopmentContext:
    request: str
    canonical_references: tuple[CanonicalReference, ...] = ()
    code_subjects: tuple[str, ...] = ()
    affected_tests: tuple[CodeIntelligenceRelation, ...] = ()
    impacts: tuple[CodeIntelligenceRelation, ...] = ()
    dependencies: tuple[CodeIntelligenceRelation, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    index_revisions: tuple[str, ...] = ()
    fresh: bool = False
    uncertainties: tuple[str, ...] = ()
    authoritative: bool = False


class DevelopmentContextCompiler:
    """Compile the smallest deterministic context supported by explicit links."""

    def __init__(
        self,
        semantic_linker: FoundationSemanticLinker,
        code_intelligence: CodeIntelligencePort,
    ) -> None:
        self.semantic_linker = semantic_linker
        self.code_intelligence = code_intelligence

    def compile(self, request: DevelopmentRequest) -> DevelopmentContext:
        text = request.text.strip()

        if not text:
            return DevelopmentContext(
                request=request.text,
                uncertainties=("development request is empty",),
            )

        if not request.semantic_links:
            return DevelopmentContext(
                request=text,
                uncertainties=("no verified semantic links supplied",),
            )

        if request.max_relations < 1:
            return DevelopmentContext(
                request=text,
                uncertainties=("max_relations must be positive",),
            )

        refs = self._unique(
            link.canonical_reference
            for link in request.semantic_links
        )
        subjects = self._unique(
            link.code_subject
            for link in request.semantic_links
        )
        evidence = self._unique(
            item
            for link in request.semantic_links
            for item in link.evidence_refs
        )

        observations = []

        for link in request.semantic_links:
            if link.subject_kind is CodeIntelligenceSubjectKind.SYMBOL:
                observations.append(
                    self.semantic_linker.inspect(
                        link,
                        CodeIntelligenceKind.TESTS,
                    )
                )
                observations.append(
                    self.semantic_linker.inspect(
                        link,
                        CodeIntelligenceKind.IMPACT,
                    )
                )

            file_subject = self._file_subject(link)
            if file_subject:
                observations.append(
                    self.code_intelligence.inspect(
                        CodeIntelligenceQuery(
                            CodeIntelligenceKind.DEPENDENCIES,
                            file_subject,
                            CodeIntelligenceSubjectKind.FILE,
                        )
                    )
                )

        tests = []
        impacts = []
        dependencies = []
        revisions = []
        uncertainty = []
        fresh = True

        for observation in observations:
            if observation.index_revision:
                revisions.append(observation.index_revision)

            if not observation.fresh:
                fresh = False

            if observation.uncertainty:
                uncertainty.append(observation.uncertainty)

            if observation.status is not CodeIntelligenceStatus.OK:
                fresh = False
                continue

            if observation.kind is CodeIntelligenceKind.TESTS:
                tests.extend(observation.relations)
            elif observation.kind is CodeIntelligenceKind.IMPACT:
                impacts.extend(observation.relations)
            elif observation.kind is CodeIntelligenceKind.DEPENDENCIES:
                dependencies.extend(observation.relations)

        tests = self._sorted_relations(tests)
        impacts = self._sorted_relations(impacts)
        dependencies = self._sorted_relations(dependencies)

        combined = (
            [("test", item) for item in tests]
            + [("impact", item) for item in impacts]
            + [("dependency", item) for item in dependencies]
        )

        if len(combined) > request.max_relations:
            combined = combined[: request.max_relations]
            uncertainty.append("relation limit reached")

        tests = tuple(
            item for kind, item in combined
            if kind == "test"
        )
        impacts = tuple(
            item for kind, item in combined
            if kind == "impact"
        )
        dependencies = tuple(
            item for kind, item in combined
            if kind == "dependency"
        )

        return DevelopmentContext(
            request=text,
            canonical_references=tuple(refs),
            code_subjects=tuple(subjects),
            affected_tests=tests,
            impacts=impacts,
            dependencies=dependencies,
            evidence_refs=tuple(evidence),
            index_revisions=tuple(self._unique(revisions)),
            fresh=fresh,
            uncertainties=tuple(self._unique(uncertainty)),
        )

    @staticmethod
    def _file_subject(link: SemanticLink) -> str:
        if link.subject_kind is CodeIntelligenceSubjectKind.FILE:
            return link.code_subject

        if "::" in link.code_subject:
            return link.code_subject.split("::", 1)[0]

        return ""

    @staticmethod
    def _unique(values):
        return list(dict.fromkeys(values))

    @staticmethod
    def _sorted_relations(values):
        return sorted(
            set(values),
            key=lambda item: (
                item.file or "",
                item.line if item.line is not None else -1,
                item.target,
                item.relation,
            ),
        )
