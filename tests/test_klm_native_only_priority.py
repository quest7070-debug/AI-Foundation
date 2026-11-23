"""Development priority is for actually actionable local9B work, not Native-only queue labels.

No real provider/host/Native effect. Synthetic owner Issues + result directory.
"""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

from ai_foundation.klm_drive_work import read_development_state


def issue(number, body):
    return dict(number=number, body=body, state="OPEN",
                updatedAt="2026-11-07T08:00:00Z",
                labels=[{"name":"foundation-autodev:ready"}])


def native_marker():
    return ('<!-- foundation-autodev: '+json.dumps({
        "paths":["src/ai_foundation/paseo_foundation_runtime.py"],
        "depends_on":[],
        "native_handoff":{
            "anchor":"Native signed ingress canary",
            "target":"src/ai_foundation/paseo_foundation_runtime.py",
            "calls":[["client.construct",["named-operator-native-test"]]],
            "acceptance_paths":["tests/test_paseo_signed_ingress_slot.py"]
        }
    },separators=(",",":"))+' -->')


def fake_bridge(issues, *, executable=()):
    executable=set(executable)
    def issue_task(row):
        if row["number"] not in executable:
            raise ValueError("SCOPED_TASK_CONTRACT_REQUIRED")
        return {"id":f'issue-{row["number"]}-'+'a'*16}
    return SimpleNamespace(
        REPOSITORY="quest7070-dev/AI-Foundation",
        READY_LABEL="foundation-autodev:ready",
        _gh=lambda *args: issues,
        issue_task=issue_task,
        previous_issue_attempt=lambda inbox, number: False,
    )


@pytest.fixture
def worker_root(tmp_path):
    (tmp_path/"inbox").mkdir()
    (tmp_path/"results").mkdir()
    return tmp_path


def observation(root, issues, *, executable=()):
    policy=SimpleNamespace(admission=lambda item: {"status":"ELIGIBLE"})
    return read_development_state(root,fake_bridge(issues,executable=executable),
                                  policy,now=lambda:100.0)


def test_native_only_ready_issue_does_not_starve_local9b_klm(worker_root):
    native=issue(35,native_marker())
    state=observation(worker_root,[native])
    assert state.complete
    assert state.approved_pending == 0
    assert state.native_only_approved == 1
    assert state.idle(100.0)


def test_mixed_native_and_runnable_development_still_defers(worker_root):
    native=issue(35,native_marker())
    live=issue(500,"approved finite task")
    state=observation(worker_root,[native,live],executable={500})
    assert state.complete
    assert state.approved_pending == 1
    assert state.native_only_approved == 1
    assert not state.idle(100.0)


def test_malformed_approved_issue_remains_conservatively_pending(worker_root):
    malformed=issue(499,"Missing all contracts")
    state=observation(worker_root,[malformed])
    assert state.approved_pending == 1
    assert state.native_only_approved == 0
    assert not state.idle(100.0)


def test_native_marker_cannot_masquerade_if_mixed_with_finite_recipe(worker_root):
    ticks=chr(96)*3
    suspicious=issue(501,native_marker()+"\n"+ticks+"foundation-autodev-task\n{}\n"+ticks)
    state=observation(worker_root,[suspicious])
    assert state.approved_pending == 1
    assert state.native_only_approved == 0


@pytest.mark.parametrize("body",[
    '<!-- foundation-autodev: {"native_handoff":true} -->',
    '<!-- foundation-autodev: {"paths":[],"depends_on":[],"native_handoff":{}} -->',
    '<!-- foundation-autodev: {"paths":["x"],"depends_on":[],"native_handoff":{"target":"x"}} -->',
    '<!-- foundation-autodev: {"paths":["x"],"depends_on":[],"native_handoff":{"target":"x","anchor":"ok","calls":[],"acceptance_paths":[]}} -->',
    'native_handoff is mentioned but no bounded JSON marker exists',
    native_marker() + native_marker(),
])
def test_untrusted_or_incomplete_native_claims_still_block(worker_root,body):
    state=observation(worker_root,[issue(35,body)])
    assert state.approved_pending == 1
    assert state.native_only_approved == 0
    assert not state.idle(100.0)


def test_unsupported_worker_issue_with_started_effect_remains_uncertain(worker_root):
    native=issue(35,native_marker())
    (worker_root/"results"/"issue-35-a.started").write_text("start")
    state=observation(worker_root,[native])
    assert state.active_or_uncertain==1
    assert not state.idle(100.0)


def test_unknown_source_coverage_cannot_claim_idle(worker_root):
    native=issue(35,native_marker())
    bridge=fake_bridge([native])
    bridge._gh=lambda *a: (_ for _ in ()).throw(OSError("source unavailable"))
    policy=SimpleNamespace(admission=lambda issue:{"status":"ELIGIBLE"})
    state=read_development_state(worker_root,bridge,policy,now=lambda:100.0)
    assert not state.complete
    assert not state.idle(100.0)



def test_duplicate_native_json_keys_never_remove_dev_priority(worker_root):
    marker='<!-- foundation-autodev: {"paths":["x"],"paths":["src/ai_foundation/paseo_foundation_runtime.py"],"depends_on":[],"native_handoff":{}} -->'
    state=observation(worker_root,[issue(35,marker)])
    assert state.approved_pending==1
    assert state.native_only_approved==0
    assert not state.idle(100.0)

def test_incomplete_ready_identity_cannot_authorize_queued_only_fairness(worker_root):
    unversioned=issue(505, "approved finite task")
    unversioned.pop("updatedAt")
    observed=observation(worker_root, [unversioned], executable={505})
    assert observed.complete
    assert observed.approved_pending==1
    assert not observed.queued_only_fresh(100.0)
    assert observed.queue_fingerprint==""
