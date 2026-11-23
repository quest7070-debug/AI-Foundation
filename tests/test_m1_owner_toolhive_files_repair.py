"""One synthetic fixed-owner repair test; no M1 commands, models or services."""
import json
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from ai_foundation.core import CanonContract, GuardState, TaskPlan
from ai_foundation.guard import GuardCore
from scripts import m1_owner_toolhive_files_repair as repair


def owner_event(sha="a"*40):
    issue = {
        "number": 123, "state": "open", "user": {"login":repair.OWNER},
        "title": repair.PREFIX + sha,
        "body": "<!-- foundation-m1-toolhive-files-repair:v1:" + sha + " -->",
    }
    event = {"action": "opened", "repository": {"full_name": repair.REPO},
             "sender": {"login": repair.OWNER}, "issue": issue}
    env = {"GITHUB_REPOSITORY":repair.REPO, "GITHUB_WORKFLOW":repair.WORKFLOW,
           "GITHUB_EVENT_NAME":"issues","GITHUB_ACTOR":repair.OWNER,"GITHUB_SHA":sha}
    return event, env


def test_fixed_owner_issue_never_accepts_caller_command_or_changed_identity():
    event, env = owner_event()
    with patch.object(repair.platform,"system",return_value="Darwin"), \
         patch.object(repair.platform,"machine",return_value="arm64"), \
         patch.object(repair.os,"getuid",return_value=501), \
         patch.object(repair.os,"geteuid",return_value=501):
        assert repair.check_event(event,env) == (123,"a"*40)
        assert repair.check_event(event,env,event["issue"]) == (123,"a"*40)
        for mutation in (
            lambda: {**event,"sender":{"login":"other"}},
            lambda: {**event,"issue":{**event["issue"],"body":
                     event["issue"]["body"]+"\nexecute=rm -rf"}},
            lambda: {**event,"issue":{**event["issue"],"user":{"login":"other"}}},
        ):
            with pytest.raises(repair.Denied):
                repair.check_event(mutation(),env)
        with pytest.raises(repair.Denied):
            repair.check_event(event,env,{**event["issue"],"state":"closed"})


def test_exact_pinned_workload_status_and_guard_one_dispatch(monkeypatch):
    calls=[]
    state={"value":"unhealthy"}
    def cli(argv,**kw):
        calls.append(tuple(argv))
        if argv[1]=="status":
            return SimpleNamespace(returncode=0,stdout=json.dumps({
                "name":repair.NAME,"package":"docker.io/mcp/filesystem:1.0.2",
                "status":state["value"],"url":"OWNER_PRIVATE_URL"}),stderr="SECRET")
        if argv[1]=="image":
            assert argv==["/bin/sh","image","inspect","--format","{{.Id}}",
                         "docker.io/mcp/filesystem:1.0.2"]
            return SimpleNamespace(returncode=0,
                                   stdout=repair.EXPECTED_IMAGE_ID+"\n")
        assert argv==["/owner/thv","start",repair.NAME]
        state["value"]="running"
        return subprocess.CompletedProcess(argv,0,b"",b"PRIVATE")
    monkeypatch.setattr(repair,"DOCKER_BINARIES",("/bin/sh",))
    monkeypatch.setattr(repair.subprocess,"run",cli)
    port=repair.FixedFilesWorkload("/owner/thv")
    guard=GuardCore(GuardState(approvals={"synthetic-owner"}))
    canon=CanonContract("foundation-toolhive-files","fixed-canon")
    plan=TaskPlan("synthetic-owner","production_deploy","toolhive:"+repair.NAME,
                  canon_revision="fixed-canon",target_precondition="UNHEALTHY",
                  exclusive_target=True,effect_id="synthetic-files-repair")
    assert guard.execute(plan,canon,port,"RUNNING")=="VERIFIED_COMPLETE"
    assert port.dispatches==1
    assert calls.count(("/owner/thv","start",repair.NAME))==1
    assert calls[0]==("/owner/thv","status",repair.NAME,"--format","json")
    assert guard.execute(plan,canon,port,"RUNNING")=="VERIFIED_COMPLETE"
    assert calls.count(("/owner/thv","start",repair.NAME))==1

    with patch.object(repair.subprocess,"run",return_value=SimpleNamespace(
         returncode=0,stdout=json.dumps({
             "name":"different-server","package":"io.github.stacklok/filesystem",
             "status":"running"}),stderr="PRIVATE")):
        with pytest.raises(repair.Denied):
            repair.cli_status("/owner/thv")
    with patch.object(repair.subprocess,"run",return_value=SimpleNamespace(
         returncode=0,stdout=json.dumps({
             "name":repair.NAME,"package":"unknown/remote",
             "status":"unhealthy"}),stderr="PRIVATE")):
        with pytest.raises(repair.Denied):
            repair.cli_status("/owner/thv")


