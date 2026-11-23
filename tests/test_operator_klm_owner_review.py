"""Real HTTP owner confirmation reuses exact Guard and native source checks."""
from contextlib import contextmanager
from html import unescape
import http.client
import json
import re
import sqlite3
import threading
from urllib.parse import urlencode

import pytest
from test_m1_klm_owner_review import service, native
from test_m1_development_owner_review import fixture as code_fixture
from ai_foundation.klm_review_renderer import render_klm_review
from ai_foundation.operator_actions import OperatorActions
from ai_foundation.operator_server import OperatorApplication, serve


@contextmanager
def running(root, actions, *, klm=None, code=None):
    class Config:
        data_dir = str(root)
        work_db = "work.db"
    app = OperatorApplication(Config(), actions, csrf_token="owner-csrf",
                              development_review=code, klm_review=klm)
    server = serve(app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    def request(path, form=None, **headers):
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port)
        conn.request("GET" if form is None else "POST", path,
                     body=None if form is None else urlencode(form), headers=headers)
        response = conn.getresponse()
        result = response.status, response.read().decode()
        conn.close()
        return result
    try:
        yield request
    finally:
        server.shutdown()
        server.server_close()


def token_from(page):
    return unescape(re.search(r'name="preview_token" value="([^"]+)"', page).group(1))


def test_http_klm_review_pages_are_frozen(service):
    backend, journal, guard, atoms, values, gets, key = service
    with running(journal.path.parent, OperatorActions(guard), klm=lambda: backend) as request:
        assert request("/klm/review")[0] == 503
        assert request("/klm/review", Host="evil.invalid")[0] == 403
        fields = dict(csrf="owner-csrf", review_key=key)
        assert request("/klm/review/preview", dict(fields, csrf="wrong"))[0] == 403
        assert request("/klm/review/preview", fields)[0] == 503
        assert request("/klm/review/confirm", fields)[0] == 503
    with sqlite3.connect(journal.path) as db:
        assert db.execute("SELECT COUNT(*) FROM klm_relation_reviews WHERE status='UNRESOLVED'").fetchone()[0] == 1
    with guard.store._connect() as db:
        assert db.execute("SELECT COUNT(*) FROM approval_requests").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 0
def test_http_confirmation_is_frozen_and_records_nothing(service):
    backend, journal, guard, atoms, values, gets, key = service
    with running(journal.path.parent, OperatorActions(guard), klm=lambda: backend) as request:
        assert request("/klm/review/preview", dict(csrf="owner-csrf", review_key=key))[0] == 503
        assert request("/klm/review/confirm", dict(
            csrf="owner-csrf", review_key=key, preview_token="0" * 64,
            decision="ACCEPT", relation_kind="supports", reviewed="yes"))[0] == 503
    with sqlite3.connect(journal.path) as db:
        assert db.execute("SELECT COUNT(*) FROM klm_relation_reviews WHERE status='UNRESOLVED'").fetchone()[0] == 1
def test_renderer_escapes_sources_and_uses_existing_theme_without_checked_decision():
    raw = '<script>alert("private")</script>'
    atom = dict.fromkeys(("resource_id", "record_id", "revision", "span_text", "atom_id",
                         "source_sha256", "span_sha256", "meaning_sha256"), raw)
    preview = dict(reason=raw, scope=raw, review_key=raw, preview_token=raw, before=atom, after=atom)
    page = render_klm_review(raw, preview=preview, theme="C")
    assert raw not in page and "<script>" not in page and "&lt;script&gt;" in page
    assert "checked" not in page and 'action="/klm/review/confirm"' in page
    assert 'name="reviewed"' in page and "AI FOUNDATION" in page


def test_http_development_review_pages_are_frozen(tmp_path):
    root, repo, ident, backend = code_fixture(tmp_path)
    with running(root, object(), code=backend) as request:
        assert request("/development/review")[0] == 503
        assert request("/development/review/preview", dict(csrf="owner-csrf", ticket_id=ident))[0] == 503
        assert request("/development/review/cancel", dict(
            csrf="owner-csrf", ticket_id=ident, preview_token="0" * 64,
            withdrawal_confirmed="yes"))[0] == 503
    with sqlite3.connect(root / "work.db") as db:
        assert db.execute("SELECT status FROM work_steps").fetchone()[0] != "CANCELLED"
def test_unavailable_optional_klm_does_not_break_existing_operator(tmp_path):
    with running(tmp_path, object()) as request:
        assert request("/klm/review")[0] == 503
        assert request("/klm/review/preview", dict(csrf="owner-csrf", review_key="a" * 64))[0] == 503


def test_owner_klm_review_link_is_responsive_only(service):
    backend, journal, guard, atoms, values, gets, key = service
    from ai_foundation.productization import FoundationConfig
    config = FoundationConfig(str(journal.path.parent.resolve()))
    app = OperatorApplication(config, OperatorActions(guard),
                              csrf_token="owner-csrf", klm_review=lambda: backend,
                              development_review=object())
    # CODE and KLM use the original unified owner notification actions.
    # Historical protected endpoints are preserved but not advertised as
    # separate human approval interfaces on either presentation surface.
    desktop = app.page("responsive")
    echo = app.page("echo")
    assert 'id="development"' in desktop
    assert 'href="/klm/review"' not in desktop
    assert 'href="/development/review"' not in desktop
    assert 'href="/klm/review"' not in echo
    assert 'href="/development/review"' not in echo
    assert desktop.endswith('</body></html>')
