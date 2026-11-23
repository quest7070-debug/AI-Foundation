"""Synthetic MCP host-adapter checks: real SQLite Guard, no MCP listener."""
import pytest

from ai_foundation.core import GuardState
from ai_foundation.guard import GuardCore
from ai_foundation.operator_actions import OperatorActions
from ai_foundation.operator_mcp_tools import OperatorMcpTools
from ai_foundation.operator_server import OperatorApplication
from ai_foundation.productization import FoundationConfig
from ai_foundation.store import SQLiteGuardStore


def setup(tmp_path, *, allowed=None):
    root = tmp_path / "data"
    root.mkdir()
    config = FoundationConfig(str(root.resolve()))
    store = SQLiteGuardStore(root / config.guard_db)
    guard = GuardCore(store.load(), store=store)
    app = OperatorApplication(config, OperatorActions(guard))
    actor = object()
    allowed = allowed if allowed is not None else {
        "foundation_status", "approval_requests", "review_candidate",
        "submit_decision:AUTHORIZE", "submit_decision:DENY",
    }
    port = OperatorMcpTools(
        app, authorize=lambda identity, tool, _run:
        identity is actor and tool in allowed,
    )
    return store, guard, app, actor, port


def test_no_host_authority_fails_closed(tmp_path):
    store, _, _, actor, port = setup(tmp_path)
    store.request_approval("run-1", "production_deploy", "secret-target",
                           "revision-1", "effect-1")
    with pytest.raises(ValueError, match="authorizer"):
        OperatorMcpTools(None, authorize=None)
    for method in (port.foundation_status, port.approval_requests):
        with pytest.raises(PermissionError):
            method(None)
        with pytest.raises(PermissionError):
            method(object())
    with pytest.raises(PermissionError):
        port.submit_decision(object(), "run-1", "a" * 64, "AUTHORIZE")
    assert not store.is_approved("run-1")


def test_read_only_tools_redact_target_and_do_not_delegate(tmp_path):
    store, _, app, actor, port = setup(tmp_path)
    store.request_approval("run-2", "send_email", "private-recipient",
                           "revision-2", "effect-2")
    requests = port.approval_requests(actor)
    assert len(requests) == 1
    row = requests[0]
    assert row["run_id"] == "run-2"
    assert row["action"] == "send_email"
    assert row["actionable"] is True
    assert len(row["request_ref"]) == 64
    assert "private-recipient" not in str(requests)
    result = port.review_candidate(actor, "run-2", row["request_ref"])
    assert result == {"run_id": "run-2", "current": True,
                      "requires_explicit_authority": True,
                      "authorized": False}
    status = port.foundation_status(actor)
    assert status["guard_pending"] == 1
    assert status["approved_humanmodel_view"] == "UNVERIFIED"
    assert status["worker_runtime"] == "UNVERIFIED"
    assert "private-recipient" not in str(status)
    assert "secret" not in str(status)
    assert not store.is_approved("run-2")
    assert next(n for n in app.human_payload()["notices"]
                if n["subject"] == "run-2")["level"] == 4


def test_stale_replay_and_retarget_fail_against_same_guard(tmp_path):
    store, guard, app, actor, port = setup(tmp_path)
    store.request_approval("run-3", "production_deploy", "original",
                           "rev-1", "effect-3")
    old = port.approval_requests(actor)[0]["request_ref"]
    store.request_approval("run-3", "production_deploy", "changed",
                           "rev-1", "effect-3")
    new = port.approval_requests(actor)[0]["request_ref"]
    assert old != new
    assert not port.review_candidate(actor, "run-3", old)["current"]
    assert port.submit_decision(actor, "run-3", old, "AUTHORIZE")["ok"] is False
    assert not store.is_approved("run-3")
    assert port.submit_decision(actor, "run-3", new, "AUTHORIZE") == {
        "ok": True, "status": "APPROVED",
    }
    assert store.is_approved("run-3")
    assert port.submit_decision(actor, "run-3", new, "AUTHORIZE")["ok"] is False
    assert not any(r["run_id"] == "run-3" for r in port.approval_requests(actor))


def test_mcp_deny_and_ui_observe_same_canonical_record(tmp_path):
    store, _, app, actor, port = setup(tmp_path)
    store.request_approval("run-4", "delete", "test-only", "rev-1", "effect-4")
    ref = port.approval_requests(actor)[0]["request_ref"]
    assert port.submit_decision(actor, "run-4", ref, "DENY") == {
        "ok": True, "status": "CANCELLED",
    }
    assert store.is_cancelled("run-4")
    assert port.submit_decision(actor, "run-4", ref, "DENY")["ok"] is False
    assert not any(n["subject"] == "run-4" and n["status"] == "WAITING_HUMAN"
                   for n in app.human_payload()["notices"])


def test_write_requires_independent_exact_decision_delegation(tmp_path):
    store, _, _, actor, port = setup(
        tmp_path, allowed={"foundation_status", "approval_requests", "review_candidate"},
    )
    store.request_approval("run-5", "send_email", "private",
                           "rev-1", "effect-5")
    ref = port.approval_requests(actor)[0]["request_ref"]
    assert port.review_candidate(actor, "run-5", ref)["current"]
    with pytest.raises(PermissionError):
        port.submit_decision(actor, "run-5", ref, "AUTHORIZE")
    with pytest.raises(PermissionError):
        port.submit_decision(actor, "run-5", ref, "DENY")
    with pytest.raises(ValueError, match="AUTHORIZE or DENY"):
        port.submit_decision(actor, "run-5", ref, "PROMOTE")
    assert not store.is_approved("run-5")
    assert not store.is_cancelled("run-5")


