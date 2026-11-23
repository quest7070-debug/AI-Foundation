"""No-network audit contract: distinguish identical, missing and changed blobs."""
from pathlib import Path

import pytest

from scripts.closed_pr_blob_audit import (
    reconcile, manifest_rows, blobs, original_change_scope,
)


def test_reconcile_does_not_claim_semantic_equivalence():
    rows = [(607, "a" * 40, "PORT_SOURCE_ONLY")]
    main = {"a.py": "same", "b.py": "new", "unrelated.py": "later"}
    old = {"a.py": "same", "b.py": "old", "c.py": "lost",
           "unrelated.py": "early"}
    scope = lambda number, head: {
        "paths": ("a.py", "b.py", "c.py"), "removed_paths": (),
    }
    result = reconcile(rows, main, get_tree=lambda _: old,
                       get_changed_paths=scope)[0]
    assert result["identical_blob_count"] == 1
    assert result["missing_paths"] == ["c.py"]
    assert result["different_blob_paths"] == ["b.py"]
    assert result["status"] == "REQUIRES_SEMANTIC_REVIEW"
    # A changed file outside the original PR is not PR feature debt.
    assert "unrelated.py" not in result["different_blob_paths"]
    assert result["scope"] == "ORIGINAL_PR_CHANGED_PATHS"


def test_manifest_parser_recognizes_all_52_original_frozen_heads():
    rows = "\n".join(
        f"| [#{n}](https://github.com/quest7070-dev/AI-Foundation/pull/{n}) "
        f"| `{n:040x}` | `SUPERSEDED_BY_MAIN` |"
        for n in range(1, 53)
    )
    parsed = manifest_rows(rows)
    assert len(parsed) == 52
    assert parsed[0] == (1, f"{1:040x}", "SUPERSEDED_BY_MAIN")
    assert parsed[-1] == (52, f"{52:040x}", "SUPERSEDED_BY_MAIN")


def test_checked_in_consolidation_manifest_has_exactly_52_pinned_heads():
    manifest = (Path(__file__).resolve().parents[1] /
                "docs" / "PR_CONSOLIDATION_20261112.md")
    original = manifest_rows(manifest.read_text(encoding="utf-8"))
    assert len(original) == 52
    assert len({n for n, _, _ in original}) == 52


def test_blob_audit_dereferences_commit_sha_without_guessing_tree(monkeypatch):
    seen = []

    def api(path):
        seen.append(path)
        if "/git/commits/" in path:
            return {"tree": {"sha": "b" * 40}}
        assert path.endswith("/git/trees/" + "b" * 40 + "?recursive=1")
        return {"truncated": False, "tree": [
            {"path": "src/owned.py", "type": "blob", "sha": "c" * 40},
        ]}

    monkeypatch.setattr("scripts.closed_pr_blob_audit.gh_json", api)
    assert blobs("a" * 40) == {"src/owned.py": "c" * 40}
    assert seen[0].endswith("/git/commits/" + "a" * 40)


def test_original_change_scope_exhausts_pages_and_checks_frozen_head(monkeypatch):
    head = "a" * 40
    calls = []

    def api(path):
        calls.append(path)
        if path.endswith("/pulls/607"):
            return {"head": {"sha": head}, "changed_files": 101}
        if path.endswith("page=1"):
            return [{"filename": f"src/f{i}.py", "status": "modified"}
                    for i in range(100)]
        if path.endswith("page=2"):
            return [{"filename": "src/f100.py", "status": "renamed",
                     "previous_filename": "src/old100.py"}]
        raise AssertionError(path)

    monkeypatch.setattr("scripts.closed_pr_blob_audit.gh_json", api)
    scope = original_change_scope(607, head)
    assert len(scope["paths"]) == 101
    assert scope["removed_paths"] == ()
    assert scope["renamed_previous_paths"] == ("src/old100.py",)
    assert len(calls) == 3
    with pytest.raises(ValueError, match="ORIGINAL_PR_CHANGE_SCOPE_UNVERIFIED"):
        original_change_scope(607, "b" * 40)


def test_deleted_original_path_does_not_create_false_complete_audit():
    rows = [(81, "a" * 40, "EXPERIMENT_REQUIRES_SEPARATE_ACCEPTANCE")]
    scope = lambda number, head: {
        "paths": (), "removed_paths": ("src/removed.py",),
    }
    result = reconcile(rows, {}, get_tree=lambda _: {},
                       get_changed_paths=scope)[0]
    assert result["original_removed_path_count"] == 1
    assert result["original_removed_paths"] == ("src/removed.py",)
    assert result["status"] == "REQUIRES_SEMANTIC_REVIEW"


def test_renamed_original_path_requires_semantic_review():
    rows = [(607, "a" * 40, "PORT_SOURCE_ONLY")]
    scope = lambda number, head: {
        "paths": ("src/new.py",), "removed_paths": (),
        "renamed_previous_paths": ("src/old.py",),
    }
    result = reconcile(rows, {"src/new.py": "same"},
                       get_tree=lambda _: {"src/new.py": "same"},
                       get_changed_paths=scope)[0]
    assert result["missing_paths"] == []
    assert result["renamed_previous_paths"] == ("src/old.py",)
    assert result["status"] == "REQUIRES_SEMANTIC_REVIEW"
