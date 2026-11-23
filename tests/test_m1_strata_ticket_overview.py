"""Read-only owner Work aggregate: existing multiple tickets, never retry."""
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from scripts.m1_strata_ticket_overview import summarize, _contract


def test_read_only_owner_ticket_summary_recovers_verified_strata_without_paths(tmp_path):
    root = tmp_path / "owner"
    dev = root / "development"
    dev.mkdir(mode=0o700, parents=True)
    dev.chmod(0o700)
    source = dev / "worktrees/task-one/src/ai_foundation/test_fixture.py"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"VALUE = 2\n")
    test = dev / "worktrees/task-one/tests/test_fixture.py"
    test.parent.mkdir(parents=True)
    test.write_bytes(b"assert True\n")
    original = dev / "tickets.json"
    instruction = "Return full reviewed Python source"
    record = {
        "ticket_id": "task-one", "base_sha": "a"*40,
        "target": "src/ai_foundation/test_fixture.py",
        "test": "tests/test_fixture.py",
        "model": "strata", "instruction": instruction,
        "source_sha256": "b"*64, "test_sha256": sha256(test.read_bytes()).hexdigest(),
        "public_source_sha256": "b"*64,
        "public_instruction_sha256": sha256(instruction.encode()).hexdigest(),
    }
    original.write_text(json.dumps({"version":1,"tickets":[record]}))
    original.chmod(0o600)
    db = root / "work.db"
    job = "mcp-local-development:" + sha256(json.dumps(
        ["macos-owner-local", "task-one"], separators=(",", ":")).encode()).hexdigest()
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE work_steps(job_id TEXT,position INTEGER,status TEXT,result TEXT,name TEXT)")
        con.execute("INSERT INTO work_steps VALUES (?,?,?,?,?)", (
            job, 0, "VERIFIED", json.dumps({"status":"TESTED_CHANGE",
            "sha256":sha256(source.read_bytes()).hexdigest(),
            "execution_binding":"local:mainpc-strata:code-agent"}), _contract(record)))
    result = summarize(root, db)
    assert result["status"] == "READ_VERIFIED"
    assert result["ticket_count"] == 1
    assert result["strata_verified"] == 1
    assert result["source_mismatch"] == 0
    assert str(root) not in json.dumps(result)
    # Preserve original FAILED evidence. An equivalent successful task proves
    # recovery of the outcome, never success of the failed Work itself.
    failed = {**record, "ticket_id": "task-failed", "base_sha": "d"*40}
    original.write_text(json.dumps({"version": 1, "tickets": [failed, record]}))
    failed_job = "mcp-local-development:" + sha256(json.dumps(
        ["macos-owner-local", failed["ticket_id"]], separators=(",", ":")).encode()).hexdigest()
    with sqlite3.connect(db) as con:
        con.execute("INSERT INTO work_steps VALUES (?,?,?,?,?)", (
            failed_job, 0, "FAILED", "RuntimeError", _contract(failed)))
    before = db.read_bytes()
    recovered = summarize(root, db)
    assert recovered["work_states"] == {"FAILED": 1, "VERIFIED": 1}
    assert recovered["failed_recovered_by_equivalent_ticket"] == 1
    assert recovered["failed_unresolved"] == 0
    assert recovered["failure_codes"] == {"RuntimeError": 1}
    assert db.read_bytes() == before
    # A different reviewed instruction cannot be reconciled by target alone.
    changed_failed = {**failed, "instruction": "A different task"}
    changed_failed["public_instruction_sha256"] = sha256(changed_failed["instruction"].encode()).hexdigest()
    original.write_text(json.dumps({"version": 1, "tickets": [changed_failed, record]}))
    denied = summarize(root, db)
    assert denied["failed_recovered_by_equivalent_ticket"] == 0
    assert denied["failed_unresolved"] == 1
    assert denied["contract_mismatch"] == 1
    original.write_text(json.dumps({"version": 1, "tickets": [failed, record]}))
    # Changing the independent test invalidates successful recovery evidence.
    test.write_bytes(b"assert False\n")
    assert summarize(root, db)["failed_unresolved"] == 1
    test.write_bytes(b"assert True\n")
    source.write_bytes(b"VALUE = 3\n")
    changed = summarize(root, db)
    assert changed["strata_verified"] == 0
    assert changed["source_mismatch"] == 1
    assert changed["failed_unresolved"] == 1
    with sqlite3.connect(db) as con:
        con.execute("UPDATE work_steps SET status='PRIVATE_BAD_STATUS',result='secret /owner/path' WHERE job_id=?", (failed_job,))
    unknown = summarize(root, db)
    assert unknown["work_states"] == {"UNKNOWN": 1, "VERIFIED": 1}
    assert "PRIVATE_BAD_STATUS" not in json.dumps(unknown)
    assert "secret" not in json.dumps(unknown)


