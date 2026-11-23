from pathlib import Path
import os
import plistlib
from unittest.mock import patch
import subprocess
import sys

from scripts import m1_llama_swap_upgrade as probe


def test_gguf_header_rejects_fifo_without_waiting_for_writer(tmp_path):
    fifo = tmp_path / "model.gguf"
    os.mkfifo(fifo)
    result = subprocess.run(
        [sys.executable, "-c",
         "from scripts.m1_llama_swap_upgrade import gguf_header_plausible; "
         "import sys; assert gguf_header_plausible(sys.argv[1]) is False",
         str(fifo)],
        cwd=Path(__file__).resolve().parents[1], capture_output=True,
        text=True, timeout=5, check=False,
    )
    assert result.returncode == 0, result.stderr


def test_owner_llama_swap_audit_is_only_fixed_counts_no_paths(tmp_path):
    home = tmp_path
    binary = home / "llama-swap"
    brew = home / "brew"
    binary.write_bytes(b"fake")
    brew.write_bytes(b"fake")
    manifest = home / probe.RELATIVE_MANIFEST
    manifest.parent.mkdir(parents=True)
    model = home / "private-model.gguf"
    model.write_bytes(b"fake model")
    manifest.write_text("models:\n  local-general:\n    cmd: llama-server --model " + str(model) + "\n")
    plist = home / "Library/LaunchAgents" / (probe.OWNER_LABEL + ".plist")
    plist.parent.mkdir(parents=True)
    plist.write_bytes(plistlib.dumps({"Label": probe.OWNER_LABEL,
                                      "ProgramArguments": [str(binary), "--config", str(manifest)]}))
    commands = []
    def version(argv):
        commands.append(argv)
        if argv[0] == str(binary):
            return "llama-swap version v271"
        return "llama-swap 271"
    with patch("scripts.m1_development_bridge.require_m1"), \
         patch.object(probe, "EXECUTABLE", binary), patch.object(probe, "HOMEBREW", brew):
        result = probe.audit(home=home, inspect_version=version)
    assert result["status"] == "UPGRADE_AUDIT"
    assert result["installed_version"] == "v271"
    assert result["declared_model_paths"] == result["artifact_found"] == 1
    assert result["ready_for_fixed_upgrade"]
    assert result["model_calls"] == result["service_mutations"] == 0
    assert len(commands) == 2
    assert str(home) not in str(result)
    plist.write_bytes(plistlib.dumps({"Label": "other",
                                      "ProgramArguments": [str(binary), "--config", str(manifest)]}))
    with patch("scripts.m1_development_bridge.require_m1"), patch.object(probe, "EXECUTABLE", binary):
        assert probe.audit(home=home)["status"] == "PLIST_UNVERIFIED"


def test_exact_v256_to_v272_package_only_no_runtime_mutation():
    before = {"ready_for_fixed_upgrade": True, "installed_version": "v256",
              "brew_formula_version": "256", "declared_model_paths": 4}
    after = {"ready_for_fixed_upgrade": True, "installed_version": "v272",
             "brew_formula_version": "272", "declared_model_paths": 4,
             "artifact_missing": 4}
    calls = []
    def brew(args, *, timeout):
        calls.append(tuple(args))
        return True
    def formula(args, *, max_bytes=500):
        assert args[1:] == ["cat", "mostlygeek/llama-swap/llama-swap"]
        return 'version "272"\nsha256 "' + probe.LATEST_ARM64_SHA256 + '"'
    with patch.object(probe, "audit", side_effect=[before, after]), \
         patch.object(probe, "_brew", side_effect=brew), \
         patch.object(probe, "fixed_command", side_effect=formula):
        value = probe.stage_v272_binary()
    assert value["status"] == "V272_BINARY_INSTALLED_LIVE_UNVERIFIED"
    assert value["missing_model_paths"] == 4
    assert value["model_calls"] == value["model_process_stops"] == value["launchd_restarts"] == 0
    assert calls == [("update", "--quiet"), ("upgrade", "mostlygeek/llama-swap/llama-swap")]


def test_changed_package_or_formula_fails_before_upgrade():
    before = {"ready_for_fixed_upgrade": True, "installed_version": "v256",
              "brew_formula_version": "256", "declared_model_paths": 4}
    with patch.object(probe, "audit", return_value=before), \
         patch.object(probe, "_brew", return_value=True) as brew, \
         patch.object(probe, "fixed_command", return_value='version "273"'):
        assert probe.stage_v272_binary()["status"] == "REVIEWED_V272_FORMULA_NOT_FOUND"
    brew.assert_called_once_with(["update", "--quiet"], timeout=210)
    with patch.object(probe, "audit", return_value={
            **before, "installed_version": "v257"}), \
         patch.object(probe, "_brew") as brew:
        assert probe.stage_v272_binary()["status"] == "UPGRADE_BASE_VERSION_CHANGED"
        brew.assert_not_called()

def test_model_origin_classes_refuse_guesswork(tmp_path):
    home = tmp_path
    artifacts = {
        "owner": home / "models" / "missing.gguf",
        "volume": Path("/Volumes/NonexistentOwnerTestVolume/models/missing.gguf"),
        "system": Path("/opt/unknown_models/missing.gguf"),
    }
    value = probe._artifact_roots(artifacts, home)
    assert value["configured_path_classes"] == {
        "CURRENT_HOME": 1, "OTHER_USER_HOME": 0,
        "REMOVABLE_VOLUME": 1, "OTHER_ABSOLUTE": 1}
    assert value["resolution_granted"] is False
    assert value["same_suffix_existing_owner_files"] == 0
    assert str(home) not in str(value)


