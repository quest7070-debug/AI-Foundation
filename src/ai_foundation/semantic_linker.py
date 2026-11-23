"""Foundation-specific derived links between canon and code intelligence.

This module creates navigation/context only.  It does not copy canonical
claims, grant authority, or create an independent specification/evidence
store.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path, PurePosixPath
import re

from .code_intelligence import (
    CodeIntelligenceCompleteness,
    CodeIntelligenceKind,
    CodeIntelligencePort,
    CodeIntelligenceQuery,
    CodeIntelligenceRelation,
    CodeIntelligenceStatus,
    CodeIntelligenceSubjectKind,
)


class SemanticClassification(str, Enum):
    MAPPED = "MAPPED"
    PARTIAL = "PARTIAL"
    UNMAPPED = "UNMAPPED"
    CONFLICT = "CONFLICT"
    DERIVED_ONLY = "DERIVED_ONLY"


REQUIRED_SEMANTIC_FIELDS = (
    "purpose",
    "ownership",
    "rationale",
    "failure_semantics",
    "side_effects",
    "change_impact",
)


@dataclass(frozen=True)
class CanonicalReference:
    source_path: str
    locator: str
    claim_kind: str


@dataclass(frozen=True)
class SemanticLink:
    canonical_reference: CanonicalReference
    code_subject: str
    subject_kind: CodeIntelligenceSubjectKind
    evidence_refs: tuple[str, ...] = ()
    provenance: str = ""
    uncertainty: str = ""

    # Explicitly grounded semantic facts only.  Empty values remain missing;
    # FoundationSemanticLinker never invents or infers them.
    purpose: str = ""
    ownership: str = ""
    rationale: str = ""
    failure_semantics: str = ""
    side_effects: str = ""
    change_impact: str = ""
    # Exact implementation source declared by Canon. Older explicit links may
    # omit it; Canon-native parser output always supplies it.
    code_source_path: str = ""

    def semantic_fields(self) -> dict[str, str]:
        return {
            "purpose": self.purpose.strip(),
            "ownership": self.ownership.strip(),
            "rationale": self.rationale.strip(),
            "failure_semantics": self.failure_semantics.strip(),
            "side_effects": self.side_effects.strip(),
            "change_impact": self.change_impact.strip(),
        }


@dataclass(frozen=True)
class SemanticLinkResult:
    link: SemanticLink
    kind: CodeIntelligenceKind
    status: CodeIntelligenceStatus
    classification: SemanticClassification = SemanticClassification.UNMAPPED
    missing_fields: tuple[str, ...] = ()
    relations: tuple[CodeIntelligenceRelation, ...] = ()
    backend: str = ""
    backend_version: str = ""
    index_revision: str = ""
    fresh: bool = False
    uncertainty: str = ""
    authoritative: bool = False


@dataclass(frozen=True)
class SemanticCoverageRecord:
    """One source-derived inventory observation in semantic coverage."""

    inventory_kind: str
    code_subject: str
    file: str
    line: int | None
    classification: SemanticClassification = SemanticClassification.UNMAPPED
    missing_fields: tuple[str, ...] = REQUIRED_SEMANTIC_FIELDS
    authoritative: bool = False


@dataclass(frozen=True)
class SemanticCoverageResult:
    """Repository-wide source population without semantic invention."""

    status: CodeIntelligenceStatus
    records: tuple[SemanticCoverageRecord, ...] = ()
    backend: str = ""
    backend_version: str = ""
    index_revision: str = ""
    fresh: bool = False
    completeness: CodeIntelligenceCompleteness | None = None
    uncertainty: str = ""
    authoritative: bool = False


FOUNDATION_SEMANTIC_KEYS = (
    "source", "subject", "subject_kind", "claim_kind", "purpose",
    "ownership", "rationale", "failure_semantics", "side_effects",
    "change_impact", "evidence",
)


class FoundationSemanticParseError(ValueError):
    """A Canon-native semantic declaration is malformed or ambiguous."""


def _strict_json_object(body: str) -> dict[str, object]:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise FoundationSemanticParseError(
                    f"duplicate foundation-semantic key: {key}"
                )
            result[key] = value
        return result
    try:
        value = json.loads(body, object_pairs_hook=pairs)
    except FoundationSemanticParseError:
        raise
    except (json.JSONDecodeError, TypeError) as exc:
        raise FoundationSemanticParseError(
            f"invalid foundation-semantic JSON: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise FoundationSemanticParseError(
            "foundation-semantic body must be one JSON object"
        )
    return value


def _valid_repo_source(source: str) -> bool:
    if not source or "\\" in source or source.startswith("/"):
        return False
    path = PurePosixPath(source)
    return str(path) == source and all(
        part not in ("", ".", "..") for part in path.parts
    )


def parse_foundation_semantic(
    canonical_text: str,
    canonical_path: str,
) -> tuple[SemanticLink, ...]:
    """Parse only explicit Canon-native foundation-semantic fenced blocks."""
    if not _valid_repo_source(canonical_path):
        raise FoundationSemanticParseError(
            "canonical_path must be normalized repository-relative POSIX path"
        )
    lines = canonical_text.splitlines()
    links = []
    identities = set()
    index = 0
    while index < len(lines):
        if lines[index] != "```foundation-semantic":
            index += 1
            continue
        opening_line = index + 1
        closing = index + 1
        while closing < len(lines) and lines[closing].strip() != "```":
            closing += 1
        if closing >= len(lines):
            raise FoundationSemanticParseError(
                f"unclosed foundation-semantic fence at {canonical_path}:{opening_line}"
            )
        data = _strict_json_object("\n".join(lines[index + 1:closing]))
        if set(data) != set(FOUNDATION_SEMANTIC_KEYS):
            missing = sorted(set(FOUNDATION_SEMANTIC_KEYS) - set(data))
            extra = sorted(set(data) - set(FOUNDATION_SEMANTIC_KEYS))
            raise FoundationSemanticParseError(
                f"foundation-semantic keys mismatch; missing={missing}; extra={extra}"
            )
        for key in FOUNDATION_SEMANTIC_KEYS[:-1]:
            if not isinstance(data[key], str) or not data[key].strip():
                raise FoundationSemanticParseError(
                    f"foundation-semantic {key} must be a non-empty string"
                )
        evidence = data["evidence"]
        if (
            not isinstance(evidence, list)
            or any(not isinstance(item, str) or not item.strip() for item in evidence)
            or len(evidence) != len(set(evidence))
        ):
            raise FoundationSemanticParseError(
                "foundation-semantic evidence must be unique non-empty strings"
            )
        source = data["source"]
        if not _valid_repo_source(source):
            raise FoundationSemanticParseError(
                "foundation-semantic source must be normalized repository-relative POSIX"
            )
        try:
            subject_kind = CodeIntelligenceSubjectKind(data["subject_kind"])
        except ValueError as exc:
            raise FoundationSemanticParseError(
                "foundation-semantic subject_kind is invalid"
            ) from exc
        subject = data["subject"]
        if subject_kind is CodeIntelligenceSubjectKind.FILE:
            identity_matches = subject == source
        else:
            identity_matches = subject.startswith(source + "::")
        if not identity_matches:
            raise FoundationSemanticParseError(
                "foundation-semantic source and subject identities do not match"
            )
        identity = (source, subject, subject_kind.value)
        if identity in identities:
            raise FoundationSemanticParseError(
                f"duplicate foundation-semantic identity: {identity}"
            )
        identities.add(identity)
        locator = f"{canonical_path}:{opening_line}"
        links.append(SemanticLink(
            canonical_reference=CanonicalReference(
                source_path=canonical_path,
                locator=locator,
                claim_kind=data["claim_kind"],
            ),
            code_subject=data["subject"],
            subject_kind=subject_kind,
            evidence_refs=tuple(evidence),
            provenance=locator,
            purpose=data["purpose"],
            ownership=data["ownership"],
            rationale=data["rationale"],
            failure_semantics=data["failure_semantics"],
            side_effects=data["side_effects"],
            change_impact=data["change_impact"],
            code_source_path=source,
        ))
        index = closing + 1
    return tuple(links)


def parse_foundation_semantic_repository(
    root: Path,
    *,
    docs_root: str = "docs",
) -> tuple[SemanticLink, ...]:
    """Rebuild explicit semantic links from canonical Markdown only."""
    root = Path(root)
    docs = root / docs_root
    if not docs.is_dir():
        raise FoundationSemanticParseError(
            f"canonical docs root is missing or unreadable: {docs_root}"
        )

    links = []
    identities = set()
    for path in sorted(docs.rglob("*.md")):
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_text()
        except (OSError, UnicodeError) as exc:
            raise FoundationSemanticParseError(
                f"unreadable canonical source: {rel}"
            ) from exc
        for link in parse_foundation_semantic(text, rel):
            identity = (
                link.code_source_path,
                link.code_subject,
                link.subject_kind.value,
            )
            if identity in identities:
                raise FoundationSemanticParseError(
                    f"duplicate foundation-semantic identity across Canon: {identity}"
                )
            identities.add(identity)
            links.append(link)

    return tuple(sorted(
        links,
        key=lambda link: (
            link.canonical_reference.source_path,
            link.canonical_reference.locator,
            link.code_source_path,
            link.code_subject,
        ),
    ))


class FoundationSemanticLinker:
    """Read-only semantic composition over an existing code-intelligence port."""

    def __init__(self, code_intelligence: CodeIntelligencePort) -> None:
        self.code_intelligence = code_intelligence

    def repository_coverage(self) -> SemanticCoverageResult:
        """Expose every deterministic inventory observation without omission.

        This is a completeness surface, not a semantic inference engine.
        Inventory observations start UNMAPPED until separately grounded
        semantic evidence establishes another classification.
        """

        result = self.code_intelligence.inspect(
            CodeIntelligenceQuery(
                CodeIntelligenceKind.INVENTORY,
                ".",
                CodeIntelligenceSubjectKind.FILE,
            )
        )

        completeness = result.completeness
        records = tuple(
            SemanticCoverageRecord(
                inventory_kind=relation.relation,
                code_subject=relation.target,
                file=relation.file,
                line=relation.line,
            )
            for relation in result.relations
        )
        problems = []

        if result.status is not CodeIntelligenceStatus.OK:
            problems.append(
                f"inventory status is {result.status.value}"
            )

        if not result.fresh:
            problems.append("inventory evidence is stale")

        if completeness is None:
            problems.append("inventory completeness metadata is missing")
        elif not completeness.complete:
            problems.append("inventory completeness is incomplete")

        if problems:
            status = result.status
            if status is CodeIntelligenceStatus.OK:
                status = CodeIntelligenceStatus.UNKNOWN

            return SemanticCoverageResult(
                status=status,
                records=records,
                backend=result.backend,
                backend_version=result.backend_version,
                index_revision=result.index_revision,
                fresh=result.fresh,
                completeness=completeness,
                uncertainty=self._join_uncertainty(
                    result.uncertainty,
                    "; ".join(problems),
                ),
            )

        return SemanticCoverageResult(
            status=CodeIntelligenceStatus.OK,
            records=records,
            backend=result.backend,
            backend_version=result.backend_version,
            index_revision=result.index_revision,
            fresh=True,
            completeness=completeness,
            uncertainty=(
                "repository coverage is source-derived only; UNMAPPED "
                "means no grounded semantic explanation has been supplied"
            ),
        )

    def inspect(
        self,
        link: SemanticLink,
        kind: CodeIntelligenceKind,
    ) -> SemanticLinkResult:
        invalid = self._validation_error(link)

        if invalid:
            return SemanticLinkResult(
                link=link,
                kind=kind,
                status=CodeIntelligenceStatus.UNAVAILABLE,
                classification=SemanticClassification.UNMAPPED,
                missing_fields=self._missing_fields(link),
                uncertainty=invalid,
            )

        result = self.code_intelligence.inspect(
            CodeIntelligenceQuery(
                kind,
                link.code_subject,
                link.subject_kind,
            )
        )

        uncertainty = self._join_uncertainty(
            link.uncertainty,
            result.uncertainty,
        )

        missing_fields = [
            name
            for name, value in link.semantic_fields().items()
            if not value
        ]
        if result.status is not CodeIntelligenceStatus.OK:
            missing_fields.append("source_relationships")

        classification = (
            SemanticClassification.MAPPED
            if (
                result.status is CodeIntelligenceStatus.OK
                and result.fresh
                and not missing_fields
                and not uncertainty
            )
            else SemanticClassification.PARTIAL
        )

        return SemanticLinkResult(
            link=link,
            kind=kind,
            status=result.status,
            classification=classification,
            missing_fields=tuple(missing_fields),
            relations=result.relations,
            backend=result.backend,
            backend_version=result.backend_version,
            index_revision=result.index_revision,
            fresh=result.fresh,
            uncertainty=uncertainty,
        )

    @staticmethod
    def _missing_fields(link: SemanticLink) -> tuple[str, ...]:
        ref = link.canonical_reference
        missing = []

        if not ref.source_path.strip():
            missing.append("canonical_reference.source_path")
        if not ref.locator.strip():
            missing.append("canonical_reference.locator")
        if not ref.claim_kind.strip():
            missing.append("canonical_reference.claim_kind")
        if not link.code_subject.strip():
            missing.append("code_subject")
        if not link.provenance.strip():
            missing.append("provenance")

        missing.extend(
            name
            for name, value in link.semantic_fields().items()
            if not value
        )
        return tuple(missing)

    @staticmethod
    def _validation_error(link: SemanticLink) -> str:
        ref = link.canonical_reference

        if not ref.source_path.strip():
            return "canonical source path is missing"

        if not ref.locator.strip():
            return "canonical locator is missing"

        if not ref.claim_kind.strip():
            return "canonical claim kind is missing"

        if not link.code_subject.strip():
            return "code subject is missing"

        if not link.provenance.strip():
            return "semantic link provenance is missing"

        return ""

    @staticmethod
    def _join_uncertainty(*values: str) -> str:
        return "; ".join(
            dict.fromkeys(
                value.strip()
                for value in values
                if value and value.strip()
            )
        )
