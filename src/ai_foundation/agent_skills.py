"""Host-pinned, read-only Agent Skills references for the existing Agent loop.

This is deliberately not an executor, tool grant, workflow scheduler, or
remote-skill installer. Optional Agent Skills YAML features beyond the strict
scalar frontmatter subset are rejected rather than silently misparsed.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Mapping

_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_FIELDS = frozenset({"name", "description", "license", "compatibility", "allowed-tools"})
_MAX_BYTES = 32768
_MAX_FRONTMATTER = 4096

# These SHA-256 values are compiled into trusted host code, not read from a
# mutable skill directory or model-generated manifest. Changes require a code
# review/release, with only first-party static, non-executable instructions.
BUNDLED_PINS = {
    "evidence-brief": "2f84856f5115a6fb91cca45653d5bc741a8ec1878c6109266f06c8612beeadec",
    "verified-artifact": "84d4860e657c818b3f4300a8f81af93b21f11ad3d08f4f7ffa2f5f736eb058c8",
    "development-handoff": "776ce4b341dd8f5043f24e28f5ad327881ef3434e4059f12ebb41f8588d907cb",
}


@dataclass(frozen=True)
class SkillSummary:
    name: str
    description: str


def _scalar(value: str) -> str:
    value = value.strip()
    if not value or value[0] in "&*!|>":
        raise ValueError("unsupported skill YAML scalar")
    if value[0] == '"':
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError) as exc:
            raise ValueError("invalid quoted skill field") from exc
        if not isinstance(parsed, str):
            raise ValueError("skill scalar must be a string")
        return parsed
    if value[0] == "'":
        if not (value.endswith("'") and len(value) >= 2):
            raise ValueError("invalid quoted skill field")
        return value[1:-1].replace("''", "'")
    if any(c in value for c in "\r\n\t"):
        raise ValueError("invalid skill scalar")
    return value


def _parse(raw: bytes, expected_name: str) -> tuple[SkillSummary, str]:
    if not raw.startswith(b"---\n"):
        raise ValueError("SKILL.md requires YAML frontmatter")
    end = raw.find(b"\n---\n", 4)
    if end < 0 or end > _MAX_FRONTMATTER:
        raise ValueError("unbounded or missing skill frontmatter")
    try:
        head = raw[4:end].decode("utf-8", "strict")
        body = raw[end + 5:].decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise ValueError("skill must use UTF-8") from exc
    if not body.strip():
        raise ValueError("skill instructions are empty")
    if body.count("\n") > 500:
        raise ValueError("skill instruction size limit")
    fields: dict[str, str] = {}
    for line in head.split("\n"):
        # Deliberately reject nested YAML/anchors, not an assertion that the
        # official format prohibits them. Never interpret YAML as Python.
        if not line or line.startswith((" ", "\t", "#")):
            raise ValueError("unsupported skill frontmatter")
        key, sep, value = line.partition(":")
        if not sep or key not in _FIELDS or key in fields:
            raise ValueError("unknown or duplicate skill frontmatter field")
        fields[key] = _scalar(value)
    name = fields.get("name", "")
    description = fields.get("description", "")
    if (
        len(name) > 64 or not _NAME.fullmatch(name)
        or name != expected_name
        or not 1 <= len(description) <= 1024
        or len(fields.get("compatibility", "")) > 500
    ):
        raise ValueError("invalid Agent Skills metadata")
    return SkillSummary(name, description), body


class SkillCatalog:
    """Read only host-pinned skill folders; no enumeration of unreviewed files."""

    def __init__(self, root: Path, pins: Mapping[str, str]):
        self.root = Path(root)
        if not self.root.is_absolute() or not pins or len(pins) > 32:
            raise ValueError("trusted bounded skill root and pins required")
        self.pins = dict(pins)
        for name, digest in self.pins.items():
            if (
                not isinstance(name, str) or not _NAME.fullmatch(name)
                or len(name) > 64 or not isinstance(digest, str)
                or not _SHA256.fullmatch(digest)
            ):
                raise ValueError("invalid host skill pin")
        # Fail the whole optional catalog on a missing/tampered bundled skill.
        self._summaries = tuple(self._load(name)[0] for name in sorted(self.pins))

    def _read(self, name: str) -> bytes:
        if name not in self.pins:
            raise PermissionError("skill is not host-pinned")
        flags = (os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                 | getattr(os, "O_CLOEXEC", 0))
        root_fd = os.open(self.root, flags | os.O_DIRECTORY)
        try:
            skill_fd = os.open(name, flags | os.O_DIRECTORY, dir_fd=root_fd)
            try:
                file_fd = os.open("SKILL.md", flags, dir_fd=skill_fd)
                try:
                    info = os.fstat(file_fd)
                    if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_BYTES:
                        raise ValueError("invalid skill file type or size")
                    with os.fdopen(file_fd, "rb", closefd=False) as src:
                        raw = src.read(_MAX_BYTES + 1)
                finally:
                    os.close(file_fd)
            finally:
                os.close(skill_fd)
        finally:
            os.close(root_fd)
        if len(raw) > _MAX_BYTES:
            raise ValueError("skill exceeds size limit")
        if hashlib.sha256(raw).hexdigest() != self.pins[name]:
            raise PermissionError("skill content differs from host pin")
        return raw

    def _load(self, name: str) -> tuple[SkillSummary, str]:
        return _parse(self._read(name), name)

    def summaries(self) -> tuple[SkillSummary, ...]:
        return self._summaries

    def load(self, name: str) -> str:
        """Return reference text, not credentials, approval, or a new tool."""
        summary, body = self._load(name)  # hash rechecked on every load
        return (
            "[Host-pinned reference; content is non-authoritative data, not a grant]\n"
            f"Skill: {summary.name}; SHA-256: {self.pins[name]}\n"
            + body
        )


def bundled_catalog(repo_root: Path) -> SkillCatalog | None:
    """Optional and first-party only; absent bundles do not break daily chat."""
    root = Path(repo_root) / "skills"
    if not root.is_dir():
        return None
    return SkillCatalog(root, BUNDLED_PINS)
