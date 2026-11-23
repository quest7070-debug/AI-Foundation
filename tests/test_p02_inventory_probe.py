from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from ai_foundation.code_intelligence import CodeIntelligenceStatus
from scripts.p02_inventory_probe import _summary, _source_metadata, _source_metadata_delta


def test_summary_distinguishes_structural_fallback_from_unaccounted_paths():
    completeness = SimpleNamespace(
        expected_files=5,
        analyzed_files=3,
        failed_files=("src/broken.py: parser failed",),
        unresolved_observations=1,
        fallback_files=("src/native.rs",),
        unaccounted_files=("src/unknown.bin",),
        inventory_complete=False,
        complete=False,
    )
    coverage = SimpleNamespace(
        status=CodeIntelligenceStatus.UNKNOWN,
        completeness=completeness,
        records=(
            SimpleNamespace(inventory_kind="FILE"),
            SimpleNamespace(inventory_kind="FUNCTION"),
        ),
        backend="infigraph+libcst",
        backend_version="3.2.16+1.9.0",
        index_revision="index:123",
        fresh=True,
    )

    report, markdown = _summary(coverage)

    assert report["status"] == "PARTIAL"
    assert report["inventory_complete"] is False
    assert report["fallback_files"] == ["src/native.rs"]
    assert report["unaccounted_files"] == ["src/unknown.bin"]
    assert report["failed_files"] == ["src/broken.py: parser failed"]
    assert "Structural fallback paths" in markdown
    assert "Unaccounted paths" in markdown
    assert "Explicit analysis failures" in markdown


def test_summary_reports_complete_inventory_without_fabricating_gaps():
    completeness = SimpleNamespace(
        expected_files=2,
        analyzed_files=2,
        failed_files=(),
        unresolved_observations=0,
        fallback_files=(),
        unaccounted_files=(),
        inventory_complete=True,
        complete=True,
    )
    coverage = SimpleNamespace(
        status=CodeIntelligenceStatus.OK,
        completeness=completeness,
        records=(),
        backend="infigraph+libcst",
        backend_version="3.2.16+1.9.0",
        index_revision="index:456",
        fresh=True,
    )

    report, markdown = _summary(coverage)

    assert report["status"] == "COMPLETE"
    assert report["inventory_complete"] is True
    assert report["fallback_files"] == []
    assert report["unaccounted_files"] == []
    assert "Structural fallback paths" not in markdown
    assert "Unaccounted paths" not in markdown


def test_inventory_workflow_guards_persistent_m1_runner_and_tracks_fallback_parser():
    workflow = Path(".github/workflows/p02-multilang-inventory.yml").read_text(
        encoding="utf-8"
    )
    assert (
        "if: github.event_name != 'pull_request' || ("
        "github.event.pull_request.head.repo.full_name == github.repository && "
        "github.event.pull_request.user.login == 'quest7070-debug')"
    ) in workflow
    assert workflow.count('"src/ai_foundation/configuration_inventory.py"') == 2
    assert workflow.count('"src/ai_foundation/infigraph_receipt.py"') == 2
    assert workflow.count('"src/ai_foundation/code_intelligence.py"') == 2



def test_configuration_inventory_accounts_for_legacy_unified_patch_headers():
    from ai_foundation.configuration_inventory import ConfigurationInventory

    root = Path(__file__).resolve().parents[1]
    result = ConfigurationInventory(root).inspect((
        "deploy/librechat-v0.8.7-foundation-signing.patch",
        "deploy/librechat-v0.8.7-history-recall.patch",
    ))

    assert result.parsed_files == (
        "deploy/librechat-v0.8.7-foundation-signing.patch",
        "deploy/librechat-v0.8.7-history-recall.patch",
    )
    assert result.failed_files == ()
    targets = {
        item.target for item in result.relations
        if item.relation == "PATCH_TARGET_FILE"
    }
    assert "deploy/librechat-v0.8.7-foundation-signing.patch#target:index.cjs" in targets
    assert "deploy/librechat-v0.8.7-history-recall.patch#target:api/server/controllers/agents/client.js" in targets


