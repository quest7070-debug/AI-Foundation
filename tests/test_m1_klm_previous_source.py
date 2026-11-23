"""Resolve a prior deployed stage without granting new release authority."""
from hashlib import sha256
import json
from pathlib import Path
import plistlib
import pytest
from scripts.m1_klm_previous_source import staged_previous_root, LABEL, ENTRY, MODULE


def fixture(tmp_path):
    home = tmp_path / "owner"
    stage = home / "Library/Application Support/AI-Foundation/operator-release-staging" / ("a" * 64)
    root = stage / "candidate"
    file = root / MODULE
    file.parent.mkdir(parents=True)
    file.write_bytes(b"# reviewed KLM source\n")
    (stage / "manifest.json").write_text(json.dumps({
        "scope_ref": stage.name, "candidate_commit": "b" * 40}))
    plist = {"Label": LABEL, "StartInterval": 900,
             "ProgramArguments": ["/usr/bin/python3", str(root / ENTRY)],
             "EnvironmentVariables": {"PYTHONPATH": str(root / "src")}}
    return home, stage, root, plist


def read(path, *, max_bytes):
    data = Path(path).read_bytes()
    assert len(data) <= max_bytes
    return data


def test_previous_stage_requires_exact_source_and_existing_guard_proof(tmp_path):
    home, stage, root, plist = fixture(tmp_path)
    approvals = []
    def approved(commit, digest):
        approvals.append((commit, digest))
        return commit == "b" * 40 and digest == sha256((root / MODULE).read_bytes()).hexdigest()
    assert staged_previous_root(plistlib.dumps(plist), home, read_bytes=read,
        verify_stage=lambda path, ref: path == stage and ref == stage.name,
        guard_accepts=approved) == root
    assert len(approvals) == 1


@pytest.mark.parametrize("sealed,approved", [(False, True), (True, False)])
def test_unsealed_or_unapproved_previous_stage_never_becomes_rollback_target(tmp_path, sealed, approved):
    home, stage, root, plist = fixture(tmp_path)
    with pytest.raises(ValueError, match="PREVIOUS_KLM_STAGE_UNVERIFIED"):
        staged_previous_root(plistlib.dumps(plist), home, read_bytes=read,
            verify_stage=lambda *args: sealed, guard_accepts=lambda *args: approved)


def test_untrusted_previous_path_is_rejected_before_any_file_read(tmp_path):
    home, stage, root, plist = fixture(tmp_path)
    plist["ProgramArguments"][-1] = str(tmp_path / "private" / ENTRY)
    def forbidden(*args, **kwargs):
        raise AssertionError("must reject before touching owner files")
    with pytest.raises(ValueError, match="PREVIOUS_KLM_STAGE_UNVERIFIED"):
        staged_previous_root(plistlib.dumps(plist), home, read_bytes=forbidden,
            verify_stage=forbidden, guard_accepts=forbidden)