def test_unbound_legacy_and_in_memory_fallback_cannot_be_used(tmp_path):
    store, _, app, actor, port = setup(tmp_path)
    store.request_approval("run-6", "send_email", "legacy")
    row = port.approval_requests(actor)[0]
    assert not row["actionable"] and not row["request_ref"]
    assert port.submit_decision(actor, "run-6", "a" * 64, "AUTHORIZE")["ok"] is False
    assert not store.is_approved("run-6")
    # In-memory Guard fixtures deliberately support a legacy UI path.
    # MCP must never inherit that broad run-only authorization.
    app.actions = OperatorActions(GuardCore(GuardState()))
    assert port.submit_decision(actor, "run-6", "a" * 64, "AUTHORIZE")["ok"] is False



def test_mcp_status_projects_only_owner_observed_worker_and_klm_codes(tmp_path):
    _, _, app, actor, port = setup(tmp_path)
    original = app.human_payload
    def payload():
        row = original()
        row["development"] = {
            "source": "CURRENT_GUARD_WORK_SNAPSHOT+M1_OWNER_RUNTIME",
            "local9b_worker": "SCHEDULED_IDLE",
            "local9b_queue_state": "NO_QUEUED_TASK",
            "klm_status": "CURRENT",
            "owner_private": "SECRET_OWNER_SOURCE",
        }
        return row
    app.human_payload = payload
    result = port.foundation_status(actor)
    assert result["worker_runtime"] == "SCHEDULED_IDLE"
    assert result["worker_queue"] == "NO_QUEUED_TASK"
    assert result["klm_runtime"] == "CURRENT"
    assert result["approved_humanmodel_view"] == "UNVERIFIED"
    assert "SECRET" not in str(result)
    def corrupted():
        row = payload()
        row["development"].update(
            source="UNTRUSTED",
            local9b_worker="SECRET_WORKER",
            klm_status="SECRET_KLM",
        )
        return row
    app.human_payload = corrupted
    redacted = port.foundation_status(actor)
    assert redacted["worker_runtime"] == "UNVERIFIED"
    assert redacted["worker_queue"] == "UNVERIFIED"
    assert redacted["klm_runtime"] == "UNVERIFIED"
    assert "SECRET" not in str(redacted)


def test_dismissed_notice_cannot_hide_pending_guard_work_from_mcp(tmp_path):
    store, _, app, actor, port = setup(tmp_path)
    store.request_approval("run-hidden", "send_email", "private-target",
                           "revision-hidden", "effect-hidden")
    assert port.foundation_status(actor)["guard_pending"] == 1
    app.dismissals.dismiss("run-hidden", "WAITING_HUMAN")
    original = app.human_payload

    def observed():
        state = original()
        state["development"]["work_failed"] = 2
        state["development"]["work_uncertain"] = 1
        state["services"] = [
            {"name": "FILES", "ok": True},
            {"name": "LOCAL", "ok": False},
            {"name": "UNTESTED", "ok": None},
        ]
        assert not any(n["subject"] == "run-hidden" for n in state["notices"])
        return state

    app.human_payload = observed
    result = port.foundation_status(actor)
    assert result["guard_pending"] == 1
    assert result["work_failed"] == 2
    assert result["work_uncertain"] == 1
    assert result["services_ok"] == 1
    assert result["services_down"] == 1
    assert result["services_unverified"] == 1
    assert result["services_unavailable"] == 2  # existing compatibility key
    assert "private-target" not in str(result)


def test_untrusted_mcp_development_counts_fail_closed(tmp_path):
    _, _, app, actor, port = setup(tmp_path)
    original = app.human_payload

    def stale():
        state = original()
        state["development"].update(source="UNTRUSTED",
                                    work_failed=999, work_uncertain=888,
                                    guard_actionable=777)
        return state

    app.human_payload = stale
    result = port.foundation_status(actor)
    assert result["work_failed"] is None
    assert result["work_uncertain"] is None
    assert result["guard_pending"] == 0


def test_owner_work_backlog_is_observed_without_minting_admission(tmp_path):
    _, _, app, actor, port = setup(tmp_path)
    app.development_status = lambda: {
        "state": "SCHEDULED_IDLE",
        "queue_state": "NO_QUEUED_TASK",
        "development_backlog": {
            "source": "CURRENT_OWNER_WORK",
            "review_required": 7, "admitted": 3, "failed_local_attempts": 5,
        },
    }
    result = port.foundation_status(actor)
    assert (result["code_review_required"], result["code_admitted_requests"],
            result["code_failed_local_attempts"]) == (7, 3, 5)
    assert result["guard_pending"] == 0
    assert result["worker_runtime"] == "SCHEDULED_IDLE"
    # An unauthenticated/malformed runtime source cannot promote count data.
    app.development_status = lambda: {
        "state": "SCHEDULED_IDLE", "queue_state": "NO_QUEUED_TASK",
        "development_backlog": {
            "source": "UNTRUSTED", "review_required": 0,
            "admitted": 999, "failed_local_attempts": 0,
        },
    }
    invalid = port.foundation_status(actor)
    assert invalid["code_review_required"] is None
    assert invalid["code_admitted_requests"] is None
