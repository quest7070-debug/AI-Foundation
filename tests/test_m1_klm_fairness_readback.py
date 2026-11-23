"""No-model, no-effect independent KLM release readback."""
import plistlib
from types import SimpleNamespace

import pytest
from scripts import m1_klm_fairness_readback as rb


def fixed_env(monkeypatch, tmp_path):
    monkeypatch.setattr(rb.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(rb.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(rb.os, "getuid", lambda: 501)
    releases = tmp_path / "Library/Application Support/AI-Foundation/klm-drive/releases"
    new = releases / rb.NEW
    new.mkdir(parents=True)
    prior = {"Label": rb.LABEL, "StartInterval": 900,
             "ProgramArguments": ["/opt/homebrew/bin/python3",
                                  str(releases / rb.OLD / rb.ENTRY)],
             "EnvironmentVariables": {
                 "PYTHONPATH": str(releases / rb.OLD / "src"),
                 "PRESERVE": "not-a-secret"}}
    installed = {"Label": rb.LABEL, "StartInterval": 900,
                 "ProgramArguments": ["/opt/homebrew/bin/python3",
                                      str(releases / rb.NEW / rb.ENTRY)],
                 "EnvironmentVariables": {
                     "PYTHONPATH": str(releases / rb.NEW / "src"),
                     "PRESERVE": "not-a-secret"}}
    expected = {"previous-klm-launchagent.plist": plistlib.dumps(prior),
                rb.LABEL + ".plist": plistlib.dumps(installed)}
    for name in rb.BLOBS:
        expected[name] = name.encode()
    def read(path, *, maximum, private=False):
        key = ("previous-klm-launchagent.plist" if str(path).endswith("previous-klm-launchagent.plist")
               else rb.LABEL + ".plist" if str(path).endswith(rb.LABEL + ".plist")
               else str(path.relative_to(new)))
        return expected[key]
    monkeypatch.setattr(rb, "bounded_owner_file", read)
    monkeypatch.setattr(rb, "blob",
                        lambda raw: rb.BLOBS[raw.decode()])
    def run(args, **kwargs):
        if args[0] == "/usr/bin/git":
            return SimpleNamespace(returncode=0, stdout=rb.NEW + "\n")
        assert args[0] == "/bin/launchctl"
        return SimpleNamespace(returncode=0, stdout=str(new / rb.ENTRY))
    monkeypatch.setattr(rb.subprocess, "run", run)
    return installed, expected, new


def test_independent_readback_exact_install_and_rollback(monkeypatch, tmp_path):
    installed, _, _ = fixed_env(monkeypatch, tmp_path)
    result = rb.readback(home=tmp_path)
    assert result["status"] == "APPLIED_VERIFIED"
    assert result["rollback_backup_preserved"] is True
    assert result["pinned_files_read_back"] == len(rb.BLOBS)
    assert result["owner_data_writes"] == result["model_calls"] == 0


def test_independent_readback_refuses_wrong_release(monkeypatch, tmp_path):
    installed, expected, new = fixed_env(monkeypatch, tmp_path)
    installed["ProgramArguments"][-1] = installed["ProgramArguments"][-1].replace(rb.NEW, rb.OLD)
    expected[rb.LABEL + ".plist"] = plistlib.dumps(installed)
    with pytest.raises(rb.ReadbackDenied, match="KLM_ACTIVE_RELEASE_NOT_EXPECTED"):
        rb.readback(home=tmp_path)


def test_independent_readback_refuses_unrelated_plist_change(monkeypatch, tmp_path):
    installed, expected, _ = fixed_env(monkeypatch, tmp_path)
    installed["EnvironmentVariables"]["PRESERVE"] = "drift"
    expected[rb.LABEL + ".plist"] = plistlib.dumps(installed)
    with pytest.raises(rb.ReadbackDenied, match="KLM_UNRELATED_SERVICE_CONFIG_CHANGED"):
        rb.readback(home=tmp_path)
