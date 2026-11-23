"""Fixed KLM Google read-only transport probe: no owner token/source leaks."""
from scripts import m1_klm_live_readonly_probe as probe
from scripts import m1_development_bridge as bridge


class Inbox:
    def values(self):
        return [["Fixture"], ["1"]], 10


def test_fixed_probe_verifies_only_three_gets_and_never_exports_cursor():
    calls=[]
    def token(): calls.append("refresh");return "PRIVATE_TOKEN"
    def drive(path,params):
        calls.append((path,params))
        return {"startPageToken":"PRIVATE_CURSOR"}
    row=probe.inspect_transport(token,Inbox(),drive)
    assert row=={"status":"LIVE_READONLY_APIS_VERIFIED",
                 "phase":"COMPLETE","fixed_gets":3,"model_calls":0,"drive_mutations":0}
    assert calls==["refresh",("/drive/v3/changes/startPageToken",
                             {"fields":"startPageToken"})]
    assert "PRIVATE" not in str(row)
    assert bridge.parse_request("Foundation M1 Bridge: klm-live-readonly",
        '<!-- foundation-m1-bridge: {"version":1,"operation":"klm-live-readonly"} -->')=="klm-live-readonly"


def test_fixed_probe_classifies_refresh_and_drive_failures_without_secrets():
    def refresh_error():
        raise RuntimeError("OAUTH_HTTP_400")
    never=lambda *args:(_ for _ in ()).throw(AssertionError("no late API"))
    row=probe.inspect_transport(refresh_error,Inbox(),never)
    assert row["phase"]=="TOKEN_REFRESH" and row["reason"]=="OAUTH_HTTP_400"
    assert row["fixed_gets"]==0 and row["model_calls"]==0
    row=probe.inspect_transport(lambda:None,Inbox(),
        lambda *args:(_ for _ in ()).throw(
            RuntimeError("PRIVATE_ACCESS_TOKEN: /Users/owner/secret")))
    assert row["phase"]=="DRIVE_CHANGES_READ" and row["reason"]=="UNCLASSIFIED"
    assert "PRIVATE" not in str(row) and "secret" not in str(row)


def test_inbox_failure_stops_before_drive_and_redacts_private_error():
    class FailingInbox:
        def values(self):
            raise RuntimeError("PRIVATE_INBOX_CELL: /Users/owner/secret")

    def forbidden_drive(*args):
        raise AssertionError("Drive must not be called after Inbox failure")

    row = probe.inspect_transport(lambda: "PRIVATE_TOKEN", FailingInbox(), forbidden_drive)
    assert row["status"] == "BLOCKED"
    assert row["phase"] == "INBOX_READ"
    assert row["reason"] == "UNCLASSIFIED"
    assert row["model_calls"] == 0 and row["drive_mutations"] == 0
    assert "PRIVATE" not in str(row) and "secret" not in str(row)


def test_owner_bridge_workflow_admits_exact_readonly_title():
    # Parser acceptance without the workflow gate silently skips the M1 probe.
    from pathlib import Path
    workflow = (Path(__file__).resolve().parents[1] /
                ".github/workflows/m1-development-bridge.yml").read_text()
    expected = "github.event.issue.title == 'Foundation M1 Bridge: klm-live-readonly'"
    assert workflow.count(expected) == 1
    assert "github.event.issue.user.login == 'quest7070-debug'" in workflow
    assert "runs-on: [self-hosted, macOS, ARM64]" in workflow


def test_hung_owner_keychain_probe_stops_only_fixed_child_and_redacts_stderr():
    from types import SimpleNamespace
    from unittest.mock import Mock
    import subprocess
    called=[]
    def blocked(argv,**kw):
        called.append((argv,kw))
        raise subprocess.TimeoutExpired(cmd=argv,timeout=55,
                                        stderr=b"KLM_PHASE:OWNER_CONFIG\nKLM_PHASE:TOKEN_REFRESH\nPRIVATE_TOKEN=leak\n")
    row=bridge.bounded_klm_readonly_helper(run=blocked)
    assert row["status"]=="BLOCKED"
    assert row["reason"]=="READONLY_HELPER_TIMEOUT"
    assert row["phase"]=="TOKEN_REFRESH"
    assert row["model_calls"]==0 and row["drive_mutations"]==0
    assert "PRIVATE_TOKEN" not in str(row)
    assert called[0][1]["timeout"]==55
    assert "GITHUB_TOKEN" not in called[0][1]["env"]


def test_fixed_owner_probe_result_only_can_be_reported():
    import json
    from types import SimpleNamespace
    raw={"status":"BLOCKED","phase":"INBOX_READ",
         "error_type":"RuntimeError","reason":"DRIVE_HTTP_403",
         "model_calls":0,"drive_mutations":0,
         "private_source":"MUST_NOT_ESCAPE"}
    row=bridge.bounded_klm_readonly_helper(
        run=lambda *a,**kw:SimpleNamespace(returncode=0,stdout=json.dumps(raw),stderr=""))
    assert row["phase"]=="INBOX_READ"
    assert row["reason"]=="DRIVE_HTTP_403"
    assert "MUST_NOT_ESCAPE" not in str(row)


def test_native_oauth_callback_reports_fixed_keychain_and_http_phases():
    import json
    from ai_foundation.klm_drive_auth import ReadonlyGoogleToken, BINDING, SCOPES
    seen=[]
    class Store:
        def available(self, key):
            assert key==BINDING
            return True
        def load(self, key):
            return json.dumps({"scopes": sorted(SCOPES),
                               "client_id":"synthetic",
                               "client_secret":"PRIVATE_SECRET",
                               "refresh_token":"PRIVATE_REFRESH"})
    def exchange(row):
        assert row["refresh_token"]=="PRIVATE_REFRESH"
        return {"access_token":"PRIVATE_ACCESS","expires_in":3600}
    token=ReadonlyGoogleToken(Store(),exchange=exchange,clock=lambda:1000,
                              on_phase=seen.append)
    assert token()=="PRIVATE_ACCESS"
    assert seen==["KEYCHAIN_LOAD","OAUTH_REFRESH_HTTP"]
    assert token()=="PRIVATE_ACCESS"
    assert seen==["KEYCHAIN_LOAD","OAUTH_REFRESH_HTTP"]
    assert bridge._klm_timeout_phase(
        b"KLM_PHASE:KEYCHAIN_LOAD\nPRIVATE_SECRET\n")=="KEYCHAIN_LOAD"
    assert bridge._klm_timeout_phase(
        b"KLM_PHASE:OAUTH_REFRESH_HTTP\nPRIVATE_ACCESS\n")=="OAUTH_REFRESH_HTTP"
