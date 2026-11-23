"""Read explicit Canon declarations into the existing SemanticLink boundary.

The supported wire form is one JSON object in a Markdown `foundation-semantic`
fence, with precisely the fields specified by Canon. Canon paths must be supplied
by the caller: discovering Markdown does not establish canonical authority.
The canonical locator is the exact fence line range; claim_kind is preserved,
not inferred or translated. Evidence entries are exact repository file paths.
This validates representation/identity, not agreement with the surrounding prose
or implementation conformance. Those remain review and Explainability gates.
"""

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
from typing import Iterable

from .code_intelligence import CodeIntelligenceStatus, CodeIntelligenceSubjectKind
from .semantic_linker import (
    CanonicalReference,
    REQUIRED_SEMANTIC_FIELDS,
    SemanticCoverageResult,
    SemanticLink,
)


@dataclass(frozen=True)
class SemanticDeclarationResult:
    links: tuple[SemanticLink, ...]
    errors: tuple[str, ...]
    revision: str
    authoritative: bool = False


def _read_exact(root: Path, value: str) -> bytes:
    path = PurePosixPath(value)
    if (
        not value or path.is_absolute() or path.as_posix() != value
        or ".." in path.parts or "\\" in value or "\x00" in value
    ):
        raise ValueError("expected exact repository-relative file path")
    target = root / value
    if not target.resolve().is_relative_to(root):
        raise ValueError("file escapes repository")
    return target.read_bytes()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate field: {key}")
        result[key] = value
    return result


def parse_semantic_declarations(
    root: Path,
    canonical_paths: Iterable[str],
    inventory: SemanticCoverageResult,
) -> SemanticDeclarationResult:
    """Fail the entire supplied batch closed on malformed/ambiguous input.

    Inventory establishes exact structural identity only, never semantic meaning.
    No missing values or NONE/NOT_APPLICABLE assertions are synthesized.
    Rebuilding hashes the Canon and evidence bytes so edits enter drift evidence.
    """
    root = Path(root).resolve()
    links = []
    errors = []
    digest = sha256()
    seen = set()
    paths = tuple(sorted(canonical_paths))
    if len(set(paths)) != len(paths):
        errors.append("duplicate canonical source input")
    identities = {
        (record.file, record.code_subject,
         "FILE" if record.inventory_kind == "MODULE" else "SYMBOL")
        for record in inventory.records
    }
    # Successful coverage carries an explanatory (non-error) uncertainty string.
    # Availability/completeness/freshness, rather than that prose, are the gate.
    inventory_valid = (
        inventory.status is CodeIntelligenceStatus.OK and inventory.fresh
        and inventory.completeness is not None and inventory.completeness.complete
    )
    digest.update(inventory.index_revision.encode())
    fields = {"source", "subject", "subject_kind", "claim_kind", "evidence",
              *REQUIRED_SEMANTIC_FIELDS}
    for canonical_path in sorted(set(paths)):
        try:
            raw = _read_exact(root, canonical_path)
            text = raw.decode("utf-8")
        except (OSError, UnicodeError, ValueError):
            errors.append(f"{canonical_path}: unreadable or non-exact canonical source")
            continue
        digest.update(json.dumps([canonical_path, text]).encode())
        fence = None
        body = []
        start = 0
        semantic = False
        for number, line in enumerate(text.splitlines(), 1):
            if fence is None:
                match = re.fullmatch(r" {0,3}(`{3,}|~{3,})([^\r\n]*)", line)
                if not match:
                    continue
                fence = match[1]
                info = match[2].strip()
                semantic = info == "foundation-semantic"
                if info.startswith("foundation-semantic") and not semantic:
                    errors.append(f"{canonical_path}:L{number}: invalid semantic fence")
                start, body = number, []
                continue
            if not re.fullmatch(r" {0,3}" + re.escape(fence[0])
                                + "{" + str(len(fence)) + r",}[ \t]*", line):
                body.append(line)
                continue
            fence = None
            if not semantic:
                continue
            locator = f"L{start}-L{number}"
            where = f"{canonical_path}:{locator}"
            try:
                declaration = json.loads("\n".join(body), object_pairs_hook=_unique_object)
                if not isinstance(declaration, dict) or set(declaration) != fields:
                    raise ValueError("missing or unknown declaration fields")
                for name in sorted(fields - {"evidence"}):
                    value = declaration[name]
                    if not isinstance(value, str) or not value.strip():
                        raise ValueError(f"missing or invalid field: {name}")
                source = declaration["source"]
                subject = declaration["subject"]
                kind = CodeIntelligenceSubjectKind(declaration["subject_kind"])
                claim = declaration["claim_kind"]
                if claim != claim.strip():
                    raise ValueError("non-exact claim_kind")
                _read_exact(root, source)
                if not inventory_valid:
                    raise ValueError("source inventory is stale or incomplete")
                if (source, subject, kind.value) not in identities:
                    raise ValueError("source/subject/subject_kind identity mismatch")
                identity = (source, subject, kind)
                if identity in seen:
                    raise ValueError("duplicate semantic obligation")
                seen.add(identity)
                evidence = declaration["evidence"]
                if not isinstance(evidence, list) or any(
                    not isinstance(ref, str) for ref in evidence
                ):
                    raise ValueError("evidence must be a list of exact file paths")
                if len(set(evidence)) != len(evidence):
                    raise ValueError("duplicate evidence reference")
                for ref in evidence:
                    content = _read_exact(root, ref)
                    digest.update(json.dumps([ref, sha256(content).hexdigest()]).encode())
                links.append(SemanticLink(
                    canonical_reference=CanonicalReference(canonical_path, locator, claim),
                    code_subject=subject,
                    subject_kind=kind,
                    evidence_refs=tuple(evidence),
                    provenance=f"foundation-semantic:{where}",
                    **{name: declaration[name] for name in REQUIRED_SEMANTIC_FIELDS},
                ))
            except (ValueError, OSError, RecursionError) as exc:
                # Never copy file contents or OS error paths into diagnostics.
                reason = str(exc) if isinstance(exc, ValueError) else "unreadable declaration reference"
                errors.append(f"{where}: {reason}")
        if fence is not None and semantic:
            errors.append(f"{canonical_path}:L{start}: unclosed semantic fence")
    stable_errors = tuple(sorted(set(errors)))
    digest.update(json.dumps(stable_errors).encode())
    return SemanticDeclarationResult(
        links=() if stable_errors else tuple(links),
        errors=stable_errors,
        revision=digest.hexdigest(),
    )
