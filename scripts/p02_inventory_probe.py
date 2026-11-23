"""Read-only P02 multi-language inventory probe for a pinned Infigraph binary.

The only writes are the derived .infigraph index and a private receipt outside
the worktree. Source files, Git refs, provider state and credentials are not
modified or passed to a model.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from ai_foundation.code_intelligence import CodeIntelligenceStatus
from ai_foundation.composite_code_intelligence import CompositeCodeIntelligence
from ai_foundation.infigraph_adapter import InfigraphCodeIntelligence
from ai_foundation.libcst_adapter import LibCSTCodeIntelligence
from ai_foundation.semantic_linker import FoundationSemanticLinker


def _summary(coverage) -> tuple[dict, str]:
    completeness = coverage.completeness
    records = coverage.records
    kinds = Counter(item.inventory_kind for item in records)
    report = {
        "status": (
            "COMPLETE"
            if coverage.status is CodeIntelligenceStatus.OK
            and completeness is not None
            and completeness.complete
            else "PARTIAL"
        ),
        "backend": coverage.backend,
        "backend_version": coverage.backend_version,
        "index_revision": coverage.index_revision,
        "fresh": coverage.fresh,
        "expected_files": None if completeness is None else completeness.expected_files,
        "analyzed_files": None if completeness is None else completeness.analyzed_files,
        "inventory_complete": (
            False if completeness is None else completeness.inventory_complete
        ),
        "fallback_files": (
            [] if completeness is None else list(completeness.fallback_files)
        ),
        "unaccounted_files": (
            [] if completeness is None else list(completeness.unaccounted_files)
        ),
        "failed_files": [] if completeness is None else list(completeness.failed_files),
        "unresolved_observations": (
            None if completeness is None else completeness.unresolved_observations
        ),
        "inventory_records": len(records),
        "inventory_kinds": dict(sorted(kinds.items())),
    }
    lines = [
        "## P02 multi-language inventory",
        f"Status: **{report['status']}**",
        (
            f"Files: {report['analyzed_files']}/{report['expected_files']} analyzed; "
            f"symbols/files: {report['inventory_records']}; "
            f"unresolved: {report['unresolved_observations']}"
        ),
        "",
        "### Inventory kinds",
    ]
    lines.extend(
        f"- {kind}: {count}" for kind, count in sorted(kinds.items())
    )
    if report["fallback_files"]:
        lines.extend(["", "### Structural fallback paths"])
        lines.extend(f"- `{path}`" for path in report["fallback_files"][:40])
        if len(report["fallback_files"]) > 40:
            lines.append(f"- … {len(report['fallback_files']) - 40} additional paths omitted")
    if report["unaccounted_files"]:
        lines.extend(["", "### Unaccounted paths"])
        lines.extend(f"- `{path}`" for path in report["unaccounted_files"][:40])
        if len(report["unaccounted_files"]) > 40:
            lines.append(f"- … {len(report['unaccounted_files']) - 40} additional paths omitted")
    if report["failed_files"]:
        lines.extend(["", "### Explicit analysis failures"])
        lines.extend(f"- `{path}`" for path in report["failed_files"][:40])
        if len(report["failed_files"]) > 40:
            lines.append(f"- … {len(report['failed_files']) - 40} additional paths omitted")
    return report, "\n".join(lines) + "\n"



def _source_metadata(root: Path) -> dict[str, tuple[int, int]] | None:
    """Safe P02 diagnostics, not authority: hashed path IDs and file stat only.

    Match the adapter's tracked+untracked, exclude-standard path selection.
    No filenames, file contents, credentials or raw git output are logged.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others",
             "--exclude-standard", "-z"],
            cwd=root, capture_output=True, timeout=20, check=True,
        )
        if len(result.stdout) > 8_000_000:
            return None
        manifest = {}
        for raw in result.stdout.split(b"\0"):
            if not raw or raw == b".infigraph" or raw.startswith(b".infigraph/"):
                continue
            if len(manifest) >= 30_000:
                return None
            name = raw.decode("utf-8", "surrogateescape")
            path_key = hashlib.sha256(raw).hexdigest()[:16]
            try:
                meta = (root / name).stat()
                manifest[path_key] = (meta.st_size, meta.st_mtime_ns)
            except FileNotFoundError:
                manifest[path_key] = (-1, -1)
        return manifest
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _source_metadata_delta(before, after):
    if before is None or after is None:
        return {"status": "DIAGNOSTIC_UNAVAILABLE"}
    old, new = set(before), set(after)
    changed = sorted(key for key in old & new if before[key] != after[key])
    return {
        "status": "METADATA_ONLY",
        "added_count": len(new - old),
        "removed_count": len(old - new),
        "size_or_mtime_changed_count": len(changed),
        "added_path_hashes": sorted(new - old)[:12],
        "removed_path_hashes": sorted(old - new)[:12],
        "changed_path_hashes": changed[:12],
    }



def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--infigraph-bin", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args()

    root = args.repo.resolve()
    receipt = args.receipt.resolve()
    if receipt.is_relative_to(root):
        print("receipt must be outside the worktree", file=sys.stderr)
        return 2

    structural = InfigraphCodeIntelligence(
        executable=args.infigraph_bin,
        root=root,
        index_receipt=receipt,
        timeout_seconds=120.0,
    )
    before = _source_metadata(root)
    refreshed = structural.refresh()
    if refreshed.status is not CodeIntelligenceStatus.OK or not refreshed.fresh:
        failure = {
            "status": "UNAVAILABLE",
            "uncertainty": refreshed.uncertainty,
        }
        if refreshed.uncertainty == "source identity changed during explicit refresh":
            failure["source_change_metadata"] = _source_metadata_delta(
                before, _source_metadata(root))
        print(json.dumps(failure, ensure_ascii=False, indent=2))
        return 2

    composite = CompositeCodeIntelligence(
        structural=structural,
        scoped_names=LibCSTCodeIntelligence(root=root),
    )
    coverage = FoundationSemanticLinker(composite).repository_coverage()
    report, markdown = _summary(coverage)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        with args.summary.open("a", encoding="utf-8") as stream:
            stream.write(markdown)

    # A PARTIAL inventory is an expected diagnostic result, not a green gate.
    # This probe fails only when the backend/receipt/freshness path is unavailable.
    if not coverage.fresh or coverage.completeness is None:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
