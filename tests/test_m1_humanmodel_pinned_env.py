"""No-network, no-model contract tests for one-time owner pinned runtime."""
import json
from pathlib import Path

from scripts import m1_humanmodel_pinned_env as pinned
from scripts import m1_owner_humanmodel_fast_entry as entry


def test_setup_issue_is_exact_owner_action():
    issue = {"number": 25, "state": "open", "title": pinned.TITLE,
             "body": pinned.BODY, "user": {"login": pinned.OWNER}}
    event = {"action": "opened", "repository": {"full_name": pinned.REPO},
             "sender": {"login": pinned.OWNER}, "issue": issue}
    assert pinned.event_authorized(event, issue)
    assert not pinned.event_authorized(event, {**issue, "body": "untrusted"})
    assert not pinned.event_authorized(
        {**event, "sender": {"login": "someone-else"}}, issue)


def test_main_lock_fingerprint_changes_when_frozen_source_changes(tmp_path, monkeypatch):
    (tmp_path / "uv.lock").write_text("dependency lock")
    (tmp_path / "pyproject.toml").write_text("[project]")
    monkeypatch.setattr(pinned, "ROOT", tmp_path)
    first = pinned.source_signature()
    assert all(len(v) == 64 for v in first.values())
    (tmp_path / "uv.lock").write_text("changed lock")
    assert pinned.source_signature()["uv_lock_sha256"] != first["uv_lock_sha256"]


def test_fast_private_answer_prefers_exact_verified_environment(monkeypatch):
    expected = Path("/valid-only-after-owner-runtime-check/bin/python")
    monkeypatch.setattr(entry, "runtime_ready", lambda: expected)
    monkeypatch.setattr(entry.readiness, "installed_paths",
                        lambda: (_ for _ in ()).throw(AssertionError("no fallback")))
    assert entry.installed_python() == expected


def test_no_model_or_owner_data_paths_in_runtime_module():
    script = Path(pinned.__file__).read_text()
    assert "from ai_foundation.auto_agent" not in script
    assert "/api/chat" not in script
    assert "human_model_context" not in script


def test_failed_sync_preserves_old_manifest_and_reports_blocked(tmp_path, monkeypatch):
    marker = tmp_path / pinned.MANIFEST_NAME
    original = '{"uv_lock_sha256":"previous-lock"}'
    marker.write_text(original)
    receipts = []
    monkeypatch.setattr(pinned, "owner_context", lambda: ("test", "/issues/25", 25))
    def api(method, path, token, payload=None):
        if method == "GET":
            return []
        receipts.append(payload)
    monkeypatch.setattr(pinned.bridge, "_github_api", api)
    def unexpected(*args, **kwargs):
        raise AssertionError("failed sync must not inspect or certify old runtime")
    monkeypatch.setattr(pinned, "secure_parent", unexpected)
    monkeypatch.setattr(pinned.subprocess, "run", unexpected)
    for outcome in (None, "", "failure", "cancelled", "skipped"):
        assert pinned.finalize(sync_outcome=outcome) == 1
        assert marker.read_text() == original
        assert '"reason": "DEPENDENCY_SYNC_NOT_SUCCESSFUL"' in receipts[-1]["body"]
        assert '"status": "BLOCKED"' in receipts[-1]["body"]


def test_successful_sync_binds_manifest_to_current_lock(tmp_path, monkeypatch):
    from types import SimpleNamespace
    receipts = []
    signature = {"uv_lock_sha256": "a" * 64, "project_sha256": "b" * 64}
    monkeypatch.setattr(pinned, "owner_context", lambda: ("test", "/issues/25", 25))
    def api(method, path, token, payload=None):
        if method == "GET":
            return []
        receipts.append(payload)
    monkeypatch.setattr(pinned.bridge, "_github_api", api)
    monkeypatch.setattr(pinned, "secure_parent", lambda: tmp_path)
    monkeypatch.setattr(pinned, "source_signature", lambda: signature)
    monkeypatch.setattr(pinned.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0))
    monkeypatch.setattr(pinned, "runtime_ready", lambda: tmp_path / "venv/bin/python")
    assert pinned.finalize(sync_outcome="success") == 0
    marker = tmp_path / pinned.MANIFEST_NAME
    data = json.loads(marker.read_text())
    assert all(data[k] == v for k, v in signature.items())
    assert marker.stat().st_mode & 0o777 == 0o600
    assert '"status": "PINNED_RUNTIME_READY"' in receipts[-1]["body"]
