"""Real absolute-script Operator bootstrap must expose its pinned scripts package.

The physical launchd contract intentionally has PYTHONPATH=src:experiments,
not the candidate repository root. A standard PR test runner has cwd on
sys.path; the installed absolute script does not. This subprocess recreates
that distinction without starting Operator, opening owner data, or Guard.
"""
import os
from pathlib import Path
import subprocess
import sys


def test_operator_absolute_script_exposes_only_its_own_pinned_scripts_root(
        tmp_path):
    repo = Path(__file__).resolve().parents[1]
    entry = repo / "scripts/operator_server.py"
    assert entry.is_file()
    code = """
import os, runpy, sys
from pathlib import Path
entry = Path(sys.argv[1]).resolve(strict=True)
root = entry.parents[1]
assert str(root) not in sys.path
# A true absolute-file invocation searches scripts/, not its parent root.
sys.path[0] = str(entry.parent)
runpy.run_path(str(entry), run_name="operator_import_root_nonmain_probe")
assert str(root) in sys.path
from scripts import m1_operator_release_cli as cli
from scripts import m1_development_review_candidate as review
assert Path(cli.__file__).resolve(strict=True) == root / "scripts/m1_operator_release_cli.py"
assert Path(review.__file__).resolve(strict=True) == root / "scripts/m1_development_review_candidate.py"
assert root != Path(os.environ["AI_FOUNDATION_REPO_ROOT"])
print("PINNED_OPERATOR_PACKAGE_IMPORT_VERIFIED")
"""
    env = {**os.environ,
           "PYTHONPATH": str(repo / "src") + ":" +
                         str(repo / "experiments/human_model"),
           "PYTHONDONTWRITEBYTECODE": "1",
           # Must not be used as an executable import source:
           "AI_FOUNDATION_REPO_ROOT": str(tmp_path)}
    result = subprocess.run(
        [sys.executable, "-B", "-c", code, str(entry)],
        cwd=tmp_path, env=env, text=True, capture_output=True,
        timeout=20, check=False)
    assert result.returncode == 0, result.stderr[-1200:]
    assert result.stdout.strip() == "PINNED_OPERATOR_PACKAGE_IMPORT_VERIFIED"


def test_release_launcher_environment_contract_stays_legacy_byte_compatible(
        tmp_path):
    from scripts.m1_operator_release_host import candidate_operator_plist, LABEL
    import plistlib
    repo = tmp_path / "candidate"
    script = repo / "scripts/operator_server.py"
    script.parent.mkdir(parents=True)
    script.write_text("reviewed")
    old_script = tmp_path / "prior" / "scripts/operator_server.py"
    original = plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": [sys.executable, "-B", str(old_script),
                             "--config", str(tmp_path / "config.json"),
                             "--port", "8766"],
        "EnvironmentVariables": {"PYTHONPATH": "/old/legacy/src"},
    })
    candidate, selected = candidate_operator_plist(original,old_script,repo)
    assert selected == str(script)
    row = plistlib.loads(candidate)
    assert row["EnvironmentVariables"]["PYTHONPATH"] == (
        str(repo / "src") + ":" + str(repo / "experiments/human_model"))
    assert row["WorkingDirectory"] == str(repo)
