"""Thin routing composition for replaceable code-intelligence backends."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import PurePosixPath
import re

from .code_intelligence import (
    CodeIntelligenceCompleteness,
    CodeIntelligenceKind,
    CodeIntelligencePort,
    CodeIntelligenceQuery,
    CodeIntelligenceRelation,
    CodeIntelligenceResult,
    CodeIntelligenceStatus,
)


_LIBCST_KINDS = frozenset(
    {
        CodeIntelligenceKind.INVENTORY,
        CodeIntelligenceKind.SCOPED_VARIABLES,
        CodeIntelligenceKind.READS,
        CodeIntelligenceKind.WRITES,
    }
)


@dataclass(frozen=True)
class CompositeCodeIntelligence:
    """Route queries to the narrow backend that owns their semantics.

    Infigraph owns repository-wide multi-language symbols and the existing
    references, impact, tests and dependency relations. LibCST owns Python
    scope observations and supplies the Python inventory slice; INVENTORY
    merges both without hiding partial structural observations.
    """

    SUPPORTED_KINDS = frozenset(CodeIntelligenceKind)

    structural: CodeIntelligencePort
    scoped_names: CodeIntelligencePort

    def inspect(
        self,
        query: CodeIntelligenceQuery,
    ) -> CodeIntelligenceResult:
        if query.kind is CodeIntelligenceKind.INVENTORY:
            return self._merge_inventory(query)

        if query.kind in _LIBCST_KINDS:
            return self.scoped_names.inspect(query)

        structural_query = query
        if query.subject_kind.value == "SYMBOL":
            match = re.fullmatch(
                r"(?P<path>.+\.py)::CLASS::(?P<name>[A-Za-z_][A-Za-z0-9_]*)@[0-9]+:[0-9]+",
                query.subject,
            )
            if match is not None:
                structural_query = CodeIntelligenceQuery(
                    kind=query.kind,
                    subject=f"{match.group('path')}::{match.group('name')}",
                    subject_kind=query.subject_kind,
                )

        return self.structural.inspect(structural_query)

    def _merge_inventory(
        self,
        query: CodeIntelligenceQuery,
    ) -> CodeIntelligenceResult:
        structural = self.structural.inspect(query)
        scoped = self.scoped_names.inspect(query)
        structural_completeness = structural.completeness
        scoped_completeness = scoped.completeness

        if structural_completeness is None or scoped_completeness is None:
            completeness = None
        else:
            completeness = CodeIntelligenceCompleteness(
                expected_files=structural_completeness.expected_files,
                analyzed_files=structural_completeness.analyzed_files,
                failed_files=tuple(sorted(set(
                    structural_completeness.failed_files
                    + scoped_completeness.failed_files
                ))),
                unresolved_observations=(
                    structural_completeness.unresolved_observations
                    + scoped_completeness.unresolved_observations
                ),
                fallback_files=structural_completeness.fallback_files,
                unaccounted_files=structural_completeness.unaccounted_files,
            )

        scoped_failed_paths = {
            item.split(": ", 1)[0]
            for item in (() if scoped_completeness is None
                         else scoped_completeness.failed_files)
        }
        scoped_covered_paths = {
            relation.file
            for relation in scoped.relations
            if relation.relation == "MODULE"
        }
        scoped_complete = (
            scoped.status is CodeIntelligenceStatus.OK
            and scoped.fresh
            and scoped_completeness is not None
            and scoped_completeness.complete
        )
        relations = []
        for relation in structural.relations:
            is_python = PurePosixPath(relation.file).suffix.lower() in {".py", ".pyi"}
            if (
                not is_python
                or not scoped_complete
                or relation.file not in scoped_covered_paths
                or relation.file in scoped_failed_paths
            ):
                relations.append(relation)
        relations.extend(scoped.relations)
        unique_relations = tuple(sorted(
            set(relations),
            key=lambda item: (
                item.file, -1 if item.line is None else item.line,
                item.relation, item.target,
            ),
        ))

        fresh = structural.fresh and scoped.fresh
        statuses = {structural.status, scoped.status}
        if CodeIntelligenceStatus.UNAVAILABLE in statuses:
            status = CodeIntelligenceStatus.UNAVAILABLE
        elif (
            CodeIntelligenceStatus.OK in statuses
            and len(statuses) == 1
            and fresh
            and completeness is not None
            and completeness.complete
        ):
            status = CodeIntelligenceStatus.OK
        else:
            status = CodeIntelligenceStatus.UNKNOWN

        revision = sha256(
            (structural.index_revision + "\\0" + scoped.index_revision).encode()
        ).hexdigest()
        uncertainty = "; ".join(
            item for item in (
                structural.uncertainty,
                scoped.uncertainty,
            ) if item
        )
        return CodeIntelligenceResult(
            kind=query.kind,
            subject=query.subject,
            status=status,
            relations=unique_relations,
            backend="infigraph+libcst",
            backend_version=(
                f"{structural.backend_version}; {scoped.backend_version}"
            ),
            index_revision=revision,
            fresh=fresh,
            uncertainty=uncertainty,
            completeness=completeness,
        )
