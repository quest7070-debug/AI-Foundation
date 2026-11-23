"""An old stage is a rollback target only with its actual durable Guard proof."""
import json
import sqlite3
import sys
import pytest
from ai_foundation.guard import GuardCore
from ai_foundation.release_gate import GuardReleaseGate, ImmutableReleaseScope
from ai_foundation.store import SQLiteGuardStore
from scripts import m1_github_owner_klm_main_release as release
from scripts.m1_klm_fairness_release import Denied


@pytest.mark.parametrize("status", ["PLANNED", "RUNNING"])
def test_main_release_uses_current_lease_without_importing_legacy_tree(tmp_path, monkeypatch, status):
    db = tmp_path / "work.sqlite"
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE work_steps(job_id TEXT,status TEXT)")
        con.execute("INSERT INTO work_steps VALUES(?,?)", ("klm-existing", status))
    (tmp_path / "config.json").write_text(json.dumps({
        "data_dir": str(tmp_path), "work_db": db.name}))
    lease = object()
    monkeypatch.setattr(release, "HostComputeLease", lambda: lease)
    paths = tuple(sys.path)
    module = sys.modules.get("ai_foundation.host_compute_lease")
    if status == "RUNNING":
        with pytest.raises(Denied, match="KLM_WORK_ACTIVE"):
            release.compute_admission(tmp_path, tmp_path / "missing-legacy-releases")
    else:
        assert release.compute_admission(tmp_path, tmp_path / "missing-legacy-releases") is lease
    assert tuple(sys.path) == paths
    assert sys.modules.get("ai_foundation.host_compute_lease") is module


def test_previous_stage_requires_verified_cutover_and_exact_durable_approval(tmp_path, monkeypatch):
    db = tmp_path / "guard.sqlite"
    store = SQLiteGuardStore(db)
    GuardCore(store.load(), store=store)
    commit, module_hash = "b" * 40, "c" * 64
    scope = ImmutableReleaseScope(
        path="m1-klm-main-module", source_sha="a" * 64,
        previous_authority="owner-klm:old", previous_endpoint="launchd:klm",
        candidate_authority="github-commit:" + commit,
        candidate_endpoint="staged-klm:" + module_hash,
        rollback_procedure="restore exact prior plist", switch_target="idle KLM only",
        readback_target="exact staged source", rollback_readback_target="prior source",
    )
    registry = tmp_path / ("owner-klm-main-" + scope.scope_ref[:20] + ".json")
    gate = GuardReleaseGate(store, registry)
    prepared = gate.prepare(scope, canon_revision="canon-synthetic-test")
    monkeypatch.setattr(release, "_guard_path", lambda home: (db, None))
    assert release.previous_stage_approved(tmp_path, commit, module_hash) is False
    assert store.approve_pending(prepared["run_id"], prepared["request_ref"])
    # An approved plan that never completed cutover is still not a deployed prior.
    assert release.previous_stage_approved(tmp_path, commit, module_hash) is False
    gate.registry.transition(scope.path, "PREPARED", "CUTOVER")
    gate.registry.transition(scope.path, "CUTOVER", "VERIFIED")
    assert release.previous_stage_approved(tmp_path, commit, module_hash) is True
    assert release.previous_stage_approved(tmp_path, "d" * 40, module_hash) is False
    assert release.previous_stage_approved(tmp_path, commit, "d" * 64) is False
    # Registry metadata alone cannot invent a matching approval in the real store.
    record = json.loads(registry.read_text())
    record["paths"][scope.path]["release_run_id"] = "forged-no-approval"
    registry.write_text(json.dumps(record))
    assert release.previous_stage_approved(tmp_path, commit, module_hash) is False
