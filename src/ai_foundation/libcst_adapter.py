"""Narrow LibCST sidecar for Python scoped-name relationships.

LibCST owns parsing, Python scope analysis, assignment/reference resolution,
and source positions.

Foundation only converts those derived observations into the existing
CodeIntelligencePort contract.

This adapter deliberately does not implement:
- a parser;
- a generic graph;
- type inference;
- arbitrary object-attribute identity;
- canonical or execution authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import libcst as cst
from libcst.metadata import (
    Assignment,
    ClassScope,
    ComprehensionScope,
    FunctionScope,
    GlobalScope,
    MetadataWrapper,
    PositionProvider,
    ScopeProvider,
)

from .code_intelligence import (
    CodeIntelligenceCompleteness,
    CodeIntelligenceKind,
    CodeIntelligenceQuery,
    CodeIntelligenceRelation,
    CodeIntelligenceResult,
    CodeIntelligenceStatus,
    CodeIntelligenceSubjectKind,
)


_SUPPORTED_VERSION = "1.9.0"

_SUPPORTED_KINDS = frozenset(
    {
        CodeIntelligenceKind.INVENTORY,
        CodeIntelligenceKind.SCOPED_VARIABLES,
        CodeIntelligenceKind.READS,
        CodeIntelligenceKind.WRITES,
    }
)


@dataclass(frozen=True)
class _SourceSnapshot:
    files: tuple[tuple[Path, str, bytes], ...]
    revision: str


@dataclass
class LibCSTCodeIntelligence:
    """Direct source-derived scoped-name observations for Python."""

    SUPPORTED_KINDS = _SUPPORTED_KINDS

    root: Path
    source_root: Path = Path("src/ai_foundation")

    def inspect(
        self,
        query: CodeIntelligenceQuery,
    ) -> CodeIntelligenceResult:
        backend_version = self._backend_version()

        if backend_version is None:
            return self._result(
                query,
                status=CodeIntelligenceStatus.UNAVAILABLE,
                uncertainty=(
                    "LibCST 1.9.0 is unavailable or version-mismatched"
                ),
            )

        if query.kind not in _SUPPORTED_KINDS:
            return self._result(
                query,
                status=CodeIntelligenceStatus.UNAVAILABLE,
                backend_version=backend_version,
                uncertainty=(
                    f"{query.kind.value} is not implemented by "
                    "the LibCST sidecar"
                ),
            )

        if query.subject_kind is not CodeIntelligenceSubjectKind.FILE:
            return self._result(
                query,
                status=CodeIntelligenceStatus.UNAVAILABLE,
                backend_version=backend_version,
                uncertainty=(
                    f"{query.kind.value} requires an explicit FILE subject"
                ),
            )

        try:
            paths = self._resolve_paths(query.subject)
            before = self._snapshot(paths)
        except (OSError, UnicodeError, ValueError) as exc:
            return self._result(
                query,
                status=CodeIntelligenceStatus.UNAVAILABLE,
                backend_version=backend_version,
                uncertainty=f"unable to read source snapshot: {exc}",
            )

        completeness = None

        try:
            if query.kind is CodeIntelligenceKind.INVENTORY:
                (
                    relations,
                    missing_positions,
                    completeness,
                ) = self._extract_inventory(before)
            else:
                relations, missing_positions = self._extract(
                    query.kind,
                    before,
                )
        except Exception as exc:
            return self._result(
                query,
                status=CodeIntelligenceStatus.UNAVAILABLE,
                backend_version=backend_version,
                index_revision=before.revision,
                uncertainty=(
                    "LibCST source analysis failed: "
                    f"{type(exc).__name__}: {exc}"
                ),
            )

        try:
            after = self._snapshot(paths)
        except OSError as exc:
            return self._result(
                query,
                status=CodeIntelligenceStatus.UNKNOWN,
                backend_version=backend_version,
                index_revision=before.revision,
                relations=relations,
                fresh=False,
                uncertainty=(
                    "source changed or became unreadable after analysis: "
                    f"{exc}"
                ),
            )

        if after.revision != before.revision:
            return self._result(
                query,
                status=CodeIntelligenceStatus.UNKNOWN,
                backend_version=backend_version,
                index_revision=before.revision,
                relations=relations,
                fresh=False,
                uncertainty="source changed during LibCST analysis",
            )

        if completeness is not None and not completeness.complete:
            return self._result(
                query,
                status=CodeIntelligenceStatus.UNKNOWN,
                backend_version=backend_version,
                index_revision=before.revision,
                relations=relations,
                fresh=True,
                uncertainty=(
                    "repository inventory is incomplete: "
                    f"{completeness.analyzed_files}/"
                    f"{completeness.expected_files} files analyzed; "
                    f"{len(completeness.failed_files)} failed; "
                    f"{completeness.unresolved_observations} "
                    "observations unresolved"
                ),
                completeness=completeness,
            )

        if completeness is None:
            completeness = CodeIntelligenceCompleteness(
                expected_files=len(before.files),
                analyzed_files=len(before.files),
                unresolved_observations=missing_positions,
            )

        if missing_positions:
            return self._result(
                query,
                status=CodeIntelligenceStatus.UNKNOWN,
                backend_version=backend_version,
                index_revision=before.revision,
                relations=relations,
                fresh=True,
                uncertainty=(
                    f"{missing_positions} scoped observations "
                    "had no source position"
                ),
                completeness=completeness,
            )

        scope_uncertainty = ""
        if query.kind is CodeIntelligenceKind.READS:
            scope_uncertainty = (
                "READS reports scoped Name/Param identity references only; "
                "attribute/subscript target semantics, dynamic access, and "
                "non-scoped object identity remain UNKNOWN"
            )
        elif query.kind is CodeIntelligenceKind.WRITES:
            scope_uncertainty = (
                "WRITES reports scoped Name/Param assignment identities only; "
                "attribute/subscript mutation targets, dynamic mutation, and "
                "non-scoped object identity remain UNKNOWN"
            )

        return self._result(
            query,
            status=CodeIntelligenceStatus.OK,
            backend_version=backend_version,
            index_revision=before.revision,
            relations=relations,
            fresh=True,
            uncertainty=scope_uncertainty,
            completeness=completeness,
        )

    def _backend_version(self) -> str | None:
        try:
            observed = version("libcst")
        except PackageNotFoundError:
            return None

        if observed != _SUPPORTED_VERSION:
            return None

        return observed

    def _resolve_paths(self, subject: str) -> tuple[Path, ...]:
        root = self.root.resolve()
        source_root = (root / self.source_root).resolve()

        if not source_root.is_relative_to(root):
            raise ValueError("source_root escapes repository root")

        if subject == ".":
            paths = tuple(sorted(path for pattern in ("*.py", "*.pyi") for path in source_root.rglob(pattern)))

            return paths

        path = (root / subject).resolve()

        if not path.is_relative_to(source_root):
            raise ValueError("subject escapes configured Python source root")

        if path.suffix not in {".py", ".pyi"}:
            raise ValueError("subject is not a Python source file")

        if not path.is_file():
            raise ValueError("subject Python source file does not exist")

        return (path,)

    def _snapshot(
        self,
        paths: tuple[Path, ...],
    ) -> _SourceSnapshot:
        root = self.root.resolve()
        records: list[tuple[Path, str, bytes]] = []
        digest = sha256()

        for path in paths:
            data = path.read_bytes()
            relative = path.relative_to(root).as_posix()

            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(data)
            digest.update(b"\0")

            records.append((path, relative, data))

        return _SourceSnapshot(
            files=tuple(records),
            revision=digest.hexdigest(),
        )

    def _extract(
        self,
        kind: CodeIntelligenceKind,
        snapshot: _SourceSnapshot,
    ) -> tuple[tuple[CodeIntelligenceRelation, ...], int]:
        observations: set[CodeIntelligenceRelation] = set()
        missing_positions = 0

        for _path, relative, data in snapshot.files:
            module = cst.parse_module(data.decode("utf-8"))

            wrapper = MetadataWrapper(
                module,
                unsafe_skip_copy=True,
            )

            resolved = wrapper.resolve_many(
                {
                    ScopeProvider,
                    PositionProvider,
                }
            )

            scope_map = resolved[ScopeProvider]
            positions = resolved[PositionProvider]

            scopes = {
                id(scope): scope
                for scope in scope_map.values()
                if scope is not None
            }

            seen_assignments: set[int] = set()

            for scope in scopes.values():
                for assignment in scope.assignments:
                    if not isinstance(assignment, Assignment):
                        continue

                    identity = id(assignment)

                    if identity in seen_assignments:
                        continue

                    seen_assignments.add(identity)

                    # ScopeProvider also models imports, functions and
                    # classes as assignments. This sidecar is intentionally
                    # narrower: scoped variable/parameter identities only.
                    if not isinstance(
                        assignment.node,
                        (cst.Name, cst.Param),
                    ):
                        continue

                    position = positions.get(assignment.node)

                    if position is None:
                        missing_positions += 1
                        continue

                    scope_name = type(assignment.scope).__name__

                    assignment_id = (
                        f"{relative}::{scope_name}::"
                        f"{assignment.name}@"
                        f"{position.start.line}:"
                        f"{position.start.column}"
                    )

                    if kind is CodeIntelligenceKind.SCOPED_VARIABLES:
                        observations.add(
                            CodeIntelligenceRelation(
                                target=assignment_id,
                                relation="DECLARES",
                                file=relative,
                                line=position.start.line,
                            )
                        )
                        continue

                    if kind is CodeIntelligenceKind.WRITES:
                        observations.add(
                            CodeIntelligenceRelation(
                                target=assignment_id,
                                relation="WRITE",
                                file=relative,
                                line=position.start.line,
                            )
                        )
                        continue

                    for access in assignment.references:
                        access_position = positions.get(access.node)

                        if access_position is None:
                            missing_positions += 1
                            continue

                        relation = (
                            "TYPE_READ"
                            if access.is_annotation or access.is_type_hint
                            else "READ"
                        )

                        observations.add(
                            CodeIntelligenceRelation(
                                target=assignment_id,
                                relation=relation,
                                file=relative,
                                line=access_position.start.line,
                            )
                        )

        ordered = tuple(
            sorted(
                observations,
                key=lambda item: (
                    item.file,
                    -1 if item.line is None else item.line,
                    item.relation,
                    item.target,
                ),
            )
        )

        return ordered, missing_positions


    def _extract_inventory(
        self,
        snapshot: _SourceSnapshot,
    ) -> tuple[
        tuple[CodeIntelligenceRelation, ...],
        int,
        CodeIntelligenceCompleteness,
    ]:
        """Build a deterministic source inventory from LibCST metadata.

        Classification semantics are source-derived:

        - every successfully snapshotted Python file is a MODULE;
        - every ClassDef is a CLASS;
        - Protocol/ABC/ABCMeta classes additionally carry INTERFACE;
        - FunctionDef in ClassScope is METHOD;
        - every other FunctionDef is FUNCTION, including nested functions;
        - uppercase GlobalScope/ClassScope Name assignments are constants;
        - other GlobalScope names are module variables;
        - other ClassScope names are class state;
        - FunctionScope/ComprehensionScope Name assignments are scoped
          variables, deduplicated by logical scope + name.

        Parameters are intentionally not a separate DI02 inventory category.
        """

        observations: set[CodeIntelligenceRelation] = set()
        missing_positions = 0
        analyzed_files = 0
        failed_files: list[str] = []

        for _path, relative, data in snapshot.files:
            observations.add(
                CodeIntelligenceRelation(
                    target=relative,
                    relation="MODULE",
                    file=relative,
                    line=1,
                )
            )

            try:
                module = cst.parse_module(data.decode("utf-8"))

                wrapper = MetadataWrapper(
                    module,
                    unsafe_skip_copy=True,
                )

                resolved = wrapper.resolve_many(
                    {
                        ScopeProvider,
                        PositionProvider,
                    }
                )

                scope_map = resolved[ScopeProvider]
                positions = resolved[PositionProvider]

            except Exception as exc:
                failed_files.append(
                    f"{relative}: {type(exc).__name__}: {exc}"
                )
                continue

            analyzed_files += 1

            scopes = {
                id(scope): scope
                for scope in scope_map.values()
                if scope is not None
            }

            seen_assignments: set[int] = set()

            # Logical variable inventory is distinct by source scope + name.
            # Object identity is used only inside this extraction pass.
            # The emitted stable identity is the earliest source position.
            logical_variables: dict[
                tuple[int, str, str],
                tuple[int, int, str],
            ] = {}

            for scope in scopes.values():
                for assignment in scope.assignments:
                    if not isinstance(assignment, Assignment):
                        continue

                    identity = id(assignment)

                    if identity in seen_assignments:
                        continue

                    seen_assignments.add(identity)

                    node = assignment.node

                    if isinstance(node, cst.ClassDef):
                        position = positions.get(node)

                        if position is None:
                            missing_positions += 1
                            continue

                        target = (
                            f"{relative}::CLASS::{assignment.name}@"
                            f"{position.start.line}:"
                            f"{position.start.column}"
                        )

                        observations.add(
                            CodeIntelligenceRelation(
                                target=target,
                                relation="CLASS",
                                file=relative,
                                line=position.start.line,
                            )
                        )

                        if self._is_interface(module, node):
                            observations.add(
                                CodeIntelligenceRelation(
                                    target=target,
                                    relation="INTERFACE",
                                    file=relative,
                                    line=position.start.line,
                                )
                            )

                        continue

                    if isinstance(node, cst.FunctionDef):
                        position = positions.get(node)

                        if position is None:
                            missing_positions += 1
                            continue

                        relation = (
                            "METHOD"
                            if isinstance(scope, ClassScope)
                            else "FUNCTION"
                        )

                        target = (
                            f"{relative}::{relation}::{assignment.name}@"
                            f"{position.start.line}:"
                            f"{position.start.column}"
                        )

                        observations.add(
                            CodeIntelligenceRelation(
                                target=target,
                                relation=relation,
                                file=relative,
                                line=position.start.line,
                            )
                        )

                        continue

                    # Imports and parameters are not DI02 variable elements.
                    if not isinstance(node, cst.Name):
                        continue

                    position = positions.get(node)

                    if position is None:
                        missing_positions += 1
                        continue

                    if isinstance(scope, GlobalScope):
                        relation = (
                            "MODULE_CONSTANT"
                            if assignment.name.isupper()
                            else "MODULE_VARIABLE"
                        )

                    elif isinstance(scope, ClassScope):
                        relation = (
                            "CLASS_CONSTANT"
                            if assignment.name.isupper()
                            else "CLASS_STATE"
                        )

                    elif isinstance(
                        scope,
                        (
                            FunctionScope,
                            ComprehensionScope,
                        ),
                    ):
                        relation = "SCOPED_VARIABLE"

                    else:
                        # An unknown future LibCST scope must not silently
                        # disappear from completeness accounting.
                        missing_positions += 1
                        continue

                    if relation == "SCOPED_VARIABLE":
                        key = (
                            id(scope),
                            assignment.name,
                            relation,
                        )

                        candidate = (
                            position.start.line,
                            position.start.column,
                            type(scope).__name__,
                        )

                        previous = logical_variables.get(key)

                        if previous is None or candidate[:2] < previous[:2]:
                            logical_variables[key] = candidate

                        continue

                    target = (
                        f"{relative}::{type(scope).__name__}::"
                        f"{assignment.name}@"
                        f"{position.start.line}:"
                        f"{position.start.column}"
                    )

                    observations.add(
                        CodeIntelligenceRelation(
                            target=target,
                            relation=relation,
                            file=relative,
                            line=position.start.line,
                        )
                    )

            for (
                _scope_id,
                name,
                relation,
            ), (
                line,
                column,
                scope_name,
            ) in logical_variables.items():
                observations.add(
                    CodeIntelligenceRelation(
                        target=(
                            f"{relative}::{scope_name}::{name}@"
                            f"{line}:{column}"
                        ),
                        relation=relation,
                        file=relative,
                        line=line,
                    )
                )

        ordered = tuple(
            sorted(
                observations,
                key=lambda item: (
                    item.file,
                    -1 if item.line is None else item.line,
                    item.relation,
                    item.target,
                ),
            )
        )

        completeness = CodeIntelligenceCompleteness(
            expected_files=len(snapshot.files),
            analyzed_files=analyzed_files,
            failed_files=tuple(sorted(failed_files)),
            unresolved_observations=missing_positions,
        )

        return ordered, missing_positions, completeness

    @staticmethod
    def _is_interface(
        module: cst.Module,
        node: cst.ClassDef,
    ) -> bool:
        base_names = {
            module.code_for_node(base.value).rsplit(".", 1)[-1]
            for base in node.bases
        }

        if {"Protocol", "ABC"} & base_names:
            return True

        for keyword in node.keywords:
            if (
                keyword.keyword is not None
                and keyword.keyword.value == "metaclass"
            ):
                metaclass = (
                    module.code_for_node(keyword.value)
                    .rsplit(".", 1)[-1]
                )

                if metaclass == "ABCMeta":
                    return True

        return False

    @staticmethod
    def _result(
        query: CodeIntelligenceQuery,
        *,
        status: CodeIntelligenceStatus,
        backend_version: str = "",
        index_revision: str = "",
        relations: tuple[CodeIntelligenceRelation, ...] = (),
        fresh: bool = False,
        uncertainty: str = "",
        completeness: CodeIntelligenceCompleteness | None = None,
    ) -> CodeIntelligenceResult:
        return CodeIntelligenceResult(
            kind=query.kind,
            subject=query.subject,
            status=status,
            relations=relations,
            backend="libcst",
            backend_version=backend_version,
            index_revision=index_revision,
            fresh=fresh,
            uncertainty=uncertainty,
            completeness=completeness,
        )
