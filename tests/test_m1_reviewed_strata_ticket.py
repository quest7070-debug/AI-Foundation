"""Reviewed public Strata task integrity; no inference, host write or GitHub."""
import pytest
from scripts import m1_reviewed_strata_ticket as reviewed


def test_reviewed_second_ticket_is_github_immutable_and_independently_tested():
    rows = reviewed._review_bundle()
    assert len(rows) == 1
    item = rows[0]
    assert item["ticket_id"] == "strata-dispatcher-binding-v1"
    assert item["target"] != item["test"]
    # The original immutable ticket pins the *pre-fix* source bytes. A new
    # Git source revision must never silently inherit that owner review.
    current = reviewed.git(reviewed.ROOT, "hash-object", "--", item["target"])
    if current == item["source_blob_sha1"]:
        source = reviewed._reviewed_bytes(item["target"], item["source_blob_sha1"])
        assert b"class LocalExecutionDispatcher" in source
    else:
        with pytest.raises(ValueError, match="REVIEWED_PUBLIC_BLOB_MISMATCH"):
            reviewed._reviewed_bytes(item["target"], item["source_blob_sha1"])
    case = reviewed._reviewed_bytes(item["case_source"], item["case_blob_sha1"])
    assert b"test_nonstring_bindings_are_not_implicit_authority" in case
    assert not (reviewed.ROOT / item["test"]).exists()

def test_error_codes_are_explicit_and_standard_venv_symlink_is_supported(tmp_path):
    import os
    # Fixed categories cannot return a credential-bearing ValueError message.
    assert "OWNER_PYTHON_UNAVAILABLE" in reviewed._INSTALL_BLOCKERS
    assert "PRIVATE_KEY_AS_ERROR" not in reviewed._INSTALL_BLOCKERS
    target = tmp_path / "python-real"
    target.write_text("#!/bin/sh\\nexit 0\\n")
    target.chmod(0o700)
    venv = tmp_path / ".venv/bin"
    venv.mkdir(parents=True)
    link = venv / "python"
    link.symlink_to(target)
    assert link.is_symlink() and link.is_file() and os.access(link, os.X_OK)


def test_completed_dashboard_fix_is_not_admitted_as_new_work():
    assert all(item["ticket_id"] != "strata-human-view-ready-v1"
               for item in reviewed._review_bundle())
    # Preserve the independent historical acceptance bytes; normal
    # test_human_view now covers the repaired product source.
    case = reviewed._reviewed_bytes(
        "experiments/strata_acceptance/human_view_ready.case",
        "1745edd9bc348b707bf4eaa1fec5efff6c3effd0")
    assert b"test_only_boolean_true_certifies_core_readiness" in case
    assert not (reviewed.ROOT / "tests/test_strata_human_view_ready.py").exists()


def test_install_run_does_not_select_first_historical_ticket(monkeypatch):
    def fail_run(*_args, **_kwargs):
        raise AssertionError("historical ticket must not be invoked")
    monkeypatch.setattr(reviewed.subprocess, "run", fail_run)
    result = reviewed.run_fresh_reviewed_ticket({
        "status": "REVIEWED_TICKETS_INSTALLED",
        "ticket_id": "strata-dispatcher-binding-v1",
        "fresh_ticket_id": None, "added": 0, "strata_available": True,
    })
    assert result["status"] == "NO_SINGLE_FRESH_REVIEWED_TICKET"
    assert result["model_calls"] == 0


def test_fresh_ticket_defers_when_strata_unavailable(monkeypatch):
    def fail_run(*_args, **_kwargs):
        raise AssertionError("no model route means no local Work claim")
    monkeypatch.setattr(reviewed.subprocess, "run", fail_run)
    result = reviewed.run_fresh_reviewed_ticket({
        "status": "REVIEWED_TICKETS_INSTALLED",
        "ticket_id": "strata-fresh-public-v1",
        "fresh_ticket_id": "strata-fresh-public-v1",
        "added": 1, "strata_available": False,
    })
    assert result["status"] == "WAITING_STRATA"
    assert result["model_calls"] == 0


def test_fresh_ticket_requires_exact_ready_host_status(monkeypatch):
    import json
    from types import SimpleNamespace

    calls = []
    def status_only(cmd, **_kwargs):
        calls.append(cmd[-2:])
        return SimpleNamespace(returncode=0, stdout=json.dumps({
            "status": "OBSERVED",
            "ticket": {"ticket_id": "strata-fresh-public-v1",
                       "state": "VERIFIED_LOCAL"},
        }))
    monkeypatch.setattr(reviewed.subprocess, "run", status_only)
    result = reviewed.run_fresh_reviewed_ticket({
        "status": "REVIEWED_TICKETS_INSTALLED",
        "ticket_id": "strata-fresh-public-v1",
        "fresh_ticket_id": "strata-fresh-public-v1",
        "added": 1, "strata_available": True,
    })
    assert result["status"] == "REVIEWED_TICKET_NOT_READY"
    assert calls == [["status", "strata-fresh-public-v1"]]


def test_only_new_exact_ready_ticket_reaches_guarded_local_client(monkeypatch):
    import json
    from types import SimpleNamespace

    calls = []
    ident = "strata-fresh-public-v1"
    def local_client(cmd, **_kwargs):
        calls.append(cmd[-2:])
        if cmd[-2] == "status":
            payload = {"status": "OBSERVED",
                       "ticket": {"ticket_id": ident, "state": "READY"}}
        else:
            payload = {"status": "MCP_CODE_VERIFIED",
                       "ticket": {"state": "VERIFIED_LOCAL",
                                  "execution_binding": "local:mainpc-strata:code-agent"}}
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload))
    monkeypatch.setattr(reviewed.subprocess, "run", local_client)
    result = reviewed.run_fresh_reviewed_ticket({
        "status": "REVIEWED_TICKETS_INSTALLED",
        "ticket_id": ident,
        "fresh_ticket_id": ident,
        "added": 1, "strata_available": True, "model_calls": 0,
    })
    assert calls == [["status", ident], ["run", ident]]
    assert result["status"] == "MCP_CODE_VERIFIED"
    assert "model_calls" not in result