@pytest.mark.parametrize("image", [
    "mcp/filesystem:1.0.2",
    "docker.io/mcp/filesystem:1.0.2",
    "sha256:720393842ef8b0f33713a42e2eebda51ff600756c19d53e1244645ec59496fef",
    "other-registry.local/pinned-filesystem:v1",
])
def test_v049_docker_image_id_attestation(image, monkeypatch):
    monkeypatch.setattr(repair,"DOCKER_BINARIES",("/bin/sh",))
    requests=[]
    def cmd(argv,**kw):
        requests.append(tuple(argv))
        if argv[1]=="status":
            return SimpleNamespace(returncode=0,stdout=json.dumps({
                "name":repair.NAME,"status":"unhealthy","package":image,
                "url":"OWNER_PRIVATE_URL"}),stderr="SECRET")
        assert argv==["/bin/sh","image","inspect","--format","{{.Id}}",image]
        return SimpleNamespace(returncode=0,stdout=repair.EXPECTED_IMAGE_ID+"\n")
    with patch.object(repair.subprocess,"run",side_effect=cmd):
        assert repair.cli_status("/pinned/thv") == "unhealthy"
    assert len(requests)==2

    # Arbitrary image spelling is not an authorization: only matching
    # Docker image content digest may pass, with no shell/pull/run.
    def mismatched(argv,**kw):
        if argv[1]=="status":
            return SimpleNamespace(returncode=0,stdout=json.dumps({
                "name":repair.NAME,"status":"unhealthy","package":image}))
        return SimpleNamespace(returncode=0,stdout="sha256:"+"0"*64)
    with patch.object(repair.subprocess,"run",side_effect=mismatched):
        with pytest.raises(repair.Denied,match="TOOLHIVE_DOCKER_IMAGE_ID_MISMATCH"):
            repair.cli_status("/pinned/thv")


def test_image_reference_rejects_argument_injection_and_missing_docker(monkeypatch):
    monkeypatch.setattr(repair,"DOCKER_BINARIES",("/bin/sh",))
    with pytest.raises(repair.Denied,match="TOOLHIVE_IMAGE_REFERENCE_INVALID"):
        repair.pinned_container_image("--format=hostile")
    with pytest.raises(repair.Denied,match="TOOLHIVE_IMAGE_REFERENCE_INVALID"):
        repair.pinned_container_image("valid; rm -rf .")
    monkeypatch.setattr(repair,"DOCKER_BINARIES",("/no/such/fixed/docker",))
    with pytest.raises(repair.Denied,match="PINNED_DOCKER_INSPECT_UNAVAILABLE"):
        repair.pinned_container_image("mcp/filesystem:1.0.2")


@pytest.mark.parametrize("changes,accepted", [
    ({}, True),
    ({"name": "other"}, False),
    ({"image": "evil.example/remote:latest"}, False),
    ({"remote_url": "https://private.invalid"}, False),
    ({"isolate_network": False}, False),
])
def test_empty_nonrunning_package_requires_saved_fixed_identity(monkeypatch, changes, accepted):
    monkeypatch.setattr(repair, "DOCKER_BINARIES", ("/bin/sh",))
    exported = []
    def cli(argv, **kw):
        if argv[1] == "status":
            return SimpleNamespace(returncode=0, stdout=json.dumps({
                "name": repair.NAME, "status": "unhealthy", "package": ""}))
        if argv[1] == "image":
            return SimpleNamespace(returncode=0, stdout=(
                repair.EXPECTED_IMAGE_ID if argv[-1] == "docker.io/mcp/filesystem:1.0.2"
                else "sha256:" + "0" * 64))
        assert argv[:3] == ["/pinned/thv", "export", repair.NAME]
        path = repair.Path(argv[3])
        assert path.parent.stat().st_mode & 0o077 == 0
        exported.append(path)
        path.write_text(json.dumps({
            "name": repair.NAME, "image": "docker.io/mcp/filesystem:1.0.2",
            "isolate_network": True, **changes}))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(repair.subprocess, "run", cli)
    if accepted:
        assert repair.cli_status("/pinned/thv") == "unhealthy"
    else:
        with pytest.raises(repair.Denied, match="TOOLHIVE_(SAVED_CONFIG_IDENTITY_UNVERIFIED|DOCKER_IMAGE_ID_MISMATCH)"):
            repair.cli_status("/pinned/thv")
    assert len(exported) == 1 and not exported[0].parent.exists()


def test_running_empty_package_cannot_claim_verified_running(monkeypatch):
    monkeypatch.setattr(repair.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=0, stdout=json.dumps({
            "name": repair.NAME, "status": "running", "package": ""})))
    with pytest.raises(repair.Denied, match="TOOLHIVE_IMAGE_REFERENCE_INVALID"):
        repair.cli_status("/pinned/thv")


def test_persistent_start_does_not_inherit_ci_cleanup_or_github_credential(monkeypatch):
    monkeypatch.setenv("RUNNER_TRACKING_ID", "synthetic-job")
    monkeypatch.setenv("GITHUB_TOKEN", "synthetic-credential")
    monkeypatch.setenv("FOUNDATION_EXISTING_CONFIG", "preserved")
    calls = []
    def cli(argv, **kw):
        calls.append(argv)
        assert argv == ["/owner/thv", "start", repair.NAME]
        assert "RUNNER_TRACKING_ID" not in kw["env"]
        assert "GITHUB_TOKEN" not in kw["env"]
        assert kw["env"]["FOUNDATION_EXISTING_CONFIG"] == "preserved"
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(repair.subprocess, "run", cli)
    port = repair.FixedFilesWorkload("/owner/thv")
    plan = SimpleNamespace(target="toolhive:" + repair.NAME,
                           action="production_deploy", target_precondition="UNHEALTHY")
    port.execute(plan)
    assert repair.os.environ["RUNNER_TRACKING_ID"] == "synthetic-job"
    assert repair.os.environ["GITHUB_TOKEN"] == "synthetic-credential"
    with pytest.raises(repair.Denied):
        port.execute(plan)
    assert port.dispatches == 1 and len(calls) == 1


@pytest.mark.parametrize("health,expected", [
    ("proxy process not running: PRIVATE", "PROXY_NOT_RUNNING"),
    ("workload status mismatch: PRIVATE", "CONTAINER_STATUS_MISMATCH"),
    ("workload PRIVATE not found in runtime", "CONTAINER_NOT_FOUND"),
    ("PRIVATE", "OTHER"),
    ("", "UNREPORTED"),
])
def test_health_receipt_never_exports_private_text(health, expected):
    assert repair.health_reason({"health": health}) == expected
