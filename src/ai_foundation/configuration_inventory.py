"""Structured, non-executing inventory for files outside Infigraph's parsers.

Only names, structural relationships, safe dependency identifiers and digests
are emitted. Configuration values, environment values and command bodies are
never copied into the semantic inventory.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import tomllib


from .code_intelligence import CodeIntelligenceRelation


_MAX_TEXT_BYTES = 2_000_000
_ARTIFACT_EXTENSIONS = frozenset({
    ".dylib", ".so", ".dll", ".wasm", ".jar", ".node", ".a", ".o",
    ".class", ".pyc", ".pyd", ".exe", ".pkg", ".bin", ".pem",
    ".pem", ".crt", ".key", ".p12", ".pfx", ".mobileprovision",
    ".swiftmodule", ".swiftdoc", ".metallib",
})
_SECRET_KEY = re.compile(r"(?:secret|token|password|credential|api[_-]?key|private[_-]?key)", re.I)
_PATCH_FILE = re.compile(r"^diff --git a/(.+?) b/(.+?)$")
_PATCH_OLD_FILE = re.compile(r"^--- a/(.+?)(?:\t.*)?$")
_PATCH_NEW_FILE = re.compile(r"^\+\+\+ b/(.+?)(?:\t.*)?$")
_PATCH_HUNK = re.compile(
    r"^@@ (?P<header>-(?P<old_start>\d+)(?:,(?P<old_count>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))?) @@(?: (?P<context>.*))?$"
)
_CEDAR_RULE = re.compile(r"^\s*(permit|forbid)\s*\(")
_SCHEMA_DECL = re.compile(r"^\s*(entity|action|namespace|type|commonTypes|annotations)\b")


@dataclass(frozen=True)
class ConfigurationInventoryResult:
    relations: tuple[CodeIntelligenceRelation, ...] = ()
    parsed_files: tuple[str, ...] = ()
    failed_files: tuple[str, ...] = ()
    unresolved_observations: int = 0


class ConfigurationInventory:
    """Read-only fallback inventory for workflow, policy, lock and artifact files."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()

    def inspect(self, paths: tuple[str, ...]) -> ConfigurationInventoryResult:
        relations: list[CodeIntelligenceRelation] = []
        parsed: list[str] = []
        failed: list[str] = []
        unresolved = 0
        for relative in sorted(set(paths)):
            try:
                emitted = self._inspect_one(relative)
            except (OSError, UnicodeError, ValueError, TypeError, tomllib.TOMLDecodeError, csv.Error):
                failed.append(relative)
                unresolved += 1
                continue
            if emitted is None:
                failed.append(relative)
                unresolved += 1
                continue
            parsed.append(relative)
            relations.extend(emitted)
        return ConfigurationInventoryResult(
            relations=tuple(sorted(
                relations,
                key=lambda item: (
                    item.file, -1 if item.line is None else item.line,
                    item.relation, item.target,
                ),
            )),
            parsed_files=tuple(parsed),
            failed_files=tuple(failed),
            unresolved_observations=unresolved,
        )

    def _inspect_one(self, relative: str) -> tuple[CodeIntelligenceRelation, ...] | None:
        posix = PurePosixPath(relative)
        if posix.is_absolute() or ".." in posix.parts or not posix.parts:
            return None
        candidate = self.root.joinpath(*posix.parts)
        if candidate.is_symlink():
            return None
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(self.root) or not resolved.is_file():
            return None
        size = resolved.stat().st_size
        suffix = posix.suffix.lower()
        name = posix.name.lower()

        if suffix in _ARTIFACT_EXTENSIONS:
            return (self._relation(relative, "ARTIFACT_FILE", relative),)
        if size > _MAX_TEXT_BYTES:
            return None
        # These three real-M1 P02 gaps have no safe statement-level parser.
        # Keep the existence and file identity visible as UNMAPPED structural
        # evidence, not as a claim about build commands or script behavior.
        # Unlike an extension-wide exclusion, every other source file still
        # needs its own explicitly grounded inventory coverage.
        if name == "dockerfile":
            return (self._relation(relative, "BUILD_FILE_UNPARSED", relative),)
        if suffix == ".command":
            return (self._relation(relative, "SCRIPT_FILE_UNPARSED", relative),)
        if suffix == ".log" and relative.startswith("docs/evidence/"):
            # Stored diagnostic logs can contain private values: do not read
            # or derive symbols from their text.
            return (self._relation(relative, "EVIDENCE_LOG_UNPARSED", relative),)
        if name == ".gitignore":
            return self._gitignore(relative, resolved)
        if suffix == ".patch":
            return self._patch(relative, resolved)
        if suffix == ".tsv":
            return self._tsv(relative, resolved)
        if suffix == ".cedar":
            return self._cedar(relative, resolved, schema=False)
        if suffix == ".cedarschema":
            return self._cedar(relative, resolved, schema=True)

        text = resolved.read_text(encoding="utf-8")
        if suffix in {".yaml", ".yml"}:
            return self._yaml(relative, text)
        if suffix == ".toml" or name == "uv.lock":
            return self._toml(relative, text, is_uv_lock=name == "uv.lock")
        if suffix == ".json":
            return self._json(relative, text)
        return None

    def _yaml(self, path: str, text: str) -> tuple[CodeIntelligenceRelation, ...]:
        try:
            import yaml
        except ImportError as exc:
            raise ValueError("PyYAML is unavailable for YAML inventory") from exc
        try:
            value = yaml.load(text, Loader=yaml.BaseLoader)
        except yaml.YAMLError as exc:
            raise ValueError("YAML configuration is invalid") from exc
        if not isinstance(value, dict):
            raise ValueError("YAML root must be a mapping")
        relations = [self._relation(path, "CONFIG_FILE", path)]
        if path.startswith(".github/workflows/"):
            relations.append(self._relation(path, "WORKFLOW_FILE", path))
            self._emit_permissions(
                relations, path, f"{path}#workflow", value.get("permissions")
            )
            triggers = value.get("on", value.get(True))
            for trigger in self._keys_or_values(triggers):
                relations.append(self._relation(path, "WORKFLOW_TRIGGER", f"{path}#on:{trigger}"))
            jobs = value.get("jobs", {})
            if not isinstance(jobs, dict):
                raise ValueError("workflow jobs must be a mapping")
            for job_name, job in jobs.items():
                if not isinstance(job, dict):
                    raise ValueError("workflow job must be a mapping")
                job_ref = f"{path}#job:{job_name}"
                relations.append(self._relation(path, "WORKFLOW_JOB", job_ref))
                for need in self._keys_or_values(job.get("needs")):
                    relations.append(self._relation(path, "WORKFLOW_NEEDS", f"{job_ref}#needs:{need}"))
                for runner in self._keys_or_values(job.get("runs-on")):
                    relations.append(self._relation(path, "WORKFLOW_RUNNER", f"{job_ref}#runs-on:{runner}"))
                self._emit_key_names(relations, path, "WORKFLOW_ENV_KEY", job_ref, job.get("env"))
                self._emit_permissions(relations, path, job_ref, job.get("permissions"))
                steps = job.get("steps", [])
                if not isinstance(steps, list):
                    raise ValueError("workflow steps must be a list")
                for index, step in enumerate(steps):
                    if not isinstance(step, dict):
                        raise ValueError("workflow step must be a mapping")
                    step_ref = f"{job_ref}#step:{index + 1}"
                    relations.append(self._relation(path, "WORKFLOW_STEP", step_ref))
                    uses = step.get("uses")
                    if isinstance(uses, str) and uses:
                        relations.append(self._relation(path, "WORKFLOW_USES", f"{step_ref}#uses:{uses}"))
                    run = step.get("run")
                    if isinstance(run, str) and run:
                        digest = hashlib.sha256(run.encode("utf-8")).hexdigest()
                        relations.append(self._relation(path, "WORKFLOW_RUN_DIGEST", f"{step_ref}#sha256:{digest}"))
                    self._emit_key_names(relations, path, "WORKFLOW_ENV_KEY", step_ref, step.get("env"))
                    self._emit_key_names(relations, path, "WORKFLOW_INPUT_KEY", step_ref, step.get("with"))
        else:
            self._walk_keys(relations, path, value)
        return tuple(relations)

    def _toml(self, path: str, text: str, *, is_uv_lock: bool) -> tuple[CodeIntelligenceRelation, ...]:
        value = tomllib.loads(text)
        relations = [self._relation(path, "CONFIG_FILE", path)]
        self._walk_keys(relations, path, value)
        if is_uv_lock:
            packages = value.get("package", [])
            if not isinstance(packages, list):
                raise ValueError("uv.lock package table must be an array")
            for package in packages:
                if not isinstance(package, dict):
                    raise ValueError("uv.lock package entry must be a table")
                name = package.get("name")
                version = package.get("version")
                if not isinstance(name, str) or not isinstance(version, str):
                    raise ValueError("uv.lock package identity is incomplete")
                package_ref = f"{name}@{version}"
                relations.append(self._relation(path, "DEPENDENCY", package_ref))
                dependencies = package.get("dependencies", [])
                if isinstance(dependencies, list):
                    for dependency in dependencies:
                        if isinstance(dependency, dict) and isinstance(dependency.get("name"), str):
                            relations.append(self._relation(
                                path, "DEPENDENCY_EDGE",
                                f"{package_ref}->{dependency['name']}",
                            ))
        return tuple(relations)

    def _json(self, path: str, text: str) -> tuple[CodeIntelligenceRelation, ...]:
        value = json.loads(text)
        if not isinstance(value, (dict, list)):
            raise ValueError("JSON root must be an object or array")
        relations = [self._relation(path, "CONFIG_FILE", path)]
        self._walk_keys(relations, path, value)
        return tuple(relations)

    def _cedar(self, path: str, file_path: Path, *, schema: bool) -> tuple[CodeIntelligenceRelation, ...]:
        text = file_path.read_text(encoding="utf-8")
        relations = [self._relation(path, "POLICY_SCHEMA_FILE" if schema else "POLICY_FILE", path)]
        found = 0
        for number, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("//"):
                continue
            match = _SCHEMA_DECL.match(line) if schema else _CEDAR_RULE.match(line)
            if match:
                kind = "POLICY_SCHEMA_DECLARATION" if schema else "POLICY_RULE"
                relations.append(self._relation(path, kind, f"{path}#line:{number}:{match.group(1)}", number))
                found += 1
        if not found:
            raise ValueError("no recognized Cedar declarations")
        return tuple(relations)

    def _patch(self, path: str, file_path: Path) -> tuple[CodeIntelligenceRelation, ...]:
        text = file_path.read_text(encoding="utf-8")
        relations = [self._relation(path, "PATCH_FILE", path)]
        current = None
        files = 0
        git_section = False
        in_hunk = False
        remaining_old = 0
        remaining_new = 0
        lines = text.splitlines()
        for index, line in enumerate(lines):
            number = index + 1
            if in_hunk:
                if line.startswith(" "):
                    remaining_old -= 1
                    remaining_new -= 1
                elif line.startswith("-"):
                    remaining_old -= 1
                elif line.startswith("+"):
                    remaining_new -= 1
                elif line.startswith("\\"):
                    pass
                else:
                    in_hunk = False
                if in_hunk:
                    if remaining_old <= 0 and remaining_new <= 0:
                        in_hunk = False
                    continue

            match = _PATCH_FILE.match(line)
            if match:
                current = match.group(2)
                git_section = True
                files += 1
                relations.append(self._relation(
                    path, "PATCH_TARGET_FILE", f"{path}#target:{current}", number
                ))
                continue

            # Traditional unified headers are accepted only outside a hunk and
            # only when they form a paired ---/+++ section.
            old_file = _PATCH_OLD_FILE.match(line)
            if not git_section and not in_hunk and old_file and index + 1 < len(lines):
                new_file = _PATCH_NEW_FILE.match(lines[index + 1])
                if new_file:
                    current = new_file.group(1)
                    files += 1
                    relations.append(self._relation(
                        path, "PATCH_TARGET_FILE", f"{path}#target:{current}", number
                    ))
                    continue

            hunk = _PATCH_HUNK.match(line)
            if hunk and current:
                relations.append(self._relation(
                    path, "PATCH_HUNK",
                    f"{path}#target:{current}#hunk:{number}:{hunk.group('header')}",
                    number,
                ))
                remaining_old = int(hunk.group("old_count") or "1")
                remaining_new = int(hunk.group("new_count") or "1")
                in_hunk = remaining_old > 0 or remaining_new > 0
        if files == 0:
            raise ValueError("patch has no unified diff file headers")
        return tuple(relations)

    def _tsv(self, path: str, file_path: Path) -> tuple[CodeIntelligenceRelation, ...]:
        text = file_path.read_text(encoding="utf-8")
        reader = csv.DictReader(io.StringIO(text), delimiter="\t")
        if not reader.fieldnames:
            raise ValueError("TSV header is missing")
        headers = {header.strip().lower(): header for header in reader.fieldnames if header}
        name_key = next((headers[key] for key in ("package", "name", "dependency", "project", "distribution") if key in headers), None)
        version_key = next((headers[key] for key in ("version", "resolved_version") if key in headers), None)
        license_key = next((headers[key] for key in ("license", "license_expression", "licenses") if key in headers), None)
        relations = [self._relation(path, "TABULAR_FILE", path)]
        rows = 0
        for row_number, row in enumerate(reader, 2):
            rows += 1
            package = (row.get(name_key) or "").strip() if name_key else ""
            version = (row.get(version_key) or "").strip() if version_key else ""
            license_name = (row.get(license_key) or "").strip() if license_key else ""
            if package:
                target = f"{package}@{version}:{license_name}"
                relations.append(self._relation(path, "LICENSE_RECORD", target, row_number))
            else:
                relations.append(self._relation(path, "TABULAR_ROW", f"{path}#row:{row_number}", row_number))
        if rows == 0:
            raise ValueError("TSV contains no data rows")
        return tuple(relations)

    def _gitignore(self, path: str, file_path: Path) -> tuple[CodeIntelligenceRelation, ...]:
        text = file_path.read_text(encoding="utf-8")
        relations = [self._relation(path, "IGNORE_FILE", path)]
        for number, line in enumerate(text.splitlines(), 1):
            pattern = line.strip()
            if not pattern or pattern.startswith("#"):
                continue
            relations.append(self._relation(path, "IGNORE_PATTERN", f"{path}#pattern:{pattern}", number))
        return tuple(relations)

    def _walk_keys(
        self, relations, path: str, value, prefix: str = "",
        *, _active: set[int] | None = None, _depth: int = 0,
    ) -> None:
        if _depth > 64:
            raise ValueError("configuration nesting exceeds the inventory depth bound")
        if not isinstance(value, (dict, list)):
            return
        active = set() if _active is None else _active
        identity = id(value)
        if identity in active:
            raise ValueError("recursive configuration alias")
        active.add(identity)
        try:
            if isinstance(value, dict):
                for key, child in value.items():
                    key_text = str(key)
                    full = f"{prefix}.{key_text}" if prefix else key_text
                    if _SECRET_KEY.search(key_text):
                        relations.append(self._relation(path, "CONFIG_SECRET_KEY", f"{path}#key:{full}"))
                        continue
                    relations.append(self._relation(path, "CONFIG_KEY", f"{path}#key:{full}"))
                    self._walk_keys(
                        relations, path, child, full,
                        _active=active, _depth=_depth + 1,
                    )
            else:
                for index, child in enumerate(value):
                    self._walk_keys(
                        relations, path, child, f"{prefix}[{index}]",
                        _active=active, _depth=_depth + 1,
                    )
        finally:
            active.remove(identity)

    def _emit_key_names(self, relations, path, relation, prefix, value) -> None:
        if isinstance(value, dict):
            for key in value:
                key_text = str(key)
                kind = "CONFIG_SECRET_KEY" if _SECRET_KEY.search(key_text) else relation
                relations.append(self._relation(path, kind, f"{prefix}#{relation}:{key_text}"))

    def _emit_permissions(self, relations, path, prefix, value) -> None:
        if isinstance(value, dict):
            for key, level in value.items():
                relations.append(self._relation(path, "WORKFLOW_PERMISSION", f"{prefix}#permission:{key}:{level}"))
        elif isinstance(value, str) and value:
            relations.append(self._relation(
                path, "WORKFLOW_PERMISSION", f"{prefix}#permission:{value}"
            ))

    @staticmethod
    def _keys_or_values(value) -> tuple[str, ...]:
        if isinstance(value, dict):
            return tuple(str(key) for key in value)
        if isinstance(value, list):
            return tuple(str(item) for item in value)
        if isinstance(value, str) and value:
            return (value,)
        return ()

    @staticmethod
    def _relation(path, relation, target, line=None) -> CodeIntelligenceRelation:
        return CodeIntelligenceRelation(
            target=str(target),
            relation=str(relation),
            file=path,
            line=line,
        )
