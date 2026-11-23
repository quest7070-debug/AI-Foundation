"""Read-only blob-level reconciliation of the 52 closed PR heads against main.

Uses existing GitHub CLI authentication, no model/Guard/9B or local source writes.
Blob equality is evidence, never proof of semantic equivalence.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

ROW = re.compile(r"^\| \[#([0-9]+)\]\([^)]*\) \| `([0-9a-f]{40})` \| `([A-Z_]+)` \|$", re.M)
REPO = "quest7070-dev/AI-Foundation"


def gh_json(path):
    result = subprocess.run(
        ["gh", "api", path], check=True, text=True,
        capture_output=True, timeout=90,
    )
    return json.loads(result.stdout)


def manifest_rows(text):
    rows = [(int(n), sha, status) for n, sha, status in ROW.findall(text)]
    if len(rows) != 52 or len({n for n, _, _ in rows}) != 52:
        raise ValueError("EXPECTED_52_UNIQUE_ORIGINAL_HEADS")
    return rows


def blobs(commit):
    # Frozen PR HEADs are commit SHAs, not necessarily tree object IDs.
    # Resolve the immutable commit's actual tree before the Git Trees API.
    commit_data = gh_json(f"repos/{REPO}/git/commits/{commit}")
    tree_sha = commit_data.get("tree", {}).get("sha")
    if type(tree_sha) is not str or re.fullmatch(r"[0-9a-f]{40}", tree_sha) is None:
        raise ValueError("COMMIT_TREE_UNVERIFIED")
    response = gh_json(f"repos/{REPO}/git/trees/{tree_sha}?recursive=1")
    if response.get("truncated") is not False or not isinstance(response.get("tree"), list):
        raise ValueError("GITHUB_TREE_COVERAGE_UNVERIFIED")
    return {item["path"]: item["sha"] for item in response["tree"]
            if item.get("type") == "blob" and isinstance(item.get("path"), str)
            and isinstance(item.get("sha"), str)}


def original_change_scope(number, head):
    """Inspect only files changed by this original PR, not its entire old tree.

    Comparing entire old trees makes unrelated newer main changes appear as
    dropped PR features. Require the immutable manifest HEAD to still match
    GitHub's PR HEAD, and exhaust its changed-file pagination.
    """
    meta = gh_json(f"repos/{REPO}/pulls/{number}")
    count = meta.get("changed_files")
    if (meta.get("head", {}).get("sha") != head
            or type(count) is not int or not 0 <= count <= 3000):
        raise ValueError("ORIGINAL_PR_CHANGE_SCOPE_UNVERIFIED")
    paths, deleted, renamed_previous = [], [], []
    total = 0
    for page in range(1, 32):
        batch = gh_json(f"repos/{REPO}/pulls/{number}/files?per_page=100&page={page}")
        if not isinstance(batch, list) or not 0 < len(batch) <= 100:
            raise ValueError("ORIGINAL_PR_FILES_INCOMPLETE")
        total += len(batch)
        for item in batch:
            name = item.get("filename")
            status = item.get("status")
            if (type(name) is not str or not name or
                    status not in ("added", "modified", "removed", "renamed",
                                   "copied", "changed", "unchanged")):
                raise ValueError("ORIGINAL_PR_FILE_INVALID")
            (deleted if status == "removed" else paths).append(name)
            if status == "renamed":
                previous = item.get("previous_filename")
                if (type(previous) is not str or not previous
                        or previous.startswith("/") or "\x00" in previous):
                    raise ValueError("ORIGINAL_PR_RENAME_PATH_UNVERIFIED")
                renamed_previous.append(previous)
        if total == count:
            break
        if total > count or len(batch) != 100:
            raise ValueError("ORIGINAL_PR_FILES_INCOMPLETE")
    if total != count or len(set(paths + deleted)) != total:
        raise ValueError("ORIGINAL_PR_FILES_INCOMPLETE")
    return {
        "paths": tuple(sorted(paths)),
        "removed_paths": tuple(sorted(deleted)),
        "renamed_previous_paths": tuple(sorted(renamed_previous)),
    }


def reconcile(rows, main_tree, get_tree=blobs, get_changed_paths=original_change_scope):
    output = []
    for number, head, disposition in rows:
        original = get_tree(head)
        scope = get_changed_paths(number, head)
        paths = scope["paths"]
        if any(path not in original for path in paths):
            raise ValueError("PINNED_PR_CHANGED_FILE_MISSING")
        missing = sorted(path for path in paths if path not in main_tree)
        different = sorted(path for path in paths if path in main_tree
                           and main_tree[path] != original[path])
        identical = sum(main_tree.get(path) == original[path] for path in paths)
        output.append({
            "pr": number, "head": head, "disposition": disposition,
            "scope": "ORIGINAL_PR_CHANGED_PATHS",
            "changed_path_count": len(paths),
            "original_removed_path_count": len(scope["removed_paths"]),
            "original_removed_paths": scope["removed_paths"],
            "renamed_previous_paths": scope.get("renamed_previous_paths", ()),
            "missing_paths": missing, "different_blob_paths": different,
            "identical_blob_count": identical,
            "status": ("REQUIRES_SEMANTIC_REVIEW" if missing or different
                       or scope["removed_paths"] or scope.get("renamed_previous_paths")
                       else "SCOPED_BLOB_IDENTITY_ONLY"),
        })
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="docs/PR_CONSOLIDATION_20261112.md")
    parser.add_argument("--output", help="Optional JSON output; default stdout only")
    args = parser.parse_args()
    rows = manifest_rows(Path(args.manifest).read_text(encoding="utf-8"))
    main_sha = gh_json(f"repos/{REPO}/git/ref/heads/main")["object"]["sha"]
    result = {"schema": "closed-pr-blob-audit/v2", "main_sha": main_sha,
              "coverage": len(rows), "semantic_equivalence_proven": False,
              "prs": reconcile(rows, blobs(main_sha))}
    serialized = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(serialized, encoding="utf-8")
    else:
        print(serialized, end="")


if __name__ == "__main__":
    main()
