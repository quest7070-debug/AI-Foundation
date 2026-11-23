"""Source-bound overview: durable failures survive notice dismissal; unknown probes stay unknown."""
from ai_foundation.operator_server import OperatorApplication
from ai_foundation.human_view import from_snapshot
from ai_foundation.human_renderer import render


class _Snapshot:
    def as_dict(self):
        return {
            "ready": True,
            "waiting_human": 0,
            "attention": [],  # dismissed notices do not erase Work facts
            "work": {"FAILED": 2, "UNCERTAIN": 1, "RUNNING": 0},
            "services": (
                {"name": "FILES", "ok": True},
                {"name": "LOCAL COMPUTE", "ok": False},
                {"name": "UNKNOWN", "ok": None},
            ),
        }


def test_overview_renders_persisted_work_and_observed_service_health():
    app = object.__new__(OperatorApplication)
    app.humanmodel_factory_registered = False
    app.question_resolver = None
    app.host_question_resolver = None
    app.development_status = None
    snapshot = _Snapshot()
    state = app.development_state(snapshot)
    assert state["work_failed"] == 2
    assert state["work_uncertain"] == 1
    page = render(from_snapshot(snapshot, development=state), "responsive")
    assert "\u5931\u6557 2 \u4ef6" in page
    assert "\u4e0d\u78ba\u5b9f 1 \u4ef6" in page
    assert "1 / 2 READY" not in page


def test_overview_does_not_invent_service_health_without_probe():
    view = from_snapshot(_Snapshot(), development=None)
    page = render(view, "responsive")
    assert "UNVERIFIED" in page
    assert "\u672a\u78ba\u8a8d" in page



def test_recovery_panel_uses_only_existing_guard_work_and_review_boundaries():
    app = object.__new__(OperatorApplication)
    app.humanmodel_factory_registered = False
    app.question_resolver = None
    app.host_question_resolver = None
    app.development_status = None
    snapshot = _Snapshot()
    page = render(from_snapshot(
        snapshot, development=app.development_state(snapshot)), "responsive")
    assert "GUARD / CURRENT WORK · RECOVERY" in page
    assert "WORK FAILED / 2 · UNCERTAIN / 1" in page
    assert "過去の失敗Work 2件は残っています" in page
    assert "APPROVED HUMANMODEL VIEW / UNVERIFIED" in page
    assert "HUMANMODEL / PROVISIONAL NOTICE ANSWERS / 0" in page
    # Historical routes remain protected, but dashboard actions belong to notifications.
    for path in ("/development/review", "/klm/review", "/release"):
        assert 'href="' + path + '"' not in page
    assert "既存の本人レビュー・Guard・M1独立受入を省略しません" in page
    assert 'action="/development/review' not in page
    assert 'action="/release' not in page
    echo = render(from_snapshot(
        snapshot, development=app.development_state(snapshot)), "echo")
    for path in ("/development/review", "/klm/review", "/release"):
        assert path not in echo


def test_recovery_panel_unknown_data_never_becomes_zero_or_verified():
    from types import SimpleNamespace
    snapshot = _Snapshot()
    poisoned = {
        "work_failed": True,
        "work_uncertain": -1,
        "work_waiting_human": "0",
        "approved_humanmodel_view": "<spoofed owner view>",
        "direct_mcp_status": "DONE",
        "klm_status": "<CURRENT>",
    }
    view = from_snapshot(snapshot, development=poisoned)
    page = render(view, "responsive")
    assert "WORK FAILED / UNVERIFIED · UNCERTAIN / UNVERIFIED" in page
    assert "APPROVED HUMANMODEL VIEW / UNVERIFIED" in page
    assert "<spoofed owner view>" not in page
    assert "&lt;spoofed" not in page
    assert "失敗Workの状況は現在のGuard/Workから確認できません" in page