def test_runner_strata_readback_uses_installed_work_db_not_undefined_globals(tmp_path):
    import os
    from types import SimpleNamespace
    from unittest import mock
    from scripts import m1_runtime_status_probe as status
    from scripts import m1_human_model_activation_readiness as readiness
    from scripts import m1_direct_development as direct
    from scripts import m1_strata_ticket_overview as overview
    from scripts import mainpc_management_readiness
    endpoint = {"version": 1, "endpoints": [{
        "name": "mainpc-strata",
        "base_url": "http://10.0.1.1:18080",
        "allowed_hosts": ["10.0.1.1"],
        "api_key_env": "STRATA_API_KEY", "optional": True,
        "models": [{"alias": "code-agent",
                    "runtime_model": "qwen3.8-flash-next-coder-iq1_m",
                    "capabilities": ["CODE"]}]
    }]}
    summary = {"status": "READ_VERIFIED", "ticket_count": 2,
               "strata_verified": 2, "model_calls": 0}
    with (mock.patch.object(status, "require_m1"),
          mock.patch.object(readiness, "installed_paths",
                            return_value=(tmp_path / "entry.py", tmp_path)),
          mock.patch.object(status, "_safe_path", side_effect=lambda x: x),
          mock.patch.object(status, "_owned_bytes",
                            return_value=(json.dumps(endpoint).encode(), None)),
          mock.patch.object(direct, "installed_config",
                            return_value=(None, SimpleNamespace(work_db="work.db"), tmp_path)),
          mock.patch.object(direct, "diagnose",
                            return_value={"status": "DIRECT_DEVELOPMENT_OBSERVED", "model_calls": 0}),
          mock.patch.object(overview, "summarize", return_value=summary) as read,
          mock.patch.object(mainpc_management_readiness, "management_readiness",
                            return_value={"status": "OBSERVED", "model_calls": 0}),
          mock.patch.dict(os.environ, {}, clear=True)):
        result = status.strata_status()
    assert result["status"] == "RUNNER_KEY_UNAVAILABLE"
    assert result["direct_development"]["tickets"] == summary
    read.assert_called_once_with(tmp_path, tmp_path / "work.db")


def test_owner_code_manifest_capacity_shared_and_readonly_boundaries(tmp_path):
    """Historical fixed-test Work remains readable beyond the old 8-row cap.

    A bounded count is still mandatory: neither admission nor the M1 viewer
    may silently accept an unbounded or duplicated owner manifest. Merely
    increasing history never starts a model, retries Work or grants CODE scope.
    """
    from scripts import m1_development_ticket_factory as factory
    from scripts import m1_strata_owner_ticket_admission as admission
    from scripts import m1_direct_development as direct
    from scripts import m1_reviewed_strata_ticket as reviewed
    from scripts import m1_strata_ticket_overview as overview

    cap = factory.MAX_OWNER_DEVELOPMENT_TICKETS
    assert cap == 24
    assert cap == admission.MAX_OWNER_DEVELOPMENT_TICKETS
    assert cap == direct.MAX_OWNER_DEVELOPMENT_TICKETS
    assert cap == reviewed.MAX_OWNER_DEVELOPMENT_TICKETS
    assert cap == overview.MAX_OWNER_DEVELOPMENT_TICKETS

    root = tmp_path / "owner"
    dev = root / "development"
    dev.mkdir(parents=True, mode=0o700)
    dev.chmod(0o700)
    manifest = dev / "tickets.json"
    work_db = root / "work.db"
    with sqlite3.connect(work_db) as db:
        db.execute("""CREATE TABLE work_steps(
            job_id TEXT, position INTEGER, status TEXT,
            result TEXT, name TEXT)""")

    records = []
    for i in range(cap + 1):
        records.append({
            "ticket_id": "reviewed-history-" + str(i),
            "base_sha": "a" * 40,
            "target": "src/ai_foundation/test_fixture.py",
            "test": "tests/test_fixture.py",
            "model": "m1",
            "instruction": "Independent fixed acceptance, no Work replay.",
            "source_sha256": "b" * 64,
            "test_sha256": "c" * 64,
        })
    for n in (8, 9, cap):
        manifest.write_text(json.dumps({"version": 1, "tickets": records[:n]}))
        manifest.chmod(0o600)
        observed = summarize(root, work_db)
        assert observed["status"] == "READ_VERIFIED"
        assert observed["ticket_count"] == n
        assert observed["work_states"] == {"PLANNED": n}
        assert observed["model_calls"] == 0
    # At 24 valid records, long owner-reviewed text exceeds the generic
    # private-file 64-KiB read bound. The higher bound applies ONLY to this
    # specific owner manifest; other owner files retain the tighter default.
    padded = [{**record, "instruction": "あ" * 4000}
              for record in records[:cap]]
    manifest.write_text(json.dumps({"version": 1, "tickets": padded}))
    assert manifest.stat().st_size > 65536
    assert factory._owner_manifest(manifest) == manifest.read_bytes()
    try:
        factory._owner_file(manifest)
    except ValueError as exc:
        assert str(exc) == "DEVELOPMENT_MANIFEST_SIZE_INVALID"
    else:
        raise AssertionError("generic private-file bound must remain intact")
    large = summarize(root, work_db)
    assert large["status"] == "READ_VERIFIED"
    assert large["ticket_count"] == cap
    assert large["work_states"] == {"PLANNED": cap}
    manifest.write_text(json.dumps({"version": 1, "tickets": records}))
    too_many = summarize(root, work_db)
    assert too_many["status"] == "UNVERIFIED"
    assert too_many["ticket_count"] == 0
    assert too_many["model_calls"] == 0
