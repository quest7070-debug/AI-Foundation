from types import SimpleNamespace

from ai_foundation.human_renderer import _overview


def _view(providers=()):
    return SimpleNamespace(
        development={},
        telemetry=SimpleNamespace(ready=False, services=()),
        activity=(),
        providers=providers,
        runtime_health="UNVERIFIED",
    )


def test_overview_empty_provider_feed_is_unverified_not_online():
    page = _overview(_view())
    assert "0 / 0 ONLINE" not in page
    assert "UNVERIFIED" in page
    assert "\u5916\u90e8AI" in page


def test_overview_observed_provider_rows_keep_real_online_fraction():
    providers = (
        SimpleNamespace(health="ONLINE"),
        SimpleNamespace(health="DOWN"),
    )
    page = _overview(_view(providers))
    assert "1 / 2 ONLINE" in page


def _system_view(ready, checks, services):
    view = _view()
    view.telemetry = SimpleNamespace(
        ready=ready, checks=checks, services=services, backup=None, update=None,
    )
    view.notices = view.tasks = view.credentials = view.local_compute = view.routes = ()
    view.state = "READY"
    view.severity_counts = (0, 0, 0, 0, 0)
    return view


def test_system_details_preserve_unknown_checks_and_services_on_both_surfaces():
    from ai_foundation.human_renderer import render
    rows = (
        {"name": "good", "ok": True},
        {"name": "broken", "ok": False},
        {"name": "missing", "ok": None},
        {"name": "untyped", "ok": "false"},
    )
    for surface in ("responsive", "echo"):
        page = render(_system_view(False, rows, rows), surface)
        assert "CHECKS FAILED / 1" in page
        assert "SERVICES DOWN / 1" in page
        assert "CHECKS UNVERIFIED / 2" in page
        assert "SERVICES UNVERIFIED / 2" in page
        assert "good OK" in page and "broken DOWN" in page
        assert "missing UNVERIFIED" in page and "untyped UNVERIFIED" in page
        assert "missing DOWN" not in page and "untyped OK" not in page


def test_system_ready_requires_actual_boolean_true_on_both_surfaces():
    from ai_foundation.human_renderer import render
    rows = ({"name": "probe", "ok": True},)
    for surface in ("responsive", "echo"):
        for ready in ("false", 1, [True], None, False):
            page = render(_system_view(ready, rows, rows), surface)
            assert "SYSTEM READY" not in page
        assert "SYSTEM READY" in render(_system_view(True, rows, rows), surface)

