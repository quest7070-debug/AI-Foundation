import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from scripts import m1_owner_toolhive_code_repair as repair


def test_workspace_uses_independent_objects_and_preserves_original_checkout(tmp_path):
    source = tmp_path / "original"
    source.mkdir()
    (tmp_path / "Develop").mkdir()
    def git(*args):
        return subprocess.check_output(["git", "-C", str(source), *args], text=True).strip()
    git("init", "-q")
    (source / "pyproject.toml").write_text('[project]\nname="fixture"\n')
    git("add", ".")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@localhost", "commit", "-qm", "base")
    revision = git("rev-parse", "HEAD")
    # The owner's checkout can contain ongoing unrelated work.
    (source / "private-untracked.txt").write_text("must remain only in original")
    before = git("status", "--porcelain")
    with patch.object(repair, "ROOT", source):
        workspace = repair.prepare_workspace(revision, tmp_path)
        assert not (workspace / "private-untracked.txt").exists()
        assert repair.git(workspace, "remote") == ""
        assert repair.git(workspace, "branch", "--show-current") == ""
        assert repair.prepare_workspace(revision, tmp_path) == workspace
        with pytest.raises(repair.Denied, match="CODE_WORKSPACE_REVIEW_REQUIRED"):
            repair.prepare_workspace("a" * 40, tmp_path)
    assert git("status", "--porcelain") == before
    assert git("rev-parse", "HEAD") == revision
    # Ignored private files must not be silently exposed through the /projects mount.
    (workspace / ".env").write_text("PRIVATE_TEST_SENTINEL")
    (workspace / ".git/info/exclude").write_text(".env\n*.sqlite\n")
    with patch.object(repair, "ROOT", source):
        with pytest.raises(repair.Denied, match="CODE_WORKSPACE_REVIEW_REQUIRED"):
            repair.prepare_workspace(revision, tmp_path)
    (workspace / ".env").unlink()
    (workspace / "data.sqlite").write_text("PRIVATE_TEST_SENTINEL")
    with patch.object(repair, "ROOT", source):
        with pytest.raises(repair.Denied, match="CODE_WORKSPACE_REVIEW_REQUIRED"):
            repair.prepare_workspace(revision, tmp_path)
    (workspace / "data.sqlite").unlink()
    (workspace / "pyproject.toml").write_text("isolated change")
    assert (source / "pyproject.toml").read_text() != "isolated change"


def test_uncertain_start_cannot_dispatch_twice(tmp_path):
    port = repair.FixedCodeWorkload(Path("/fixed/thv"), tmp_path, "/fixed/docker")
    plan = SimpleNamespace(target="toolhive:" + repair.NAME, action="production_deploy",
                           target_precondition="ABSENT")
    with patch.object(repair, "command", side_effect=subprocess.TimeoutExpired("fixed", 75)) as call:
        with pytest.raises(subprocess.TimeoutExpired):
            port.execute(plan)
        with pytest.raises(repair.Denied, match="FIXED_ONE_SHOT_CODE_REQUIRED"):
            port.execute(plan)
    assert call.call_count == 1
    assert port.dispatches == 1
    args = call.call_args.args[0]
    assert "--isolate-network" in args
    assert repair.EXPECTED_IMAGE_ID in args
    assert not {"rm", "stop", "start", "pull"} & set(args)


def test_absence_requires_both_registry_and_container_readbacks(tmp_path):
    port = repair.FixedCodeWorkload(Path("/fixed/thv"), tmp_path, "/fixed/docker")
    plan = SimpleNamespace(target="toolhive:" + repair.NAME)
    with patch.object(repair, "command", side_effect=["[]", ""]):
        assert port.observe(plan) == "ABSENT"
    with patch.object(repair, "command", side_effect=["[]", repair.NAME]):
        with pytest.raises(repair.Denied, match="CODE_CONTAINER_REGISTRY_CONFLICT"):
            port.observe(plan)
    with patch.object(repair, "command", return_value=json.dumps([{"name": repair.NAME, "status": "stopped"}])):
        assert port.observe(plan) == "EXISTING_WORKLOAD_REVIEW_REQUIRED"
    assert port.dispatches == 0


def test_independent_mount_check_rejects_extra_owner_data(tmp_path):
    port = repair.FixedCodeWorkload(Path("/fixed/thv"), tmp_path, "/fixed/docker")
    port.dispatches = 1
    mounts = [{"Type": "bind", "Source": str(tmp_path.resolve()), "Destination": "/projects", "RW": True},
              {"Type": "bind", "Source": "/owner/private", "Destination": "/secrets", "RW": True}]
    with patch.object(repair, "command", side_effect=[json.dumps([{"name": repair.NAME}]),
            json.dumps({"name": repair.NAME, "status": "running"}), json.dumps(mounts)]):
        with pytest.raises(repair.Denied, match="CODE_MOUNT_IDENTITY_UNVERIFIED"):
            port.observe(SimpleNamespace(target="toolhive:" + repair.NAME))


def test_exact_approved_unused_plan_can_resume_but_not_an_existing_effect(tmp_path):
    store = repair.SQLiteGuardStore(tmp_path / "guard.db")
    guard = repair.GuardCore(store.runtime_state(), store=store)
    plan = repair.TaskPlan("fixed-code-recovery", "production_deploy", "toolhive:" + repair.NAME,
                          canon_revision="current", effect_id="fixed-code-recovery:create")
    repair.approve_unused_plan(store, guard, plan)
    assert store.is_approved_for(plan.run_id, plan.action, plan.target, "current", plan.effect_id)
    assert store.get_effect(plan.effect_id) is None
    # A second Issue on the same revision can resume after the final idle
    # check aborts; it cannot manufacture another approval or effect.
    with patch.object(store, "request_approval", side_effect=AssertionError("duplicate approval")):
        repair.approve_unused_plan(store, guard, plan)
    changed = repair.TaskPlan(plan.run_id, plan.action, plan.target,
                             canon_revision="changed", effect_id=plan.effect_id)
    with pytest.raises(repair.Denied, match="GUARD_REQUEST_DENIED"):
        repair.approve_unused_plan(store, guard, changed)
    with patch.object(store, "get_effect", return_value=object()):
        with pytest.raises(repair.Denied, match="CODE_EFFECT_ALREADY_RECORDED"):
            repair.approve_unused_plan(store, guard, plan)