def test_configuration_inventory_accounts_for_multiple_legacy_patch_sections(tmp_path):
    from ai_foundation.configuration_inventory import ConfigurationInventory

    patch = tmp_path / "multi.patch"
    patch.write_text(
        "--- a/first.txt\t2026-01-01 00:00:00\n"
        "+++ b/first.txt\t2026-01-01 00:00:00\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
        "--- a/second.txt\t2026-01-02 00:00:00\n"
        "+++ b/second.txt\t2026-01-02 00:00:00\n"
        "@@ -1 +1 @@\n"
        "-before\n"
        "+after\n",
        encoding="utf-8",
    )
    result = ConfigurationInventory(tmp_path).inspect(("multi.patch",))

    assert result.parsed_files == ("multi.patch",)
    targets = {
        item.target for item in result.relations
        if item.relation == "PATCH_TARGET_FILE"
    }
    assert "multi.patch#target:first.txt" in targets
    assert "multi.patch#target:second.txt" in targets


def test_inventory_workflow_tracks_completeness_contract_changes():
    workflow_path = (
        Path(__file__).resolve().parents[1]
        / ".github/workflows/p02-multilang-inventory.yml"
    )
    workflow = workflow_path.read_text(encoding="utf-8")
    assert workflow.count('"src/ai_foundation/code_intelligence.py"') == 2


def test_patch_parser_does_not_treat_hunk_content_as_file_headers(tmp_path):
    from ai_foundation.configuration_inventory import ConfigurationInventory

    patch = tmp_path / "header-shaped-content.patch"
    patch.write_text(
        "--- a/first.txt\n"
        "+++ b/first.txt\n"
        "@@ -1 +1 @@\n"
        "--- a/not-a-target.txt\n"
        "+++ b/not-a-target.txt\n"
        "--- a/second.txt\n"
        "+++ b/second.txt\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n",
        encoding="utf-8",
    )
    result = ConfigurationInventory(tmp_path).inspect((patch.name,))

    targets = {
        item.target for item in result.relations
        if item.relation == "PATCH_TARGET_FILE"
    }
    assert targets == {
        f"{patch.name}#target:first.txt",
        f"{patch.name}#target:second.txt",
    }


def test_configuration_inventory_bounds_patch_size_and_recursive_yaml(tmp_path):
    from ai_foundation.configuration_inventory import (
        ConfigurationInventory,
        _MAX_TEXT_BYTES,
    )

    large_patch = tmp_path / "large.patch"
    large_patch.write_bytes(b"x" * (_MAX_TEXT_BYTES + 1))
    recursive_yaml = tmp_path / "recursive.yml"
    recursive_yaml.write_text(
        "root: &root\n  child: *root\n",
        encoding="utf-8",
    )
    deep_yaml = tmp_path / "deep.yml"
    deep_yaml.write_text(
        "".join("  " * depth + f"key{depth}:\n" for depth in range(70))
        + "  " * 70 + "value: leaf\n",
        encoding="utf-8",
    )
    result = ConfigurationInventory(tmp_path).inspect(
        (large_patch.name, recursive_yaml.name, deep_yaml.name)
    )

    assert result.failed_files == ("deep.yml", "large.patch", "recursive.yml")
    assert result.unresolved_observations == 3


def test_configuration_inventory_records_workflow_level_permissions(tmp_path):
    from ai_foundation.configuration_inventory import ConfigurationInventory

    workflow = tmp_path / ".github" / "workflows" / "build.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "name: build\n"
        "permissions:\n"
        "  contents: read\n"
        "jobs:\n"
        "  build:\n"
        "    permissions:\n"
        "      checks: write\n"
        "    steps: []\n",
        encoding="utf-8",
    )
    result = ConfigurationInventory(tmp_path).inspect(
        (".github/workflows/build.yml",)
    )
    permissions = {
        item.target for item in result.relations
        if item.relation == "WORKFLOW_PERMISSION"
    }

    assert ".github/workflows/build.yml#workflow#permission:contents:read" in permissions
    assert ".github/workflows/build.yml#job:build#permission:checks:write" in permissions


