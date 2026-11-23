"""Deterministic derived Explainability Closure over explicit semantic links.

This module owns no canonical, mutation, filesystem, test or runtime authority.
It composes explicit owner/canon-grounded SemanticLink objects with the existing
CodeIntelligencePort.  Missing meaning remains missing; no semantic inference is
performed here.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from hashlib import sha256
from pathlib import Path
import re
from typing import Iterable

from .code_intelligence import (
    CodeIntelligenceKind,
    CodeIntelligenceStatus,
    CodeIntelligenceSubjectKind,
)
from .semantic_linker import (
    FoundationSemanticLinker,
    SemanticClassification,
    SemanticCoverageRecord,
    SemanticLink,
    SemanticLinkResult,
    parse_foundation_semantic_repository,
)
from .semantic_declarations import parse_semantic_declarations



class ExplainabilityGate(str, Enum):
    READY = "READY"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class ExplainabilityTrace:
    link: SemanticLink
    observations: tuple[SemanticLinkResult, ...]
    classification: SemanticClassification
    missing_fields: tuple[str, ...]
    conflicts: tuple[str, ...] = ()
    authoritative: bool = False


@dataclass(frozen=True)
class ExplainabilitySnapshot:
    traces: tuple[ExplainabilityTrace, ...]
    revision: str
    fresh: bool
    conflicts: tuple[str, ...]
    orphans: tuple[str, ...]
    canonical_references: tuple[CanonicalSourceReference, ...] = ()
    canonical_revision: str = ""
    coverage: tuple[SemanticCoverageRecord, ...] = ()
    authoritative: bool = False

    @property
    def implementation_driving_conflict_count(self) -> int:
        return len(self.conflicts)

    @property
    def coverage_counts(self) -> dict[SemanticClassification, int]:
        counts = {kind: 0 for kind in SemanticClassification}
        for record in self.coverage:
            counts[record.classification] += 1
        return counts


@dataclass(frozen=True)
class ChangePreflight:
    gate: ExplainabilityGate
    affected_subjects: tuple[str, ...]
    canonical_references: tuple[str, ...]
    tests: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    blockers: tuple[str, ...]
    snapshot_revision: str
    authoritative: bool = False


@dataclass(frozen=True)
class DriftCheck:
    gate: ExplainabilityGate
    before_revision: str
    after_revision: str
    stale: bool
    conflicts: tuple[str, ...]
    orphans: tuple[str, ...]
    blockers: tuple[str, ...]
    authoritative: bool = False



class CanonicalReferenceDisposition(str, Enum):
    IMPLEMENTATION = "IMPLEMENTATION"
    PROPOSED = "PROPOSED"


@dataclass(frozen=True)
class CanonicalSourceReference:
    """Exact source-path occurrence observed in canonical Markdown.

    This is navigation/provenance only.  Presence of a path in Canon does not
    supply purpose, ownership, rationale, failure semantics, side effects or
    change impact and therefore cannot mint MAPPED semantic authority.
    """

    source_path: str
    canonical_path: str
    line: int
    text: str
    disposition: CanonicalReferenceDisposition = (
        CanonicalReferenceDisposition.IMPLEMENTATION
    )
    authoritative: bool = False


@dataclass(frozen=True)
class CanonicalReferenceIndex:
    """Rebuildable exact-reference index over repository Markdown.

    No fuzzy matching, semantic inference, symbol guessing or copied second
    specification is performed here.
    """

    references: tuple[CanonicalSourceReference, ...]
    revision: str
    authoritative: bool = False

    @classmethod
    def rebuild(
        cls,
        root: Path,
        *,
        docs_root: str = "docs",
    ) -> "CanonicalReferenceIndex":
        root = Path(root)
        docs = root / docs_root

        references: list[CanonicalSourceReference] = []

        if docs.is_dir():
            for path in sorted(docs.rglob("*.md")):
                try:
                    text = path.read_text()
                except (OSError, UnicodeError):
                    # A partial canonical scan must not silently masquerade as
                    # complete.  Surface it deterministically in the revision.
                    rel = path.relative_to(root).as_posix()
                    references.append(
                        CanonicalSourceReference(
                            source_path="",
                            canonical_path=rel,
                            line=0,
                            text="UNREADABLE_CANONICAL_SOURCE",
                        )
                    )
                    continue

                rel = path.relative_to(root).as_posix()

                for line_number, line in enumerate(
                    text.splitlines(),
                    start=1,
                ):
                    # Exact lexical repository path only.  Stop at characters
                    # that cannot be part of a Python source path.
                    matches = re.findall(
                        r"src/ai_foundation/[A-Za-z0-9_./-]+\.py",
                        line,
                    )

                    for source_path in sorted(set(matches)):
                        stripped = line.strip()
                        lowered = stripped.lower()
                        disposition = (
                            CanonicalReferenceDisposition.PROPOSED
                            if lowered.startswith(
                                (
                                    "suggested module:",
                                    "suggested new module:",
                                )
                            )
                            else CanonicalReferenceDisposition.IMPLEMENTATION
                        )

                        references.append(
                            CanonicalSourceReference(
                                source_path=source_path,
                                canonical_path=rel,
                                line=line_number,
                                text=stripped,
                                disposition=disposition,
                            )
                        )

        stable = tuple(
            sorted(
                references,
                key=lambda item: (
                    item.source_path,
                    item.canonical_path,
                    item.line,
                    item.text,
                ),
            )
        )

        payload = "\n".join(
            (
                item.source_path
                + "\0"
                + item.canonical_path
                + "\0"
                + str(item.line)
                + "\0"
                + item.text
                + "\0"
                + item.disposition.value
            )
            for item in stable
        )

        return cls(
            references=stable,
            revision=sha256(payload.encode()).hexdigest(),
        )

    def for_source(
        self,
        source_path: str,
    ) -> tuple[CanonicalSourceReference, ...]:
        return tuple(
            item
            for item in self.references
            if item.source_path == source_path
        )

    @property
    def referenced_sources(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    item.source_path
                    for item in self.references
                    if item.source_path
                }
            )
        )

    def missing_sources(
        self,
        root: Path,
    ) -> tuple[str, ...]:
        root = Path(root)
        required_sources = tuple(sorted({
            item.source_path
            for item in self.references
            if (
                item.source_path
                and item.disposition
                is CanonicalReferenceDisposition.IMPLEMENTATION
            )
        }))

        return tuple(
            source
            for source in required_sources
            if not (root / source).is_file()
        )

    @property
    def unreadable_sources(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    item.canonical_path
                    for item in self.references
                    if (
                        not item.source_path
                        and item.text == "UNREADABLE_CANONICAL_SOURCE"
                    )
                }
            )
        )

class ExplainabilityClosure:
    """One derived lifecycle for DI04-DI09.

    Links are explicit inputs.  This class does not discover semantic meaning,
    modify canon, mutate source, or create a persistent graph.
    """

    SYMBOL_RELATION_KINDS = (
        CodeIntelligenceKind.TESTS,
        CodeIntelligenceKind.IMPACT,
        CodeIntelligenceKind.REFERENCES,
    )
    FILE_RELATION_KINDS = (
        CodeIntelligenceKind.DEPENDENCIES,
    )

    def __init__(self, linker: FoundationSemanticLinker) -> None:
        self.linker = linker

    def rebuild(
        self,
        links: Iterable[SemanticLink],
    ) -> ExplainabilitySnapshot:
        ordered = tuple(sorted(
            links,
            key=self._link_key,
        ))

        traces = tuple(self._trace(link) for link in ordered)

        conflicts = tuple(sorted({
            conflict
            for trace in traces
            for conflict in trace.conflicts
        }))

        orphans = tuple(sorted(
            trace.link.code_subject
            for trace in traces
            if (
                trace.classification is SemanticClassification.UNMAPPED
                or "ownership" in trace.missing_fields
            )
        ))

        fresh = all(
            observation.fresh
            and observation.status is CodeIntelligenceStatus.OK
            for trace in traces
            for observation in trace.observations
        )

        revision = self._revision(traces)

        return ExplainabilitySnapshot(
            traces=traces,
            revision=revision,
            fresh=fresh,
            conflicts=conflicts,
            orphans=orphans,
        )

    def rebuild_repository_with_canon(
        self,
        root: Path,
        links=(),
        *,
        canonical_paths: Iterable[str] | None = None,
    ) -> ExplainabilitySnapshot:
        """Rebuild repository explainability with exact Canon lineage evidence.

        Exact Markdown source-path references are navigation/provenance facts.
        They never populate semantic fields and never mint MAPPED/PARTIAL
        classification by themselves.
        """
        root = Path(root)

        # Explicit Canon selection uses the validated fail-closed Phase 5A parser.
        # Legacy callers retain their existing repository-wide parser behavior.
        declarations = None
        if canonical_paths is None:
            declared_links = tuple(links) + parse_foundation_semantic_repository(root)
        else:
            declarations = parse_semantic_declarations(
                root, canonical_paths, self.linker.repository_coverage(),
            )
            declared_links = tuple(links) + declarations.links
        snapshot = self.rebuild_repository(declared_links)
        if declarations is not None:
            # A semantic declaration cannot substitute for structural test evidence.
            # Apply this stricter gate only to explicitly selected Canon inputs.
            gated_traces = tuple(
                replace(
                    trace,
                    classification=SemanticClassification.PARTIAL,
                    missing_fields=tuple(sorted(set(
                        trace.missing_fields + ("test_relationships",)
                    ))),
                )
                if trace.link.provenance.startswith("foundation-semantic:")
                and trace.link.subject_kind is CodeIntelligenceSubjectKind.SYMBOL
                and not self._tests(trace)
                else trace
                for trace in snapshot.traces
            )
            snapshot = replace(snapshot, traces=gated_traces)
        canonical = CanonicalReferenceIndex.rebuild(root)

        missing = canonical.missing_sources(root)

        conflicts = tuple(sorted(set(
            snapshot.conflicts
            + (() if declarations is None else declarations.errors)
        )))

        orphans = tuple(
            sorted(
                set(snapshot.orphans)
                | {
                    f"canonical-source-missing:{source}"
                    for source in missing
                }
                | {
                    f"canonical-source-unreadable:{source}"
                    for source in canonical.unreadable_sources
                }
            )
        )

        # Preserve the existing repository revision contract.
        # Canon lineage is additional non-authoritative drift evidence;
        # it is composed with, rather than injected into, the existing
        # repository revision algorithm.
        canonical_payload = (
            snapshot.revision
            + "\0"
            + canonical.revision
            + ("" if declarations is None else "\0" + declarations.revision)
            + "\0"
            + "\0".join(conflicts)
            + "\0"
            + "\0".join(orphans)
        )
        combined_revision = sha256(
            canonical_payload.encode()
        ).hexdigest()

        return replace(
            snapshot,
            canonical_references=canonical.references,
            canonical_revision=canonical.revision,
            conflicts=conflicts,
            orphans=orphans,
            revision=combined_revision,
            fresh=snapshot.fresh and not (declarations and declarations.errors),
        )

    def rebuild_repository(
        self,
        links: Iterable[SemanticLink] = (),
    ) -> ExplainabilitySnapshot:
        """Rebuild one deterministic repository-wide derived view.

        INVENTORY remains source-derived and non-authoritative. Explicit
        SemanticLink objects may enrich matching subjects, but absence of an
        explicit link never causes semantic meaning to be invented.
        """
        semantic_snapshot = self.rebuild(links)
        coverage = self.linker.repository_coverage()

        if (
            coverage.status is not CodeIntelligenceStatus.OK
            or not coverage.fresh
            or coverage.completeness is None
            or not coverage.completeness.complete
        ):
            return ExplainabilitySnapshot(
                traces=semantic_snapshot.traces,
                revision=self._repository_revision(
                    semantic_snapshot,
                    (),
                    coverage.uncertainty,
                ),
                fresh=False,
                conflicts=semantic_snapshot.conflicts,
                orphans=semantic_snapshot.orphans,
                coverage=(),
            )

        by_subject: dict[str, list[ExplainabilityTrace]] = {}
        for trace in semantic_snapshot.traces:
            by_subject.setdefault(trace.link.code_subject, []).append(trace)

        records: list[SemanticCoverageRecord] = []

        for record in coverage.records:
            matching = by_subject.get(record.code_subject, [])

            if not matching:
                classification = record.classification
                missing = record.missing_fields
            else:
                classifications = {
                    trace.classification
                    for trace in matching
                }

                if SemanticClassification.CONFLICT in classifications:
                    classification = SemanticClassification.CONFLICT
                elif classifications == {SemanticClassification.MAPPED}:
                    classification = SemanticClassification.MAPPED
                else:
                    classification = SemanticClassification.PARTIAL

                missing = tuple(dict.fromkeys(
                    field
                    for trace in matching
                    for field in trace.missing_fields
                ))

            records.append(
                SemanticCoverageRecord(
                    inventory_kind=record.inventory_kind,
                    code_subject=record.code_subject,
                    file=record.file,
                    line=record.line,
                    classification=classification,
                    missing_fields=missing,
                    authoritative=False,
                )
            )

        ordered = tuple(sorted(
            records,
            key=lambda item: (
                item.file,
                -1 if item.line is None else item.line,
                item.inventory_kind,
                item.code_subject,
            ),
        ))

        inventory_subjects = {
            record.code_subject
            for record in ordered
        }

        semantic_orphans = tuple(sorted({
            trace.link.code_subject
            for trace in semantic_snapshot.traces
            if trace.link.code_subject not in inventory_subjects
        }))

        conflicts = tuple(sorted(set(
            semantic_snapshot.conflicts
            + tuple(
                f"coverage conflict: {record.code_subject}"
                for record in ordered
                if record.classification
                is SemanticClassification.CONFLICT
            )
        )))

        orphans = tuple(sorted(set(
            semantic_snapshot.orphans
            + semantic_orphans
        )))

        fresh = semantic_snapshot.fresh and coverage.fresh

        return ExplainabilitySnapshot(
            traces=semantic_snapshot.traces,
            revision=self._repository_revision(
                semantic_snapshot,
                ordered,
                coverage.index_revision,
            ),
            fresh=fresh,
            conflicts=conflicts,
            orphans=orphans,
            coverage=ordered,
        )

    def repository_preflight(
        self,
        snapshot: ExplainabilitySnapshot,
        code_subjects: Iterable[str],
    ) -> ChangePreflight:
        """Fail closed unless requested subjects have explicit semantic trace."""
        requested = tuple(sorted(set(code_subjects)))
        result = self.preflight(snapshot, requested)
        blockers = list(result.blockers)

        coverage_by_subject = {
            record.code_subject: record
            for record in snapshot.coverage
        }

        for subject in requested:
            record = coverage_by_subject.get(subject)

            if record is None:
                blockers.append(
                    f"subject absent from repository inventory: {subject}"
                )
                continue

            if record.classification in (
                SemanticClassification.DERIVED_ONLY,
                SemanticClassification.UNMAPPED,
            ):
                blockers.append(
                    "behavior-defining target lacks grounded canonical "
                    f"lineage: {subject}"
                )

            if record.classification is SemanticClassification.CONFLICT:
                blockers.append(
                    f"repository semantic conflict: {subject}"
                )

        blockers = list(dict.fromkeys(blockers))

        return ChangePreflight(
            gate=(
                ExplainabilityGate.BLOCKED
                if blockers
                else ExplainabilityGate.READY
            ),
            affected_subjects=result.affected_subjects,
            canonical_references=result.canonical_references,
            tests=result.tests,
            evidence_refs=result.evidence_refs,
            blockers=tuple(blockers),
            snapshot_revision=snapshot.revision,
        )

    def descend(
        self,
        snapshot: ExplainabilitySnapshot,
        source_path: str,
        locator: str = "",
    ) -> tuple[ExplainabilityTrace, ...]:
        return tuple(
            trace
            for trace in snapshot.traces
            if (
                trace.link.canonical_reference.source_path == source_path
                and (
                    not locator
                    or trace.link.canonical_reference.locator == locator
                )
            )
        )

    def ascend(
        self,
        snapshot: ExplainabilitySnapshot,
        code_subject: str,
    ) -> tuple[ExplainabilityTrace, ...]:
        return tuple(
            trace
            for trace in snapshot.traces
            if trace.link.code_subject == code_subject
        )

    def preflight(
        self,
        snapshot: ExplainabilitySnapshot,
        code_subjects: Iterable[str],
    ) -> ChangePreflight:
        requested = tuple(sorted(set(code_subjects)))
        traces = tuple(
            trace
            for subject in requested
            for trace in self.ascend(snapshot, subject)
        )

        blockers: list[str] = []

        missing_subjects = tuple(
            subject
            for subject in requested
            if not self.ascend(snapshot, subject)
        )
        blockers.extend(
            f"unexplained behavior-defining element: {subject}"
            for subject in missing_subjects
        )

        if not snapshot.fresh:
            blockers.append("required source evidence is stale or unavailable")

        blockers.extend(
            f"unresolved canonical conflict: {item}"
            for item in snapshot.conflicts
        )

        for trace in traces:
            if "ownership" in trace.missing_fields:
                blockers.append(
                    "missing authority/invariant ownership: "
                    + trace.link.code_subject
                )

            tests = self._tests(trace)
            if "test_relationships" in trace.missing_fields:
                blockers.append(
                    "missing deterministic test relationship: "
                    + trace.link.code_subject
                )
            if not tests and not trace.link.evidence_refs:
                blockers.append(
                    "affected deterministic test/evidence boundary "
                    "cannot be identified: "
                    + trace.link.code_subject
                )

        refs = tuple(sorted({
            self._canonical_identity(trace.link)
            for trace in traces
        }))
        tests = tuple(sorted({
            target
            for trace in traces
            for target in self._tests(trace)
        }))
        evidence = tuple(sorted({
            item
            for trace in traces
            for item in trace.link.evidence_refs
        }))

        blockers = list(dict.fromkeys(blockers))

        return ChangePreflight(
            gate=(
                ExplainabilityGate.BLOCKED
                if blockers
                else ExplainabilityGate.READY
            ),
            affected_subjects=requested,
            canonical_references=refs,
            tests=tests,
            evidence_refs=evidence,
            blockers=tuple(blockers),
            snapshot_revision=snapshot.revision,
        )

    def drift_check(
        self,
        before: ExplainabilitySnapshot,
        after: ExplainabilitySnapshot,
        code_subjects: Iterable[str],
    ) -> DriftCheck:
        subjects = tuple(sorted(set(code_subjects)))
        blockers: list[str] = []

        for subject in subjects:
            old = self.ascend(before, subject)
            new = self.ascend(after, subject)

            if old and not new:
                blockers.append(f"trace orphaned after change: {subject}")

            if new and any(
                trace.classification is SemanticClassification.CONFLICT
                for trace in new
            ):
                blockers.append(f"trace conflict after change: {subject}")

        if not after.fresh:
            blockers.append("post-change derived evidence is stale")

        blockers.extend(
            f"post-change conflict: {item}"
            for item in after.conflicts
        )

        affected_orphans = tuple(
            item for item in after.orphans if item in subjects
        )
        blockers.extend(
            f"post-change orphan: {item}"
            for item in affected_orphans
        )

        blockers = list(dict.fromkeys(blockers))

        return DriftCheck(
            gate=(
                ExplainabilityGate.BLOCKED
                if blockers
                else ExplainabilityGate.READY
            ),
            before_revision=before.revision,
            after_revision=after.revision,
            stale=not after.fresh,
            conflicts=after.conflicts,
            orphans=affected_orphans,
            blockers=tuple(blockers),
        )

    def _trace(self, link: SemanticLink) -> ExplainabilityTrace:
        relation_kinds = (
            self.FILE_RELATION_KINDS
            if link.subject_kind is CodeIntelligenceSubjectKind.FILE
            else self.SYMBOL_RELATION_KINDS
        )
        observations = tuple(
            self.linker.inspect(link, kind)
            for kind in relation_kinds
        )

        missing = tuple(dict.fromkeys(
            field
            for observation in observations
            for field in observation.missing_fields
        ))

        conflicts: list[str] = []

        # Explicit conflict input only.  No semantic disagreement is guessed.
        if link.uncertainty.startswith("CONFLICT:"):
            conflicts.append(link.uncertainty)

        if conflicts:
            classification = SemanticClassification.CONFLICT
        elif any(
            item.status is CodeIntelligenceStatus.UNAVAILABLE
            for item in observations
        ):
            classification = SemanticClassification.PARTIAL
        elif missing:
            classification = SemanticClassification.PARTIAL
        elif all(
            item.classification is SemanticClassification.MAPPED
            for item in observations
        ):
            classification = SemanticClassification.MAPPED
        else:
            classification = SemanticClassification.PARTIAL

        return ExplainabilityTrace(
            link=link,
            observations=observations,
            classification=classification,
            missing_fields=missing,
            conflicts=tuple(conflicts),
        )

    @staticmethod
    def _tests(trace: ExplainabilityTrace) -> tuple[str, ...]:
        return tuple(sorted({
            relation.target
            for observation in trace.observations
            if observation.kind is CodeIntelligenceKind.TESTS
            for relation in observation.relations
        }))

    @staticmethod
    def _canonical_identity(link: SemanticLink) -> str:
        ref = link.canonical_reference
        return f"{ref.source_path}::{ref.locator}::{ref.claim_kind}"

    @classmethod
    def _link_key(cls, link: SemanticLink) -> tuple[str, ...]:
        ref = link.canonical_reference
        return (
            ref.source_path,
            ref.locator,
            ref.claim_kind,
            link.code_subject,
            link.subject_kind.value,
            link.provenance,
        )

    @classmethod
    def _repository_revision(
        cls,
        semantic_snapshot: ExplainabilitySnapshot,
        coverage: tuple[SemanticCoverageRecord, ...],
        source_revision: str,
    ) -> str:
        rows = [
            "semantic=" + semantic_snapshot.revision,
            "source=" + source_revision,
        ]

        rows.extend(
            "|".join((
                record.inventory_kind,
                record.code_subject,
                record.file,
                str(record.line),
                record.classification.value,
                ",".join(record.missing_fields),
            ))
            for record in coverage
        )

        return sha256(
            "\n".join(rows).encode("utf-8")
        ).hexdigest()

    @classmethod
    def _revision(
        cls,
        traces: tuple[ExplainabilityTrace, ...],
    ) -> str:
        rows: list[str] = []

        for trace in traces:
            link = trace.link
            rows.append("|".join((
                cls._canonical_identity(link),
                link.code_subject,
                link.subject_kind.value,
                link.provenance,
                *(
                    f"{name}={value}"
                    for name, value in sorted(
                        link.semantic_fields().items()
                    )
                ),
                "evidence=" + ",".join(sorted(link.evidence_refs)),
                "classification=" + trace.classification.value,
                "missing=" + ",".join(trace.missing_fields),
                "conflicts=" + ",".join(trace.conflicts),
                *(
                    "obs="
                    + observation.kind.value
                    + ":"
                    + observation.status.value
                    + ":"
                    + observation.index_revision
                    + ":"
                    + str(observation.fresh)
                    + ":"
                    + ",".join(
                        sorted(
                            f"{r.relation}:{r.target}:{r.file}:{r.line}"
                            for r in observation.relations
                        )
                    )
                    for observation in trace.observations
                ),
            )))

        return sha256(
            "\n".join(rows).encode("utf-8")
        ).hexdigest()
