"""Thin, replaceable Infigraph adapter for code-intelligence observations.

The adapter intentionally does not implement repository indexing, graph
construction, graph traversal, semantic search, or Foundation authority.

Repository-wide multi-language inventory plus source-derived references,
impact, tests, dependencies and calls.

Existing indexes are treated as freshness-unverified. A separate explicit
refresh lifecycle must establish freshness before this adapter may report
``fresh=True``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import hashlib
import os
import re
import subprocess

from .configuration_inventory import ConfigurationInventory
from .code_intelligence import (
    CodeIntelligenceCompleteness,
    CodeIntelligenceKind,
    CodeIntelligenceQuery,
    CodeIntelligenceRelation,
    CodeIntelligenceResult,
    CodeIntelligenceStatus,
    CodeIntelligenceSubjectKind,
)


_SUPPORTED_VERSION = "3.2.16"
_INVENTORY_FILES_QUERY = (
    "MATCH (f:File) RETURN f.path,f.language,f.symbol_count"
)
_INVENTORY_SYMBOLS_QUERY = (
    "MATCH (s:Symbol) RETURN s.id,s.kind,s.file,s.start_line"
)
_CONFIG_EXTENSIONS = frozenset({
    ".json", ".jsonc", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".conf", ".xml", ".plist", ".properties", ".env", ".xcconfig",
    ".pbxproj", ".entitlements", ".service", ".desktop", ".gradle",
    ".lock", ".proto", ".sql", ".tf", ".hcl", ".ipynb", ".mod", ".sum",
})
_ARTIFACT_EXTENSIONS = frozenset({
    ".dylib", ".so", ".dll", ".wasm", ".jar", ".node", ".a", ".o",
    ".class", ".pyc", ".pyd", ".exe", ".pkg", ".mobileprovision",
    ".bin", ".pem", ".crt", ".key", ".p12", ".pfx", ".swiftmodule",
    ".swiftdoc", ".metallib",
})
_NON_SOURCE_EXTENSIONS = frozenset({
    ".md", ".mdx", ".rst", ".txt", ".pdf", ".docx", ".png", ".jpg",
    ".jpeg", ".gif", ".svg", ".webp", ".mp3", ".wav", ".mp4", ".mov",
    ".zip", ".gz", ".tgz", ".tar", ".woff", ".woff2", ".ttf", ".otf",
    ".ico", ".icns", ".heic", ".avif", ".webm", ".m4a", ".aac",
    ".pptx", ".xlsx", ".odt", ".ods", ".epub",
})
_CONFIG_FILENAMES = frozenset({
    ".env", ".env.example", "dockerfile", "makefile", "cmakelists.txt",
    "requirements.txt", "requirements-dev.txt", "constraints.txt",
    "pipfile", "pipfile.lock", "gemfile", "gemfile.lock",
    "go.mod", "go.sum", "cargo.toml", "cargo.lock", "pyproject.toml",
    "uv.lock", "package.json", "package-lock.json", "pnpm-lock.yaml",
    "yarn.lock", "composer.json", "composer.lock", "pom.xml",
    "build.gradle", "gradle.properties", "podfile", "podfile.lock",
    ".gitignore", ".gitattributes", ".gitmodules", ".editorconfig",
    ".dockerignore", ".npmrc", ".nvmrc", ".python-version",
    ".ruby-version", ".node-version", ".tool-versions", "codeowners",
    "procfile", "makefile", "dockerfile", "cmakelists.txt",
})
_NON_SOURCE_FILENAMES = frozenset({
    "readme", "license", "licence", "notice", "copying", "authors",
    "contributors", "contributing", "security", "support", "funding",
    "patents", "third_party_notices", "acknowledgements",
    "code_of_conduct", "changelog",
})

_REFERENCE_LINE = re.compile(
    r"^\s{2}(?P<file>.+):(?P<line>[0-9]+)"
    r"\s+in\s+(?P<context>.+?)\s*$"
)


@dataclass(frozen=True)
class _BackendState:
    version: str
    index_revision: str = ""


class InfigraphCodeIntelligence:
    SUPPORTED_KINDS = frozenset(
        {
            CodeIntelligenceKind.REFERENCES,
            CodeIntelligenceKind.IMPACT,
            CodeIntelligenceKind.TESTS,
            CodeIntelligenceKind.DEPENDENCIES,
            CodeIntelligenceKind.CALLS,
            CodeIntelligenceKind.INVENTORY,
        }
    )

    def __init__(
        self,
        *,
        executable: Path,
        root: Path,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        timeout_seconds: float = 10.0,
        source_identity: Callable[[], str] | None = None,
        index_receipt: Path | None = None,
        source_files: Callable[[], tuple[str, ...]] | None = None,
    ) -> None:
        self.executable = Path(executable)
        self.root = Path(root)
        self.runner = runner
        self.timeout_seconds = timeout_seconds
        self.source_identity = source_identity or self._git_source_identity
        self.source_files = source_files or self._git_source_files
        self._refresh_revision = ""
        self._receipt_store = None
        if index_receipt is not None:
            from .infigraph_receipt import InfigraphIndexReceipt
            self._receipt_store = InfigraphIndexReceipt(root=self.root,
                executable=self.executable, receipt=index_receipt)

    def refresh(self) -> CodeIntelligenceResult:
        if self._receipt_store is None:
            return self._refresh()
        try:
            with self._receipt_store.refresh_lock():
                executable = self._receipt_store.executable_identity()
                self._receipt_store.invalidate()
                result = self._refresh()
                if result.fresh and (self.source_identity() != result.index_revision
                        or self._receipt_store.executable_identity() != executable):
                    self._receipt_store.invalidate()
                    raise ValueError('source or backend changed during receipt commit')
                return result
        except (OSError, ValueError, RuntimeError) as exc:
            self._refresh_revision = ""
            return self._result(CodeIntelligenceQuery(CodeIntelligenceKind.DEPENDENCIES,
                ".", CodeIntelligenceSubjectKind.FILE),
                status=CodeIntelligenceStatus.UNAVAILABLE,
                uncertainty=f"durable index receipt unavailable: {exc}")

    def _refresh(self) -> CodeIntelligenceResult:
        query = CodeIntelligenceQuery(
            CodeIntelligenceKind.DEPENDENCIES,
            ".",
            CodeIntelligenceSubjectKind.FILE,
        )

        backend = self._backend_state(query)
        if isinstance(backend, CodeIntelligenceResult):
            self._refresh_revision = ""
            return backend

        try:
            before = self.source_identity()
        except Exception as exc:
            self._refresh_revision = ""
            return self._result(
                query,
                status=CodeIntelligenceStatus.UNAVAILABLE,
                backend_version=backend.version,
                uncertainty=f"unable to establish source identity before refresh: {exc}",
            )

        process = self._run("index", "--full", "--no-embed")
        if isinstance(process, str):
            self._refresh_revision = ""
            return self._result(
                query,
                status=CodeIntelligenceStatus.UNAVAILABLE,
                backend_version=backend.version,
                uncertainty=f"explicit refresh failed: {process}",
            )

        if process.returncode != 0:
            self._refresh_revision = ""
            return self._result(
                query,
                status=CodeIntelligenceStatus.UNAVAILABLE,
                backend_version=backend.version,
                uncertainty=(
                    "explicit refresh failed: "
                    f"{self._process_error(process)}"
                ),
            )

        try:
            after = self.source_identity()
        except Exception as exc:
            self._refresh_revision = ""
            return self._result(
                query,
                status=CodeIntelligenceStatus.UNAVAILABLE,
                backend_version=backend.version,
                uncertainty=f"unable to establish source identity after refresh: {exc}",
            )

        if before != after:
            self._refresh_revision = ""
            return self._result(
                query,
                status=CodeIntelligenceStatus.UNAVAILABLE,
                backend_version=backend.version,
                uncertainty="source identity changed during explicit refresh",
            )

        if self._receipt_store is not None:
            self._receipt_store.commit(after, backend.version)
        self._refresh_revision = after
        return self._result(
            query,
            status=CodeIntelligenceStatus.OK,
            backend_version=backend.version,
            index_revision=after,
            fresh=True,
        )

    def inspect(
        self,
        query: CodeIntelligenceQuery,
    ) -> CodeIntelligenceResult:
        if self._receipt_store is None:
            return self._inspect_unlocked(query)
        try:
            with self._receipt_store.read_lock():
                return self._inspect_unlocked(query)
        except BlockingIOError:
            return self._result(
                query,
                status=CodeIntelligenceStatus.UNKNOWN,
                uncertainty="index refresh is in progress; inventory read was not mixed across generations",
            )
        except (OSError, ValueError, RuntimeError) as exc:
            return self._result(
                query,
                status=CodeIntelligenceStatus.UNKNOWN,
                uncertainty=f"consistent index read lock unavailable: {type(exc).__name__}",
            )

    def _inspect_unlocked(
        self,
        query: CodeIntelligenceQuery,
    ) -> CodeIntelligenceResult:
        if query.kind is CodeIntelligenceKind.INVENTORY:
            return self._inspect_inventory(query)

        if query.kind in {
            CodeIntelligenceKind.REFERENCES,
            CodeIntelligenceKind.IMPACT,
            CodeIntelligenceKind.TESTS,
            CodeIntelligenceKind.CALLS,
        } and query.subject_kind is not CodeIntelligenceSubjectKind.SYMBOL:
            return self._result(
                query,
                status=CodeIntelligenceStatus.UNAVAILABLE,
                uncertainty=(
                    f"{query.kind.value} requires an explicit SYMBOL subject"
                ),
            )

        if (
            query.kind is CodeIntelligenceKind.DEPENDENCIES
            and query.subject_kind is not CodeIntelligenceSubjectKind.FILE
        ):
            return self._result(
                query,
                status=CodeIntelligenceStatus.UNAVAILABLE,
                uncertainty=(
                    "DEPENDENCIES requires an explicit FILE subject"
                ),
            )

        if query.kind not in self.SUPPORTED_KINDS:
            return self._result(
                query,
                status=CodeIntelligenceStatus.UNAVAILABLE,
                uncertainty=(
                    f"{query.kind.value} is not implemented by "
                    "this adapter slice"
                ),
            )

        backend = self._backend_state(query)
        if isinstance(backend, CodeIntelligenceResult):
            return backend

        if query.kind is CodeIntelligenceKind.DEPENDENCIES:
            resolved = self._resolve_file(query, backend)
        else:
            resolved = self._resolve_symbol(query, backend)

        if isinstance(resolved, CodeIntelligenceResult):
            return resolved

        if query.kind is CodeIntelligenceKind.DEPENDENCIES:
            process = self._run(
                "file-deps",
                query.subject,
            )
            parse = self._parse_dependencies
            parse_error = "unable to parse Infigraph dependency output"
        elif query.kind is CodeIntelligenceKind.REFERENCES:
            process = self._run(
                "find-refs",
                query.subject,
            )
            parse = self._parse_references
            parse_error = "unable to parse Infigraph reference output"
        elif query.kind is CodeIntelligenceKind.CALLS:
            escaped_subject = (
                query.subject
                .replace("\\", "\\\\")
                .replace("'", "\\'")
            )
            process = self._run(
                "query",
                (
                    "MATCH (n)-[:CALLS]->(t) "
                    f"WHERE n.id = '{escaped_subject}' "
                    "RETURN t.id,t.file,t.start_line,t.end_line"
                ),
            )
            parse = self._parse_calls
            parse_error = "unable to parse Infigraph CALLS output"
        elif query.kind is CodeIntelligenceKind.TESTS:
            escaped_subject = (
                query.subject
                .replace("\\", "\\\\")
                .replace("'", "\\'")
            )
            process = self._run(
                "query",
                (
                    "MATCH (n)-[:TESTED_BY]->(t) "
                    f"WHERE n.id = '{escaped_subject}' "
                    "RETURN t.id,t.file,t.start_line,t.end_line"
                ),
            )
            parse = self._parse_tests
            parse_error = "unable to parse Infigraph TESTED_BY output"
        else:
            process = self._run(
                "impact",
                "--depth",
                "3",
                query.subject,
            )
            parse = self._parse_impact
            parse_error = "unable to parse Infigraph impact output"

        if isinstance(process, str):
            return self._result(
                query,
                status=CodeIntelligenceStatus.UNAVAILABLE,
                backend_version=backend.version,
                uncertainty=process,
            )

        if process.returncode != 0:
            return self._result(
                query,
                status=CodeIntelligenceStatus.UNAVAILABLE,
                backend_version=backend.version,
                uncertainty=self._process_error(process),
            )

        relations = parse(process.stdout)
        if relations is None:
            return self._result(
                query,
                status=CodeIntelligenceStatus.UNAVAILABLE,
                backend_version=backend.version,
                uncertainty=parse_error,
            )

        fresh, index_revision, uncertainty = self._freshness()

        if query.kind is CodeIntelligenceKind.CALLS:
            calls_uncertainty = (
                "CALLS contains only Infigraph-resolved graph edges; "
                "backend-omitted unresolved builtin, external, dynamic, "
                "or otherwise unresolved calls remain UNKNOWN"
            )
            uncertainty = "; ".join(
                value
                for value in (uncertainty, calls_uncertainty)
                if value
            )

        return self._result(
            query,
            status=CodeIntelligenceStatus.OK,
            relations=relations,
            backend_version=backend.version,
            index_revision=index_revision,
            fresh=fresh,
            uncertainty=uncertainty,
        )


    def _inspect_inventory(
        self,
        query: CodeIntelligenceQuery,
    ) -> CodeIntelligenceResult:
        if (
            query.subject != "."
            or query.subject_kind is not CodeIntelligenceSubjectKind.FILE
        ):
            return self._result(
                query,
                status=CodeIntelligenceStatus.UNAVAILABLE,
                uncertainty="INVENTORY requires the repository root FILE subject '.'",
            )

        backend = self._backend_state(query)
        if isinstance(backend, CodeIntelligenceResult):
            return backend

        language_process = self._run("languages")
        if isinstance(language_process, str) or language_process.returncode != 0:
            detail = (
                language_process
                if isinstance(language_process, str)
                else self._process_error(language_process)
            )
            return self._result(
                query,
                status=CodeIntelligenceStatus.UNAVAILABLE,
                backend_version=backend.version,
                uncertainty=f"unable to enumerate backend language coverage: {detail}",
            )
        extensions = self._parse_language_extensions(language_process.stdout)
        if extensions is None:
            return self._result(
                query,
                status=CodeIntelligenceStatus.UNAVAILABLE,
                backend_version=backend.version,
                uncertainty="unable to parse Infigraph supported-language inventory",
            )

        try:
            source_paths = tuple(sorted(set(self.source_files())))
        except Exception as exc:
            return self._result(
                query,
                status=CodeIntelligenceStatus.UNAVAILABLE,
                backend_version=backend.version,
                uncertainty=f"unable to enumerate repository source paths: {type(exc).__name__}",
            )

        expected_paths = {
            path for path in source_paths
            if (
                self._path_uses_supported_extension(path, extensions)
                or PurePosixPath(path).suffix.lower() in _CONFIG_EXTENSIONS
                or PurePosixPath(path).suffix.lower() in _ARTIFACT_EXTENSIONS
                or PurePosixPath(path).name.lower() in _CONFIG_FILENAMES
                or (
                    PurePosixPath(path).suffix.lower() not in _NON_SOURCE_EXTENSIONS
                    and PurePosixPath(path).name.lower() not in _NON_SOURCE_FILENAMES
                )
            )
        }
        expected_paths = {
            path for path in expected_paths
            if (
                PurePosixPath(path).suffix.lower() not in _NON_SOURCE_EXTENSIONS
                or PurePosixPath(path).name.lower() in _CONFIG_FILENAMES
            )
        }

        files_process = self._run("query", _INVENTORY_FILES_QUERY)
        if isinstance(files_process, str) or files_process.returncode != 0:
            detail = (
                files_process
                if isinstance(files_process, str)
                else self._process_error(files_process)
            )
            return self._result(
                query,
                status=CodeIntelligenceStatus.UNAVAILABLE,
                backend_version=backend.version,
                uncertainty=f"unable to read Infigraph file inventory: {detail}",
            )
        file_rows = self._parse_file_inventory(files_process.stdout)
        if file_rows is None:
            return self._result(
                query,
                status=CodeIntelligenceStatus.UNAVAILABLE,
                backend_version=backend.version,
                uncertainty="unable to parse Infigraph file inventory rows",
            )

        symbols_process = self._run("query", _INVENTORY_SYMBOLS_QUERY)
        if isinstance(symbols_process, str) or symbols_process.returncode != 0:
            detail = (
                symbols_process
                if isinstance(symbols_process, str)
                else self._process_error(symbols_process)
            )
            return self._result(
                query,
                status=CodeIntelligenceStatus.UNAVAILABLE,
                backend_version=backend.version,
                uncertainty=f"unable to read Infigraph symbol inventory: {detail}",
            )
        symbol_rows = self._parse_symbol_inventory(symbols_process.stdout)
        if symbol_rows is None:
            return self._result(
                query,
                status=CodeIntelligenceStatus.UNAVAILABLE,
                backend_version=backend.version,
                uncertainty=("unable to parse Infigraph symbol inventory rows: " +
                             self._symbol_inventory_failure_reason(symbols_process.stdout)),
            )

        indexed = {path: (language, count) for path, language, count in file_rows}
        expected_indexed = expected_paths & set(indexed)
        failed_files = tuple(sorted(expected_paths - set(indexed)))
        relations = [
            CodeIntelligenceRelation(
                target=path,
                relation="FILE",
                file=path,
            )
            for path in sorted(expected_paths)
        ]
        relations.extend(
            CodeIntelligenceRelation(
                target=path,
                relation="MODULE",
                file=path,
                line=1,
            )
            for path in sorted(expected_indexed)
        )
        relations.extend(
            CodeIntelligenceRelation(
                target=path,
                relation="UNINDEXED_FILE",
                file=path,
            )
            for path in failed_files
        )
        fallback = ConfigurationInventory(self.root).inspect(failed_files)
        relations.extend(fallback.relations)
        symbol_counts: dict[str, int] = {}
        unresolved = sum(
            1 for path in expected_indexed
            if indexed[path][0].upper() in {"", "NULL", "NONE", "UNKNOWN"}
            or indexed[path][1] < 0
        )
        source_path_set = set(source_paths)
        for symbol_id, kind, file, line in symbol_rows:
            if file not in source_path_set:
                unresolved += 1
                continue
            if file not in expected_paths:
                continue
            if file not in indexed:
                unresolved += 1
                continue
            symbol_counts[file] = symbol_counts.get(file, 0) + 1
            relations.append(
                CodeIntelligenceRelation(
                    target=symbol_id,
                    relation=kind.upper(),
                    file=file,
                    line=line,
                )
            )

        for path in expected_indexed:
            expected_count = indexed[path][1]
            if expected_count >= 0 and symbol_counts.get(path, 0) != expected_count:
                unresolved += 1

        fresh, revision, freshness_uncertainty = self._freshness()
        completeness = CodeIntelligenceCompleteness(
            expected_files=len(expected_paths),
            analyzed_files=len(expected_indexed),
            failed_files=failed_files,
            unresolved_observations=unresolved + fallback.unresolved_observations,
            fallback_files=fallback.parsed_files,
            unaccounted_files=fallback.failed_files,
        )
        status = (
            CodeIntelligenceStatus.OK
            if fresh and completeness.complete
            else CodeIntelligenceStatus.UNKNOWN
        )
        uncertainty = "; ".join(
            item for item in (
                freshness_uncertainty,
                (
                    f"{len(failed_files)} relevant repository files "
                    "were absent from the Infigraph index"
                    if failed_files else ""
                ),
                (
                    f"{unresolved} symbol/file observations were unresolved"
                    if unresolved else ""
                ),
            ) if item
        )
        return self._result(
            query,
            status=status,
            relations=tuple(sorted(
                relations,
                key=lambda item: (
                    item.file, -1 if item.line is None else item.line,
                    item.relation, item.target,
                ),
            )),
            backend_version=backend.version,
            index_revision=revision,
            fresh=fresh,
            uncertainty=uncertainty,
            completeness=completeness,
        )

    @staticmethod
    def _parse_language_extensions(stdout: str) -> frozenset[str] | None:
        extensions: set[str] = set()
        seen_language = False
        for line in stdout.splitlines():
            if line.strip() == "Available languages:":
                seen_language = True
                continue
            if not line.strip():
                continue
            match = re.fullmatch(
                r"\s+.+?\((?P<extensions>[^)]*)\)\s+\[[^\]]+\]",
                line,
            )
            if match is None:
                return None
            for item in match.group("extensions").split(","):
                extension = item.strip().lower()
                if extension.startswith("*."):
                    extension = extension[1:]
                if extension:
                    extensions.add(extension)
        return frozenset(extensions) if seen_language and extensions else None

    @staticmethod
    def _path_uses_supported_extension(
        path: str,
        extensions: frozenset[str],
    ) -> bool:
        name = PurePosixPath(path).name.lower()
        suffix = PurePosixPath(path).suffix.lower()
        return suffix in extensions or name in extensions

    @staticmethod
    def _parse_file_inventory(
        stdout: str,
    ) -> tuple[tuple[str, str, int], ...] | None:
        if stdout.strip() == "(no results)":
            return ()
        rows = []
        for line in stdout.splitlines():
            fields = line.split(" | ")
            if len(fields) != 3:
                return None
            path, language, count = fields
            pure = PurePosixPath(path)
            if (
                not path or pure.is_absolute() or pure.as_posix() != path
                or ".." in pure.parts
            ):
                return None
            try:
                symbol_count = int(count)
            except ValueError:
                if count.strip().lower() in {"null", "none", ""}:
                    symbol_count = -1
                else:
                    return None
            rows.append((path, language, symbol_count))
        if len({path for path, _, _ in rows}) != len(rows):
            return None
        return tuple(rows)

    @staticmethod
    def _symbol_inventory_failure_reason(stdout: str) -> str:
        """Structural diagnostics only: never output source paths or symbol IDs."""
        if not stdout.strip():
            return "EMPTY_RESPONSE"
        column_mismatch = invalid_path = invalid_line = empty_field = 0
        symbol_ids = set()
        duplicates = 0
        for line in stdout.splitlines():
            fields = line.rsplit(" | ", 3)
            if len(fields) != 4:
                column_mismatch += 1
                continue
            symbol_id, kind, file, start = fields
            pure = PurePosixPath(file)
            if not symbol_id or not kind or not file:
                empty_field += 1
            if pure.is_absolute() or pure.as_posix() != file or ".." in pure.parts:
                invalid_path += 1
            try:
                if int(start) < 1:
                    invalid_line += 1
            except ValueError:
                invalid_line += 1
            if symbol_id in symbol_ids:
                duplicates += 1
            symbol_ids.add(symbol_id)
        return ("column_mismatch=" + str(column_mismatch)
                + "; invalid_path=" + str(invalid_path)
                + "; invalid_line=" + str(invalid_line)
                + "; empty_field=" + str(empty_field)
                + "; duplicate_id=" + str(duplicates)
                + "; rows=" + str(len(stdout.splitlines())))

    @staticmethod
    def _parse_symbol_inventory(
        stdout: str,
    ) -> tuple[tuple[str, str, str, int], ...] | None:
        if stdout.strip() == "(no results)":
            return ()
        rows = []
        for line in stdout.splitlines():
            # #478 supported separators inside symbol IDs. Anchor the four
            # columns from the right rather than rejecting valid graph rows.
            fields = line.rsplit(" | ", 3)
            if len(fields) != 4:
                return None
            symbol_id, kind, file, start_line = fields
            pure = PurePosixPath(file)
            if (
                not symbol_id or not kind or not file
                or pure.is_absolute() or pure.as_posix() != file
                or ".." in pure.parts
            ):
                return None
            try:
                line_number = int(start_line)
            except ValueError:
                return None
            if line_number < 1:
                return None
            rows.append((symbol_id, kind, file, line_number))
        if len({symbol_id for symbol_id, _, _, _ in rows}) != len(rows):
            return None
        return tuple(rows)

    def _git_source_files(self) -> tuple[str, ...]:
        process = self._run_git(
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        )
        if isinstance(process, str):
            raise RuntimeError(process)
        if process.returncode != 0:
            raise RuntimeError(self._git_process_error(process))
        return tuple(sorted(
            item.decode("utf-8", "surrogateescape")
            for item in process.stdout.encode(
                "utf-8", "surrogateescape"
            ).split(b"\0")
            if item and item != b".infigraph"
            and not item.startswith(b".infigraph/")
        ))

    def _backend_state(
        self,
        query: CodeIntelligenceQuery,
    ) -> _BackendState | CodeIntelligenceResult:
        process = self._run("--version")
        if isinstance(process, str):
            return self._result(
                query,
                status=CodeIntelligenceStatus.UNAVAILABLE,
                uncertainty=process,
            )

        if process.returncode != 0:
            return self._result(
                query,
                status=CodeIntelligenceStatus.UNAVAILABLE,
                uncertainty=self._process_error(process),
            )

        match = re.search(
            r"\binfigraph\s+([0-9]+\.[0-9]+\.[0-9]+)\b",
            process.stdout,
        )
        if match is None:
            return self._result(
                query,
                status=CodeIntelligenceStatus.UNAVAILABLE,
                uncertainty="unable to parse Infigraph version",
            )

        version = match.group(1)
        if version != _SUPPORTED_VERSION:
            return self._result(
                query,
                status=CodeIntelligenceStatus.UNAVAILABLE,
                backend_version=version,
                uncertainty=(
                    f"unsupported Infigraph version {version}; "
                    f"validated version is {_SUPPORTED_VERSION}"
                ),
            )

        return _BackendState(
            version=version,
            index_revision=self._refresh_revision,
        )

    def _resolve_file(
        self,
        query: CodeIntelligenceQuery,
        backend: _BackendState,
    ) -> CodeIntelligenceResult | None:
        process = self._run(
            "symbols",
            query.subject,
        )

        if isinstance(process, str):
            return self._result(
                query,
                status=CodeIntelligenceStatus.UNAVAILABLE,
                backend_version=backend.version,
                uncertainty=process,
            )

        if process.returncode != 0:
            return self._result(
                query,
                status=CodeIntelligenceStatus.UNAVAILABLE,
                backend_version=backend.version,
                uncertainty=self._process_error(process),
            )

        if process.stdout.strip().startswith(
            "No symbols found for "
        ):
            return self._result(
                query,
                status=CodeIntelligenceStatus.UNKNOWN,
                backend_version=backend.version,
                uncertainty="file not present in backend index",
            )

        expected = f"Symbols in {query.subject}:"
        if expected not in process.stdout:
            return self._result(
                query,
                status=CodeIntelligenceStatus.UNAVAILABLE,
                backend_version=backend.version,
                uncertainty="unable to verify file in Infigraph index",
            )

        return None

    def _resolve_symbol(
        self,
        query: CodeIntelligenceQuery,
        backend: _BackendState,
    ) -> bool | CodeIntelligenceResult:
        escaped = query.subject.replace("\\", "\\\\").replace("'", "\\'")
        statement = (
            "MATCH (n) WHERE n.id = "
            f"'{escaped}' RETURN n"
        )

        process = self._run("query", statement)
        if isinstance(process, str):
            return self._result(
                query,
                status=CodeIntelligenceStatus.UNAVAILABLE,
                backend_version=backend.version,
                uncertainty=process,
            )

        if process.returncode != 0:
            return self._result(
                query,
                status=CodeIntelligenceStatus.UNAVAILABLE,
                backend_version=backend.version,
                uncertainty=self._process_error(process),
            )

        stripped = process.stdout.strip()

        if stripped == "(no results)":
            return self._result(
                query,
                status=CodeIntelligenceStatus.UNKNOWN,
                backend_version=backend.version,
                uncertainty="subject not present in backend index",
            )

        if f"id:{query.subject}" not in process.stdout:
            return self._result(
                query,
                status=CodeIntelligenceStatus.UNAVAILABLE,
                backend_version=backend.version,
                uncertainty="unable to verify subject identity in backend index",
            )

        return True

    def _git_source_identity(self) -> str:
        process = self._run_git(
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        )
        if isinstance(process, str):
            raise RuntimeError(process)
        if process.returncode != 0:
            raise RuntimeError(self._git_process_error(process))

        raw_paths = [
            item
            for item in process.stdout.encode(
                "utf-8",
                "surrogateescape",
            ).split(b"\0")
            if item
            and item != b".infigraph"
            and not item.startswith(b".infigraph/")
        ]
        raw_paths.sort()

        digest = hashlib.sha256()

        for raw in raw_paths:
            relative = raw.decode("utf-8", "surrogateescape")
            candidate = self.root / relative

            digest.update(len(raw).to_bytes(8, "big"))
            digest.update(raw)

            if candidate.is_file():
                data = candidate.read_bytes()
                digest.update(b"FILE")
                digest.update(len(data).to_bytes(8, "big"))
                digest.update(data)
            else:
                digest.update(b"MISSING")
                digest.update((0).to_bytes(8, "big"))

        return digest.hexdigest()

    def _freshness(self) -> tuple[bool, str, str]:
        revision = self._refresh_revision
        if self._receipt_store is not None:
            try:
                current = self.source_identity()
                self._receipt_store.verify(current, _SUPPORTED_VERSION)
                revision = current
            except (OSError, ValueError, RuntimeError) as exc:
                return False, revision, f"persisted index receipt unavailable: {exc}"
        if not revision:
            return (
                False,
                "",
                "index freshness has not been established by an explicit refresh lifecycle",
            )

        try:
            current = self.source_identity()
        except Exception as exc:
            return (
                False,
                revision,
                f"unable to establish current source identity: {exc}",
            )

        if current != revision:
            return (
                False,
                revision,
                "source identity no longer matches explicit refresh",
            )

        return True, revision, ""

    def _run_git(self, *args: str):
        try:
            return subprocess.run(
                ["git", *args],
                cwd=self.root,
                timeout=self.timeout_seconds,
                capture_output=True,
                text=True,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return "Git source identity command timed out"
        except (OSError, subprocess.SubprocessError) as exc:
            return f"Git source identity unavailable: {exc}"

    @staticmethod
    def _git_process_error(
        process: subprocess.CompletedProcess[str],
    ) -> str:
        detail = (process.stderr or process.stdout).strip()
        if detail:
            return f"Git source identity command failed: {detail}"
        return (
            "Git source identity command failed with "
            f"exit code {process.returncode}"
        )

    def _run(self, *args: str):
        try:
            env = os.environ.copy()
            env["INFIGRAPH_NO_WATCH"] = "1"
            if self._receipt_store is not None:
                env["INFIGRAPH_BACKEND"] = "kuzu"
            return self.runner(
                [str(self.executable), *args],
                cwd=self.root,
                timeout=self.timeout_seconds,
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return "Infigraph command timed out"
        except (OSError, subprocess.SubprocessError) as exc:
            return f"Infigraph unavailable: {exc}"

    @staticmethod
    def _process_error(
        process: subprocess.CompletedProcess[str],
    ) -> str:
        detail = (process.stderr or process.stdout).strip()
        if detail:
            return f"Infigraph command failed: {detail}"
        return (
            "Infigraph command failed with "
            f"exit code {process.returncode}"
        )

    @staticmethod
    def _parse_references(
        stdout: str,
    ) -> tuple[CodeIntelligenceRelation, ...] | None:
        stripped = stdout.strip()

        if stripped.startswith("No references found for "):
            return ()

        header = re.search(
            r"^References to .+ \((?P<count>[0-9]+) total\):$",
            stdout,
            re.MULTILINE,
        )
        if header is None:
            return None

        expected = int(header.group("count"))
        relations = []

        for line in stdout.splitlines():
            match = _REFERENCE_LINE.match(line)
            if match is None:
                continue

            file = match.group("file")
            line_number = int(match.group("line"))
            context = match.group("context")

            relations.append(
                CodeIntelligenceRelation(
                    target=f"{file}::{context}",
                    relation="REFERENCE",
                    file=file,
                    line=line_number,
                )
            )

        if len(relations) != expected:
            return None

        return tuple(relations)

    @staticmethod
    def _parse_dependencies(
        stdout: str,
    ) -> tuple[CodeIntelligenceRelation, ...] | None:
        header = re.search(
            r"^File dependencies for '.+':$",
            stdout,
            re.MULTILINE,
        )
        if header is None:
            return None

        imports_match = re.search(
            r"^\s*Imports \((?P<count>[0-9]+)\):\s*$",
            stdout,
            re.MULTILINE,
        )
        imported_by_match = re.search(
            r"^\s*Imported by \((?P<count>[0-9]+)\):\s*$",
            stdout,
            re.MULTILINE,
        )

        if imports_match is None or imported_by_match is None:
            return None

        relations = []
        mode = None

        for line in stdout.splitlines():
            stripped = line.strip()

            if re.fullmatch(r"Imports \([0-9]+\):", stripped):
                mode = "IMPORTS"
                continue

            if re.fullmatch(r"Imported by \([0-9]+\):", stripped):
                mode = "IMPORTED_BY"
                continue

            if not stripped or stripped == "(none)":
                continue

            if stripped.startswith("File dependencies for "):
                continue

            if stripped.startswith("→ "):
                if mode != "IMPORTS":
                    return None
                target = stripped[2:].strip()
                relations.append(
                    CodeIntelligenceRelation(
                        target=target,
                        relation="IMPORTS",
                        file=target,
                    )
                )
                continue

            if stripped.startswith("← "):
                if mode != "IMPORTED_BY":
                    return None
                target = stripped[2:].strip()
                relations.append(
                    CodeIntelligenceRelation(
                        target=target,
                        relation="IMPORTED_BY",
                        file=target,
                    )
                )
                continue

            return None

        imports_expected = int(imports_match.group("count"))
        imported_by_expected = int(
            imported_by_match.group("count")
        )

        imports_actual = sum(
            relation.relation == "IMPORTS"
            for relation in relations
        )
        imported_by_actual = sum(
            relation.relation == "IMPORTED_BY"
            for relation in relations
        )

        if (
            imports_actual != imports_expected
            or imported_by_actual != imported_by_expected
        ):
            return None

        return tuple(relations)

    @staticmethod
    def _parse_calls(
        stdout: str,
    ) -> tuple[CodeIntelligenceRelation, ...] | None:
        """Parse only resolved Infigraph CALLS graph edges.

        Infigraph does not retain dangling edges for unresolved builtin,
        external or dynamic calls.  Absence from this result therefore
        must not be interpreted as proof that no source-level call exists.
        """

        stripped = stdout.strip()

        if stripped == "(no results)":
            return ()

        if not stripped:
            return None

        relations: list[CodeIntelligenceRelation] = []

        for raw_line in stripped.splitlines():
            parts = [
                part.strip()
                for part in raw_line.split(" | ")
            ]

            if len(parts) != 4:
                return None

            target, file, start_line, end_line = parts

            if not target or not file:
                return None

            if not target.startswith(f"{file}::"):
                return None

            try:
                start = int(start_line)
                end = int(end_line)
            except ValueError:
                return None

            if start < 1 or end < start:
                return None

            relations.append(
                CodeIntelligenceRelation(
                    target=target,
                    relation="CALLS",
                    file=file,
                    line=start,
                )
            )

        return tuple(relations)

    @staticmethod
    def _parse_tests(
        stdout: str,
    ) -> tuple[CodeIntelligenceRelation, ...] | None:
        stripped = stdout.strip()

        if stripped == "(no results)":
            return ()

        if not stripped:
            return None

        relations: list[CodeIntelligenceRelation] = []

        for raw_line in stripped.splitlines():
            parts = [
                part.strip()
                for part in raw_line.split(" | ")
            ]

            if len(parts) != 4:
                return None

            target, file, start_line, end_line = parts

            if not target or not file:
                return None

            if not file.startswith("tests/"):
                return None

            if not target.startswith(f"{file}::"):
                return None

            try:
                start = int(start_line)
                end = int(end_line)
            except ValueError:
                return None

            if start < 1 or end < start:
                return None

            relations.append(
                CodeIntelligenceRelation(
                    target=target,
                    relation="TESTED_BY",
                    file=file,
                    line=start,
                )
            )

        return tuple(relations)

    @staticmethod
    def _parse_impact(
        stdout: str,
    ) -> tuple[CodeIntelligenceRelation, ...] | None:
        stripped = stdout.strip()

        if stripped.startswith(
            "No symbols affected by changes to "
        ):
            return ()

        header = re.search(
            r"^Symbols affected by changes to .+ "
            r"\(depth=[0-9]+\):$",
            stdout,
            re.MULTILINE,
        )
        if header is None:
            return None

        relations = []

        for line in stdout.splitlines():
            stripped_line = line.strip()
            if not stripped_line:
                continue

            match = re.match(
                r"^(?:Test|Function|Method|Class)\s+"
                r"(?P<name>\S+)\s+"
                r"(?P<file>(?:src|tests|scripts)/\S+\.py)$",
                stripped_line,
            )
            if match is None:
                continue

            file = match.group("file")
            name = match.group("name")

            relations.append(
                CodeIntelligenceRelation(
                    target=f"{file}::{name}",
                    relation="IMPACT",
                    file=file,
                )
            )

        body = stdout[header.end():].strip()
        if body and not relations:
            return None

        return tuple(relations)

    @staticmethod
    def _result(
        query: CodeIntelligenceQuery,
        *,
        status: CodeIntelligenceStatus,
        relations: tuple[CodeIntelligenceRelation, ...] = (),
        backend_version: str = "",
        index_revision: str = "",
        fresh: bool = False,
        uncertainty: str = "",
        completeness: CodeIntelligenceCompleteness | None = None,
    ) -> CodeIntelligenceResult:
        return CodeIntelligenceResult(
            kind=query.kind,
            subject=query.subject,
            status=status,
            relations=relations,
            backend="infigraph",
            backend_version=backend_version,
            index_revision=index_revision,
            fresh=fresh,
            uncertainty=uncertainty,
            completeness=completeness,
        )