def test_brew_retained_prior_keg_never_hides_live_binary_version(tmp_path):
    binary = tmp_path / "llama-swap"
    brew = tmp_path / "brew"
    binary.write_bytes(b"fake")
    brew.write_bytes(b"fake")
    manifest = tmp_path / probe.RELATIVE_MANIFEST
    manifest.parent.mkdir(parents=True)
    manifest.write_text("models: {}")
    plist = tmp_path / "Library/LaunchAgents" / (probe.OWNER_LABEL + ".plist")
    plist.parent.mkdir(parents=True)
    plist.write_bytes(plistlib.dumps({
        "Label": probe.OWNER_LABEL, "ProgramArguments":
        [str(binary), "--config", str(manifest)]}))
    def command(args):
        return "llama-swap v272" if args[0] == str(binary) else "llama-swap 256 272"
    with patch("scripts.m1_development_bridge.require_m1"), \
         patch.object(probe, "EXECUTABLE", binary), patch.object(probe, "HOMEBREW", brew):
        result = probe.audit(home=tmp_path, inspect_version=command)
    assert result["brew_managed"] is True
    assert result["installed_version"] == "v272"
    assert result["brew_formula_version"] == "272"
    assert result["ready_for_fixed_upgrade"] is True

def test_runtime_version_uses_only_local_read_only_api():
    from unittest.mock import MagicMock
    connection = MagicMock()
    connection.getresponse.return_value.status = 200
    connection.getresponse.return_value.read.return_value = b'{"version":"256","secret":"PRIVATE_TOKEN"}'
    with patch("http.client.HTTPConnection", return_value=connection) as cli:
        assert probe._running_version() == "v256"
    cli.assert_called_once_with("127.0.0.1", 9292, timeout=3)
    connection.request.assert_called_once_with(
        "GET", "/api/version",
        headers={"Host": "127.0.0.1", "Accept": "application/json"})
    connection.close.assert_called_once()
    connection.getresponse.return_value.read.return_value = b'{"version":"PRIVATE_TOKEN"}'
    with patch("http.client.HTTPConnection", return_value=connection):
        assert probe._running_version() == "UNVERIFIED"


def test_runtime_cutover_never_restarts_with_missing_model_bytes():
    good = {
        "ready_for_fixed_upgrade": True, "installed_version": "v272",
        "brew_formula_version": "272", "live_runtime_version": "v256",
        "declared_model_paths": 4, "artifact_missing": 4,
        "artifact_found": 0, "artifact_parents_existing": 0,
        "artifact_symlinks": 0, "all_declared_absolute": True,
        "gguf_headers_plausible": 0,
    }
    blocked = probe.runtime_cutover_preconditions(good)
    assert blocked == {"status": "BLOCKED", "reason": "MODEL_ARTIFACTS_MISSING",
                       "runtime_restart_authorized": False}
    # Even once the original files are restored, source-only evidence is
    # never permission to evict a model or restart the loaded service.
    restored = {**good, "artifact_missing": 0, "artifact_found": 4,
                "artifact_parents_existing": 4, "gguf_headers_plausible": 4}
    placeholder = probe.runtime_cutover_preconditions({
        **restored, "gguf_headers_plausible": 3})
    assert placeholder == {"status": "BLOCKED",
                           "reason": "MODEL_GGUF_HEADER_UNVERIFIED",
                           "runtime_restart_authorized": False}
    # Even a plausible header + 1 MiB synthetic payload does not prove
    # that the four original model weights were restored.
    plausible = probe.runtime_cutover_preconditions(restored)
    assert plausible == {"status": "BLOCKED",
                         "reason": "MODEL_ORIGINAL_IDENTITY_UNVERIFIED",
                         "runtime_restart_authorized": False}
    assert probe.runtime_cutover_preconditions({
        **restored, "live_runtime_version": "UNVERIFIED"
    })["reason"] == "LIVE_PROCESS_VERSION_UNVERIFIED"


def test_gguf_header_preflight_rejects_stubs_and_only_reads_bounded_prefix(tmp_path):
    # No model load or inference. A plausible prefix is not provenance proof.
    artifact = tmp_path / "fixture.gguf"
    header = (b"GGUF" + (3).to_bytes(4, "little")
              + (12).to_bytes(8, "little") + (1).to_bytes(8, "little"))
    artifact.write_bytes(header)
    assert probe.gguf_header_plausible(artifact) is False  # truncated stub
    with artifact.open("r+b") as fp:
        fp.truncate(1024 * 1024)
    assert probe.gguf_header_plausible(artifact) is True
    artifact.write_bytes(b"FAKE" + header[4:])
    with artifact.open("r+b") as fp:
        fp.truncate(1024 * 1024)
    assert probe.gguf_header_plausible(artifact) is False
    artifact.unlink()
    artifact.symlink_to(tmp_path / "missing.gguf")
    assert probe.gguf_header_plausible(artifact) is False

