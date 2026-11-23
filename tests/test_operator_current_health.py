"""Runtime health remains separate from immutable historical Guard/Work failures."""
import json

from ai_foundation.human_view import from_snapshot
from ai_foundation.human_renderer import render
from ai_foundation.operator_mcp_tools import OperatorMcpTools
from scripts import foundation_mcp_stdio as stdio


class Snapshot:
    def __init__(self, *, ready=True, services=None, work=None, attention=None):
        self.data = {
            "ready": ready,
            "services": services if services is not None else
                        [{"name": "a", "ok": True}, {"name": "b", "ok": True}],
            "work": work if work is not None else {"FAILED": 2, "RUNNING": 0},
            "attention": attention if attention is not None else
                         [{"kind": "work", "status": "FAILED"}],
            "waiting_human": 0,
            "effects": {"FAILED": 1},
        }

    def as_dict(self):
        return self.data


def test_retained_failed_history_does_not_mask_observed_runtime_readiness():
    view = from_snapshot(Snapshot())
    assert view.state == "FAILED"
    assert view.runtime_health == "READY"
    page = render(view)
    assert "CURRENT RUNTIME HEALTH" in page
    assert "<h1>READY</h1>" in page
    assert "OPERATOR WORK / EFFECT STATE · FAILED" in page


def test_missing_services_never_claim_ready_and_failed_service_is_degraded():
    assert from_snapshot(Snapshot(services=[])).runtime_health == "UNVERIFIED"
    assert from_snapshot(Snapshot(ready=False)).runtime_health == "DEGRADED"
    assert from_snapshot(Snapshot(services=[{"ok": False}])).runtime_health == "DEGRADED"
    assert from_snapshot(Snapshot(services=[{"ok": None}])).runtime_health == "UNVERIFIED"
    assert from_snapshot(Snapshot(services=[{"ok": True}, {"ok": None}])).runtime_health == "UNVERIFIED"


def test_mcp_readonly_status_retains_history_with_independent_runtime_health():
    class Operator:
        def human_payload(self):
            return {
                "state": "FAILED",
                "runtime_health": "READY",
                "state_diagnostics": {"failed_work_window": 2,
                                      "failed_effect_window": 1,
                                      "dismissed_failed_notices_window": 3},
                "development": {"source": "CURRENT_GUARD_WORK_SNAPSHOT",
                                "work_failed": 2},
                "services": [{"ok": True}], "notices": [],
            }

    tools = OperatorMcpTools(Operator(), authorize=lambda *_args: True)
    result = tools.foundation_status(object())
    assert result["runtime_health"] == "READY"
    assert result["state"] == "FAILED"
    assert result["work_failed"] == 2
    assert result["failed_effect_history"] == 1
    assert result["dismissed_failed_notices"] == 3


def test_stdio_proxy_allowlists_health_and_count_not_private_data(monkeypatch):
    payload = {"state": "FAILED", "runtime_health": "READY",
               "state_diagnostics": {"failed_work_window": 2,
                                     "failed_effect_window": 1,
                                     "dismissed_failed_notices_window": 3,
                                     "private": "SECRET"},
               "services": [{"ok": True, "secret": "SECRET"}],
               "notices": [], "private": "SECRET"}
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def read(self, _size): return json.dumps(payload).encode()
    class Opener:
        def open(self, _req, timeout):
            assert timeout == 4
            return Response()
    monkeypatch.setattr(stdio.request, "build_opener", lambda *_args: Opener())
    safe = stdio.OperatorAggregateProxy().human_payload()
    assert safe["runtime_health"] == "READY"
    assert safe["state_diagnostics"]["failed_effect_window"] == 1
    assert "SECRET" not in json.dumps(safe)
