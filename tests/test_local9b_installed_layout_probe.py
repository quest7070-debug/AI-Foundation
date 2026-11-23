"""Fixed M1 installed-worker layout inspection: no scripts are executed."""
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from local9b_installed_layout_probe import inspect_worker_layout


def _create(base, *, modules=True, results=True, source=None):
    root = Path(base)
    worker = root / "worker.py"
    worker.write_text(
        source if source is not None else
        'from pathlib import Path\nROOT=Path(__file__).resolve().parent\n'
        'if __name__=="__main__":\n  raise AssertionError("must never execute")\n',
        encoding="utf-8")
    worker.chmod(0o600)
    (root / "inbox").mkdir()
    if results:
        (root / "results").mkdir()
    if modules:
        target = root / "modules" / "ai_foundation"
        target.mkdir(parents=True)
        for file in ("development_host.py", "development_loop.py",
                     "host_compute_lease.py"):
            (target / file).write_text("raise AssertionError('never import')\n")
            (target / file).chmod(0o600)
    return worker


def test_known_layout_is_observed_without_import_or_execution():
    with tempfile.TemporaryDirectory() as folder:
        worker = _create(folder)
        result = inspect_worker_layout(worker)
        assert result["status"] == "STRUCTURE_OBSERVED"
        assert result["root_contract"] == "LEGACY_SINGLE_ROOT"
        assert all(v == "PRESENT" for v in result["entries"].values())
        assert result["model_invoked"] is False
        assert result["filesystem_modified"] is False


def test_missing_results_and_modules_are_independently_classified():
    with tempfile.TemporaryDirectory() as folder:
        worker = _create(folder, modules=False, results=False)
        result = inspect_worker_layout(worker)
        assert result["status"] == "LAYOUT_BLOCKED"
        assert result["entries"]["inbox"] == "PRESENT"
        assert result["entries"]["results"] == "MISSING"
        assert result["entries"]["development_host.py"] == "MISSING"
        assert result["entries"]["host_compute_lease.py"] == "MISSING"


def test_unknown_runtime_root_does_not_guess_worker_data_directory():
    with tempfile.TemporaryDirectory() as folder:
        worker = _create(folder, source="ROOT='/other/data'\n")
        result = inspect_worker_layout(worker)
        assert result["root_contract"] == "WORKER_ROOT_UNKNOWN"
        assert result["status"] == "LAYOUT_BLOCKED"


def test_wrong_type_and_symlink_cannot_be_interpreted_as_valid_results():
    with tempfile.TemporaryDirectory() as folder:
        worker = _create(folder, results=False)
        (Path(folder) / "results").write_text("not a directory")
        result = inspect_worker_layout(worker)
        assert result["entries"]["results"] == "UNTRUSTED_OR_WRONG_TYPE"
        (Path(folder) / "results").unlink()
        (Path(folder) / "results").symlink_to(Path(folder) / "inbox")
        result = inspect_worker_layout(worker)
        assert result["entries"]["results"] == "UNTRUSTED_SYMLINK"



def test_p4_worker_uses_original_state_root_not_versioned_release_code_dir():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        code = root / "release" / "scripts"
        code.mkdir(parents=True)
        worker = code / "worker.py"
        worker.write_text(
            "from local9b_worker_paths import configure_worker_paths\n"
            'ROOT=configure_worker_paths(__file__,state_root=os.environ.get("AI_FOUNDATION_LOCAL9B_STATE_ROOT"))\n')
        worker.chmod(0o600)
        (code / "local9b_worker_paths.py").write_text("pass\n")
        package = root / "release" / "src" / "ai_foundation"
        package.mkdir(parents=True)
        for name in ("development_host.py", "development_loop.py",
                     "host_compute_lease.py"):
            (package / name).write_text("pass\n")
        state = root / "original-owner-queue"
        (state / "inbox").mkdir(parents=True)
        (state / "results").mkdir()
        result = inspect_worker_layout(worker, state_root=state)
        assert result["status"] == "STRUCTURE_OBSERVED"
        assert result["root_contract"] == "P4_SEPARATE_STATE_ROOT"
        assert result["code_state_separated"] is True
        assert result["entries"]["results"] == "PRESENT"
        assert result["entries"]["source_package"] == "PRESENT"
        # A missing module directory next to the versioned script is expected.
        assert not (code / "modules").exists()
        (state / "results").rmdir()
        result = inspect_worker_layout(worker, state_root=state)
        assert result["status"] == "LAYOUT_BLOCKED"
        assert result["entries"]["results"] == "MISSING"


def test_p4_worker_refuses_to_guess_state_root_from_code_path():
    with tempfile.TemporaryDirectory() as folder:
        worker = Path(folder) / "worker.py"
        worker.write_text(
            'ROOT=configure_worker_paths(__file__,state_root=os.environ.get("AI_FOUNDATION_LOCAL9B_STATE_ROOT"))\n')
        worker.chmod(0o600)
        import pytest
        with pytest.raises(ValueError, match="P4_STATE_ROOT_UNBOUND"):
            inspect_worker_layout(worker)
