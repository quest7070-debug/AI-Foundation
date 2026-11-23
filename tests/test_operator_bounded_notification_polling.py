"""Large synthetic Operator notices do not inflate polling or fake history coverage.

All data is fixture-only; no HumanModel source, owner approval, model or effects.
"""
import json
from http.client import HTTPConnection
from http.server import HTTPServer
from threading import Thread

import pytest

from ai_foundation.core import GuardState
from ai_foundation.guard import GuardCore
from ai_foundation.human_operations import HumanNotice
from ai_foundation.operator_actions import OperatorActions
from ai_foundation.operator_server import OperatorApplication, make_handler
from ai_foundation.productization import FoundationConfig


def application(tmp_path, current):
    root = tmp_path / "operator"
    root.mkdir()
    return OperatorApplication(
        FoundationConfig(str(root.resolve())),
        OperatorActions(GuardCore(GuardState())),
        operational_notices=lambda: tuple(current),
    )


def notice(i, text):
    return HumanNotice(
        2, "primary_review", f"synthetic-{i:04d}", "PRIMARY_REVIEW_RESOLVED",
        "synthetic local notification", "synthetic local result", False, False,
        float(i), automatic_answer=text,
        answer_reference={"task_id": f"synthetic-{i}", "current_generation": True},
    )


def test_compact_poll_and_explicit_page_stay_bounded_with_many_long_answers(tmp_path):
    private = "SECRET_PRIVATE_ANSWER_" + "あ" * 15900
    items = [notice(i, private) for i in range(48)]
    app = application(tmp_path, items)

    status = app.compact_human_status()
    raw_status = json.dumps(status, ensure_ascii=False).encode("utf-8")
    assert len(raw_status) < 8192
    assert private not in raw_status.decode()
    assert status["source_window_bounded"] is True
    assert status["notices_in_window"] == 48

    cursor = 0
    revision = None
    collected = []
    for _ in range(48):
        page = app.human_notice_page(after=cursor, revision=revision)
        raw_page = json.dumps(page, ensure_ascii=False).encode("utf-8")
        assert len(raw_page) <= 192 * 1024
        assert page["source_window_bounded"] is True
        assert len(page["notices"]) >= 1
        collected.extend(row["subject"] for row in page["notices"])
        revision = page["revision"]
        cursor = page["next_after"]
        if cursor is None:
            break
    else:
        pytest.fail("bounded page cursor did not terminate")
    assert collected == [n["subject"] for n in app.human_payload()["notices"]]
    assert len(set(collected)) == 48


def test_stale_page_rejects_reordered_or_changed_answer_without_replay(tmp_path):
    items = [notice(i, "TEST_ANSWER" + str(i)) for i in range(16)]
    app = application(tmp_path, items)
    first = app.human_notice_page()
    assert first["next_after"] is not None
    prior_revision = first["revision"]
    prior_status = app.compact_human_status()["revision"]
    items[0] = notice(0, "TEST_CHANGED_ANSWER")
    assert app.compact_human_status()["revision"] != prior_status
    with pytest.raises(ValueError, match="stale"):
        app.human_notice_page(after=first["next_after"], revision=prior_revision)
    with pytest.raises(ValueError, match="requires exact revision"):
        app.human_notice_page(after=first["next_after"])
    # A source misconfiguration must fail rather than silently drop one notice.
    items[:] = [notice(1, "🧪" * 50000)]
    with pytest.raises(ValueError, match="fixed page budget"):
        app.human_notice_page()


def test_compact_http_status_and_legacy_echo_privacy(tmp_path):
    private = "NEVER_ECHO_PRIVATE_ANSWER_" + "愛" * 15000
    app = application(tmp_path, [notice(1, private), notice(2, private)])
    html = app.page()
    assert "fetch('/api/human/status'" not in html
    echo_html = app.page("echo")
    assert "fetch('/api/human/echo'" not in echo_html

    with HTTPServer(("127.0.0.1", 0), make_handler(app)) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            conn = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            for path in ("/api/human/status", "/api/human/echo/status"):
                conn.request("GET", path, headers={"Host": "127.0.0.1"})
                response = conn.getresponse()
                raw = response.read()
                assert response.status == 200
                assert len(raw) < 8192
                assert b"NEVER_ECHO_PRIVATE" not in raw
                assert "notices" not in json.loads(raw)

            conn.request("GET", "/api/human/notices", headers={"Host": "127.0.0.1"})
            response = conn.getresponse()
            raw = response.read()
            assert response.status == 200
            assert len(raw) <= 192 * 1024
            row = json.loads(raw)
            assert row["notices"][0]["automatic_answer"] == private

            conn.request("GET", "/api/human/notices?after=1",
                         headers={"Host": "127.0.0.1"})
            response = conn.getresponse()
            assert response.status == 409
            assert b"NEVER_ECHO_PRIVATE" not in response.read()

            conn.request("GET", "/api/human/echo",
                         headers={"Host": "127.0.0.1"})
            response = conn.getresponse()
            raw = response.read()
            assert response.status == 200
            assert b"NEVER_ECHO_PRIVATE" not in raw
            conn.close()
        finally:
            server.shutdown()
            thread.join(timeout=3)
