"""Synthetic-only contracts: no live service, model, network or Guard writes."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from scripts import m1_privacy_operator_release as rel


def owner_fixture():
    sha = "a" * 40
    event = {"action": "labeled", "sender": {"login": rel.OWNER},
             "repository": {"full_name": rel.REPO}, "label": {"name": rel.LABEL},
             "pull_request": {"number": rel.PR, "state": "open",
                 "user": {"login": rel.OWNER},
                 "head": {"sha": sha, "ref": rel.BRANCH,
                          "repo": {"full_name": rel.REPO}}}}
    env = {"GITHUB_REPOSITORY": rel.REPO, "GITHUB_WORKFLOW": rel.WORKFLOW,
           "GITHUB_EVENT_NAME": "pull_request", "GITHUB_ACTOR": rel.OWNER,
           "RELEASE_HANDLER_SHA": "b" * 40}
    return event, env


def test_only_owner_label_is_release_request():
    event, env = owner_fixture()
    calls = []
    def fake_api(method, path, token):
        calls.append(path)
        if path.endswith("/pulls/612"):
            return {"state": "open", "head": event["pull_request"]["head"]}
        return [{"name": rel.LABEL}]
    command = SimpleNamespace(returncode=0, stdout="b" * 40 + "\n")
    with patch.object(rel, "api", fake_api), patch.object(rel.subprocess, "run", return_value=command):
        assert rel.owner_request(event, env, "synthetic-token") == "a" * 40
        assert len(calls) == 2
        for mutation in ("sender", "label", "pull_request"):
            changed = dict(event)
            changed[mutation] = {"login": "outsider"} if mutation == "sender" else {}
            with pytest.raises(rel.Denied):
                rel.owner_request(changed, env, "synthetic-token")
        changed = dict(env, GITHUB_ACTOR="outsider")
        with pytest.raises(rel.Denied):
            rel.owner_request(event, changed, "synthetic-token")


def test_release_scope_binds_exact_candidate_and_original():
    scope = rel.release_scope()
    assert scope.source_sha == rel.CANDIDATE
    assert rel.OLD_PLIST in scope.previous_authority
    assert rel.OLD_ENTRY in scope.previous_authority
    assert "OPERATOR" in scope.switch_target
    assert scope.scope_ref != rel.release_scope().__class__(
        **{**scope.as_dict(), "source_sha": "f" * 40}).scope_ref


def test_owned_source_rejects_symlink_and_unowned_shape(tmp_path):
    f = tmp_path / "file.py"
    f.write_text("synthetic source")
    assert rel.owned_bytes(f) == b"synthetic source"
    alias = tmp_path / "link.py"
    alias.symlink_to(f)
    with pytest.raises(rel.Denied):
        rel.owned_bytes(alias)


def test_cutover_failed_readback_restores_original_without_touching_worker(tmp_path, monkeypatch):
    home = tmp_path
    plist = home / "Library/LaunchAgents" / (rel.OP_LABEL + ".plist")
    plist.parent.mkdir(parents=True)
    raw = b"old plist content"
    plist.write_bytes(raw)
    target = home / "stage"
    target.mkdir()
    (target / "proposed.plist").write_bytes(b"new plist content")
    entry = home / "scripts/operator_server.py"
    source = (plist, raw, {"ProgramArguments": ["/usr/bin/python3", str(entry)]},
              entry, home / "src/ai_foundation")
    monkeypatch.setattr(rel, "prior", lambda home: source)
    monkeypatch.setattr(rel, "idle", lambda: True)
    monkeypatch.setattr(rel, "verify_new", lambda *a, **k: (_ for _ in ()).throw(rel.Denied("NO_PROOF")))
    seen = []
    def fake_launch(*args):
        seen.append(args)
        return SimpleNamespace(returncode=0, stdout=str(entry))
    monkeypatch.setattr(rel, "launch", fake_launch)
    with pytest.raises(rel.Denied, match="CUTOVER_FAILED_PRIOR_OPERATOR_RESTORED"):
        rel.cutover(home, source, target, lambda: True)
    assert plist.read_bytes() == raw
    assert not any(rel.WORKER_LABEL in " ".join(args) for args in seen)
    assert sum(args[0] == "bootout" for args in seen) == 2
    assert sum(args[0] == "bootstrap" for args in seen) == 2

def test_privacy_readback_survives_independently_approved_worker_release(tmp_path, monkeypatch):
    """One live-observed failure's no-effect regression, no daemon/network."""
    import hashlib
    import json
    from scripts import m1_privacy_operator_preflight as probe

    release = tmp_path / probe.TARGET[:12]
    manifest = {
        "schema": 1, "candidate_sha": probe.TARGET,
        "files": {"src/ai_foundation/guard.py": hashlib.sha256(b"fixture").hexdigest()},
        "launcher_sha256": hashlib.sha256(b"launcher").hexdigest(),
    }
    raw_manifest = json.dumps(manifest).encode()
    worker = {
        # A separately approved 9B-worker release changed its plist SHA.
        "definition_sha256": "new-independent-worker-release",
        "entry_name": "local9b_autodev_worker.py",
        "loaded_entry_present": True,
    }
    operator = {
        "entry_name": "launcher.py", "_path": release / "launcher.py",
        "running": True, "loaded_entry_present": True, "pid": 123,
    }
    monkeypatch.setattr(probe.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(probe.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(probe.os, "getuid", lambda: 501)
    monkeypatch.setattr(probe, "service", lambda home, label:
                        operator if label == probe.OPERATOR_LABEL else worker)
    def checked(path, *args):
        name = str(path)
        return (raw_manifest if name.endswith("manifest.json")
                else b"prior" if name.endswith("prior.plist")
                else b"launcher" if name.endswith("launcher.py") else b"fixture")
    monkeypatch.setattr(probe, "checked", checked)
    original = hashlib.sha256
    class FixedDigest:
        def hexdigest(self):
            return "9bb6decbf24ef6710a318e2cb2a4f681d6fceff81ad8b8e228899aa49b58dc03"
    monkeypatch.setattr(probe, "sha256",
                        lambda raw: FixedDigest() if raw == b"prior" else original(raw))
    proof = {
        "pid": 123, "candidate_sha": probe.TARGET,
        "manifest_sha256": original(raw_manifest).hexdigest(),
        "startup_sources_verified": True,
    }
    class Reply:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, amount): return json.dumps(proof).encode()
    class Opener:
        def open(self, url, timeout):
            assert url == "http://127.0.0.1:8766/internal/privacy-fastpath-release"
            return Reply()
    monkeypatch.setattr(probe, "build_opener", lambda *_args: Opener())

    accepted = probe.audit(tmp_path, tmp_path)
    assert accepted["status"] == "OBSERVED"
    assert accepted["worker_service_identity_observed"] is True
    assert accepted["worker_version_attested_by_this_probe"] is False
    assert accepted["loaded_operator_verified"] is True

    worker["loaded_entry_present"] = False
    rejected = probe.audit(tmp_path, tmp_path)
    assert rejected["status"] == "BLOCKED"
    assert rejected["loaded_operator_verified"] is False