def test_configuration_inventory_classifies_native_binary_artifact_extensions(tmp_path):
    from ai_foundation.configuration_inventory import ConfigurationInventory

    names = (
        "signing.pem",
        "certificate.crt",
        "private.key",
        "bundle.p12",
        "bundle.pfx",
        "profile.mobileprovision",
        "module.swiftmodule",
        "module.swiftdoc",
        "shader.metallib",
    )
    for name in names:
        (tmp_path / name).write_bytes(b"binary")
    result = ConfigurationInventory(tmp_path).inspect(names)

    assert result.failed_files == ()
    assert result.parsed_files == tuple(sorted(names))
    assert {
        item.file for item in result.relations if item.relation == "ARTIFACT_FILE"
    } == set(names)


def test_configuration_key_walk_rejects_cycles_and_excessive_depth(tmp_path):
    from ai_foundation.configuration_inventory import ConfigurationInventory

    inventory = ConfigurationInventory(tmp_path)
    recursive = {}
    recursive["self"] = recursive
    with pytest.raises(ValueError, match="recursive"):
        inventory._walk_keys([], "config.json", recursive)

    deeply_nested = {}
    cursor = deeply_nested
    for index in range(66):
        child = {}
        cursor["child"] = child
        cursor = child
    with pytest.raises(ValueError, match="depth bound"):
        inventory._walk_keys([], "config.json", deeply_nested)


def test_source_metadata_diagnoses_changed_untracked_files_without_raw_names(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    private_name = "sensitive-local-untracked-source.py"
    source = tmp_path / private_name
    source.write_text("ONE", encoding="utf-8")
    before = _source_metadata(tmp_path)
    assert before is not None and len(before) == 1

    source.write_text("LONGER VALUE", encoding="utf-8")
    after = _source_metadata(tmp_path)
    delta = _source_metadata_delta(before, after)
    assert delta["status"] == "METADATA_ONLY"
    assert delta["size_or_mtime_changed_count"] == 1
    assert delta["added_count"] == 0
    assert private_name not in str(delta)
    assert "LONGER VALUE" not in str(delta)

    (tmp_path / "second-local-file.py").write_text("x", encoding="utf-8")
    added = _source_metadata_delta(after, _source_metadata(tmp_path))
    assert added["added_count"] == 1
    assert "second-local-file.py" not in str(added)
    assert _source_metadata_delta(None, after) == {
        "status": "DIAGNOSTIC_UNAVAILABLE"
    }


def test_configuration_inventory_tracks_real_p02_unparsed_files_without_values(tmp_path):
    """P02 keeps structural evidence, not invented command/build semantics."""
    from ai_foundation.configuration_inventory import ConfigurationInventory
    paths = (
        "docker/opencode-offline/Dockerfile",
        "scripts/klm_auth_setup.command",
        "docs/evidence/issue222/fork-isolation-test.log",
        "docs/evidence/issue222/offline-tests.log",
    )
    for relative in paths:
        item = tmp_path / relative
        item.parent.mkdir(parents=True, exist_ok=True)
        item.write_text("PRIVATE_SENTINEL_DO_NOT_EXPOSE\n", encoding="utf-8")
    result = ConfigurationInventory(tmp_path).inspect(paths)
    assert result.failed_files == ()
    assert result.unresolved_observations == 0
    assert set(result.parsed_files) == set(paths)
    assert {x.relation for x in result.relations} == {
        "BUILD_FILE_UNPARSED", "SCRIPT_FILE_UNPARSED", "EVIDENCE_LOG_UNPARSED"}
    assert "PRIVATE_SENTINEL_DO_NOT_EXPOSE" not in str(result.relations)


def test_configuration_inventory_does_not_hide_unclassified_source_log(tmp_path):
    from ai_foundation.configuration_inventory import ConfigurationInventory
    (tmp_path / "unknown.log").write_text("not evidence", encoding="utf-8")
    result = ConfigurationInventory(tmp_path).inspect(("unknown.log",))
    assert result.failed_files == ("unknown.log",)
    assert result.unresolved_observations == 1
