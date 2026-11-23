"""Backend-neutral code-intelligence boundary for the Project World Model.

Generic repository indexing, parsing, graph construction, graph traversal,
and semantic search remain backend-owned.

Values exposed here are derived observations only. They do not establish
Foundation canonical, policy, or execution authority.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class CodeIntelligenceKind(str, Enum):
    REFERENCES = "REFERENCES"
    IMPACT = "IMPACT"
    TESTS = "TESTS"
    DEPENDENCIES = "DEPENDENCIES"
    CALLS = "CALLS"
    INVENTORY = "INVENTORY"
    SCOPED_VARIABLES = "SCOPED_VARIABLES"
    READS = "READS"
    WRITES = "WRITES"


class CodeIntelligenceStatus(str, Enum):
    OK = "OK"
    UNKNOWN = "UNKNOWN"
    UNAVAILABLE = "UNAVAILABLE"


class CodeIntelligenceSubjectKind(str, Enum):
    SYMBOL = "SYMBOL"
    FILE = "FILE"


@dataclass(frozen=True)
class CodeIntelligenceQuery:
    kind: CodeIntelligenceKind
    subject: str
    subject_kind: CodeIntelligenceSubjectKind


@dataclass(frozen=True)
class CodeIntelligenceRelation:
    """Small backend-neutral relationship observation.

    ``target`` preserves the backend identity when one exists.
    ``relation`` carries only the relationship semantics needed by consumers.
    Location is optional because not every relationship has a source line.
    """

    target: str
    relation: str
    file: str = ""
    line: int | None = None


@dataclass(frozen=True)
class CodeIntelligenceCompleteness:
    """Mechanical completeness evidence for bounded source analysis."""

    expected_files: int
    analyzed_files: int
    failed_files: tuple[str, ...] = ()
    unresolved_observations: int = 0
    fallback_files: tuple[str, ...] = ()
    unaccounted_files: tuple[str, ...] = ()

    @property
    def inventory_complete(self) -> bool:
        """True when every tracked file is indexed or explicitly fallback-inventoried."""
        return (
            self.expected_files == self.analyzed_files + len(self.fallback_files)
            and not self.unaccounted_files
            and self.unresolved_observations == 0
        )

    @property
    def complete(self) -> bool:
        return (
            self.expected_files == self.analyzed_files
            and not self.failed_files
            and self.unresolved_observations == 0
        )


@dataclass(frozen=True)
class CodeIntelligenceResult:
    kind: CodeIntelligenceKind
    subject: str
    status: CodeIntelligenceStatus
    relations: tuple[CodeIntelligenceRelation, ...]
    backend: str
    backend_version: str
    index_revision: str
    fresh: bool
    uncertainty: str = ""
    completeness: CodeIntelligenceCompleteness | None = None


class CodeIntelligencePort(Protocol):
    def inspect(self, query: CodeIntelligenceQuery) -> CodeIntelligenceResult: ...
