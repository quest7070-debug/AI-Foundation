"""Actual saved request -> local preview -> explicit immutable owner review."""
from hashlib import sha256
import http.client
import json
from pathlib import Path
import sqlite3
import subprocess
import threading
from urllib.parse import urlencode

import pytest

from scripts import m1_development_owner_review as review
from scripts import m1_development_review_candidate as prepare
from ai_foundation.development_review_renderer import render_review
from ai_foundation.operator_server import OperatorApplication, serve


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args],
                                   text=True, stderr=subprocess.DEVNULL).strip()


def fixture(tmp_path, *, source="VALUE = 1\n"):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.check_call(["git", "init", "-q", "-b", "main", str(repo)])
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    src = repo / "src/ai_foundation/sample.py"
    src.parent.mkdir(parents=True)
    src.write_text(source)
    test = repo / "tests/test_sample.py"
    test.parent.mkdir()
    test.write_text("def test_value():\n    assert True\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "local reviewed base")
    root = tmp_path / "data"
    root.mkdir(mode=0o700)
    ident = "fresh-ui-review"
    instruction = "Modify src/ai_foundation/sample.py using tests/test_sample.py."
    prefix = "mcp-development-request:" + sha256(prepare._OWNER.encode()).hexdigest() + ":"
    with sqlite3.connect(root / "work.db") as db:
        db.execute("CREATE TABLE work_steps(job_id TEXT,position INTEGER,name TEXT,status TEXT,result TEXT)")
        db.execute("INSERT INTO work_steps VALUES(?,?,?,?,?)", (
            prefix + ident, 0, "development-request", "WAITING_HUMAN",
            json.dumps({"ticket_id": ident, "instruction": instruction})))
    (root / "work.db").chmod(0o600)
    service = review.OwnerDevelopmentReview(root, repo_factory=lambda: repo)
    return root, repo, ident, service


def confirm(service, ident, token, **changes):
    args = dict(preview_token=token, model="strata", source_reviewed=True,
                test_reviewed=True, public_nonsecret=True)
    args.update(changes)
    return service.confirm(ident, **args)


def test_actual_preview_and_explicit_review_preserve_work_and_admission_boundaries(tmp_path):
    root, repo, ident, service = fixture(tmp_path)
    work_before = (root / "work.db").read_bytes()
    preview = service.preview(ident)
    assert preview["target_text"].splitlines() == ["VALUE = 1"]
    assert not (root / "development").exists()
    with pytest.raises(PermissionError):
        confirm(service, ident, preview["preview_token"], test_reviewed=False)
    assert not (root / "development").exists()
    result = confirm(service, ident, preview["preview_token"])
    assert result == {"status": "OWNER_REVIEW_SAVED", "ticket_id": ident,
                      "execution_started": False, "model_calls": 0}
    path = root / "development/reviews" / (ident + ".json")
    saved = path.read_bytes()
    assert path.stat().st_mode & 0o077 == 0
    assert path.parent.stat().st_mode & 0o077 == 0
    record = review.admission.reviewed_contract(root, repo, ident)
    assert record["model"] == "strata" and record["source_origin"] == "owner-local-review-v1"
    confirm(service, ident, preview["preview_token"])
    assert path.read_bytes() == saved
    assert (root / "work.db").read_bytes() == work_before
    assert not (root / "development/tickets.json").exists()
    with pytest.raises(PermissionError, match="IMMUTABLE"):
        confirm(service, ident, preview["preview_token"], model="m1")
    assert path.read_bytes() == saved


def test_tampered_preview_and_changed_or_cancelled_requests_cannot_be_approved(tmp_path):
    root, repo, ident, service = fixture(tmp_path)
    preview = service.preview(ident)
    with pytest.raises(PermissionError, match="PREVIEW"):
        confirm(service, ident, "0" * 64)
    assert not (root / "development/reviews").exists()
    (repo / "src/ai_foundation/sample.py").write_text("VALUE = 2\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "new base")
    with pytest.raises(PermissionError, match="PREVIEW"):
        confirm(service, ident, preview["preview_token"])
    preview = service.preview(ident)
    with sqlite3.connect(root / "work.db") as db:
        db.execute("UPDATE work_steps SET status='CANCELLED'")
    with pytest.raises(ValueError, match="WAITING"):
        confirm(service, ident, preview["preview_token"])
    assert not (root / "development/reviews").exists()


def test_sensitive_source_never_becomes_public_review(tmp_path):
    root, repo, ident, service = fixture(
        tmp_path, source='API_KEY = "sk-proj-' + "A" * 48 + '"\n')
    preview = service.preview(ident)
    with pytest.raises(PermissionError, match="EGRESS"):
        confirm(service, ident, preview["preview_token"])
    assert not (root / "development/reviews").exists()


def test_owner_review_page_escapes_every_preview_value():
    private = '<script>alert("private")</script>'
    preview = dict.fromkeys(("ticket_id", "base_sha", "target", "test",
                              "instruction", "target_text", "test_text", "preview_token"), private)
    page = render_review('"><script>csrf</script>', preview)
    assert private not in page and '<script>' not in page
    assert '&lt;script&gt;' in page
    assert 'checked' not in page
    assert 'value="strata"' in page and 'value="auto"' in page and 'value="m1"' in page


def test_http_development_review_pages_are_frozen(tmp_path):
    root, repo, ident, service = fixture(tmp_path)
    class Config:
        data_dir = str(root)
        work_db = "work.db"
    app = OperatorApplication(Config(), object(), csrf_token="test-csrf",
                              development_review=service)
    server = serve(app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    def request(path, form=None, **headers):
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port)
        body = None if form is None else urlencode(form)
        conn.request("GET" if form is None else "POST", path, body=body,
                     headers=headers)
        response = conn.getresponse()
        data = response.read().decode()
        result = response.status, data
        conn.close()
        return result
    try:
        assert request("/development/review")[0] == 503
        assert request("/development/review", Host="evil.invalid")[0] == 403
        fields = {"ticket_id": ident, "csrf": "test-csrf"}
        assert request("/development/review/preview", fields)[0] == 503
        assert request("/development/review/confirm", fields)[0] == 503
        assert not (root / "development").exists()
    finally:
        server.shutdown()
        server.server_close()
def test_late_cancellation_removes_only_new_review_and_never_modifies_work(tmp_path, monkeypatch):
    root, repo, ident, service = fixture(tmp_path)
    preview = service.preview(ident)
    actual = review.admission.reviewed_contract
    def cancelled_after_validation(*args, **kwargs):
        result = actual(*args, **kwargs)
        with sqlite3.connect(root / "work.db") as db:
            db.execute("UPDATE work_steps SET status='CANCELLED'")
        return result
    monkeypatch.setattr(review.admission, "reviewed_contract", cancelled_after_validation)
    with pytest.raises(ValueError, match="WAITING"):
        confirm(service, ident, preview["preview_token"])
    assert not (root / "development/reviews" / (ident + ".json")).exists()
    with sqlite3.connect(root / "work.db") as db:
        assert db.execute("SELECT status FROM work_steps").fetchone()[0] == "CANCELLED"


def test_storage_pressure_refuses_review_write(tmp_path):
    root, repo, ident, service = fixture(tmp_path)
    preview = service.preview(ident)
    class Denied:
        def require(self, operation):
            raise RuntimeError("STORAGE_DENIED")
    service.storage_admission = Denied()
    with pytest.raises(RuntimeError, match="STORAGE_DENIED"):
        confirm(service, ident, preview["preview_token"])
    assert not (root / "development").exists()


def test_existing_review_replay_is_readonly_under_storage_pressure(tmp_path):
    root, repo, ident, service = fixture(tmp_path)
    preview = service.preview(ident)
    confirm(service, ident, preview["preview_token"])
    path = root / "development/reviews" / (ident + ".json")
    before = path.read_bytes()
    # Removing only the inert fixture lock proves replay never recreates it.
    lock = root / "development/reviewed-strata-install.lock"
    lock.unlink()
    class Denied:
        def require(self, operation):
            raise AssertionError("READONLY_REPLAY_MUST_NOT_REQUIRE_STORAGE")
    service.storage_admission = Denied()
    assert confirm(service, ident, preview["preview_token"])["status"] == "OWNER_REVIEW_SAVED"
    assert path.read_bytes() == before and not lock.exists()


def test_owner_withdrawal_preserves_payload_review_and_never_admits_or_executes(tmp_path):
    root, repo, ident, service = fixture(tmp_path)
    preview = service.preview(ident)
    confirm(service, ident, preview["preview_token"])
    saved_review = root / "development/reviews" / (ident + ".json")
    before = saved_review.read_bytes()
    with sqlite3.connect(root / "work.db") as db:
        contract = db.execute("SELECT result FROM work_steps").fetchone()[0]
    assert service.cancel(ident, preview_token=preview["preview_token"],
                          withdrawal_confirmed=True) == {
        "status": "REQUEST_WITHDRAWN", "ticket_id": ident, "state": "CANCELLED",
        "execution_started": False, "model_calls": 0}
    with sqlite3.connect(root / "work.db") as db:
        assert db.execute("SELECT status,result FROM work_steps").fetchone() == ("CANCELLED", contract)
    assert saved_review.read_bytes() == before
    assert not (root / "development/tickets.json").exists()
    with pytest.raises(ValueError, match="WAITING"):
        service.cancel(ident, preview_token=preview["preview_token"], withdrawal_confirmed=True)
    with pytest.raises(ValueError, match="WAITING"):
        confirm(service, ident, preview["preview_token"])


def test_withdrawal_requires_explicit_current_preview_and_refuses_admitted_ticket(tmp_path):
    root, repo, ident, service = fixture(tmp_path)
    preview = service.preview(ident)
    for args in (
        dict(preview_token=preview["preview_token"]),
        dict(preview_token="0" * 64, withdrawal_confirmed=True),
    ):
        with pytest.raises(PermissionError):
            service.cancel(ident, **args)
    assert not (root / "development").exists()
    confirm(service, ident, preview["preview_token"])
    record = review.admission.reviewed_contract(root, repo, ident)
    manifest = root / "development/tickets.json"
    manifest.write_text(json.dumps({"version": 1, "tickets": [record]}))
    manifest.chmod(0o600)
    with pytest.raises(PermissionError, match="ADMITTED"):
        service.cancel(ident, preview_token=preview["preview_token"], withdrawal_confirmed=True)
    with sqlite3.connect(root / "work.db") as db:
        assert db.execute("SELECT status FROM work_steps").fetchone()[0] == "WAITING_HUMAN"


@pytest.mark.parametrize("race", ["admitted", "changed-contract"])
def test_withdrawal_cas_cannot_overwrite_resumed_or_changed_request(tmp_path, monkeypatch, race):
    root, repo, ident, service = fixture(tmp_path)
    preview = service.preview(ident)
    actual = review.SQLiteWorkStore.cancel_development_review
    latest = {}
    def resumed(work, job_id, expected_contract):
        with work._db() as db:
            if race == "admitted":
                db.execute("UPDATE work_steps SET status='VERIFIED' WHERE job_id=?", (job_id,))
            else:
                changed = json.loads(expected_contract)
                changed["instruction"] += " New owner scope."
                db.execute("UPDATE work_steps SET result=? WHERE job_id=?", (json.dumps(changed), job_id))
            latest["row"] = db.execute("SELECT status,result FROM work_steps WHERE job_id=?", (job_id,)).fetchone()
        return actual(work, job_id, expected_contract)
    monkeypatch.setattr(review.SQLiteWorkStore, "cancel_development_review", resumed)
    with pytest.raises(PermissionError, match="CHANGED_OR_ADMITTED"):
        service.cancel(ident, preview_token=preview["preview_token"], withdrawal_confirmed=True)
    with sqlite3.connect(root / "work.db") as db:
        assert db.execute("SELECT status,result FROM work_steps").fetchone() == latest["row"]


def test_withdrawal_form_is_separate_from_execution_and_approval_confirmation():
    preview = dict.fromkeys(("ticket_id", "base_sha", "target", "test",
                              "instruction", "target_text", "test_text", "preview_token"), "fixture")
    page = render_review("csrf", preview)
    withdrawal = page[page.index('<form method="post" action="/development/review/cancel">'):]
    assert 'name="preview_token"' in withdrawal and 'name="withdrawal_confirmed"' in withdrawal
    assert 'name="model"' not in withdrawal and 'name="public_nonsecret"' not in withdrawal
    assert 'checked' not in withdrawal


def test_owner_pending_request_listing_requires_no_id_input_or_work_mutation(tmp_path):
    root, repo, ident, service = fixture(tmp_path)
    prefix = "mcp-development-request:" + sha256(prepare._OWNER.encode()).hexdigest() + ":"
    with sqlite3.connect(root / "work.db") as db:
        db.execute("INSERT INTO work_steps VALUES(?,?,?,?,?)", (
            prefix + "another-owner-task", 0, "development-request", "CANCELLED",
            '{"ticket_id":"another-owner-task","instruction":"old"}'))
        db.execute("INSERT INTO work_steps VALUES(?,?,?,?,?)", (
            prefix + "another-pending-task", 0, "development-request", "WAITING_HUMAN",
            '{"ticket_id":"another-pending-task","instruction":"new"}'))
    original = (root / "work.db").read_bytes()
    assert service.pending_request_ids() == ("another-pending-task", ident)
    assert (root / "work.db").read_bytes() == original
    assert not (root / "development").exists()
    rendered = render_review("csrf",pending_ids=service.pending_request_ids())
    assert 'name="ticket_id" value="fresh-ui-review"' in rendered
    assert 'name="ticket_id" value="another-pending-task"' in rendered
    assert 'another-owner-task' not in rendered
    assert 'name="source_reviewed"' not in rendered
    assert 'name="test_reviewed"' not in rendered
    assert not (root / "development").exists()


def test_pending_list_does_not_render_untrusted_html_or_refuse_off_owner_db(tmp_path):
    root, repo, ident, service = fixture(tmp_path)
    injected = '"><script>evil</script>'
    page = render_review("csrf",pending_ids=(ident,injected))
    assert injected not in page
    assert '<script>' not in page
    assert page.count('name="ticket_id" value="fresh-ui-review"') == 1
    work = root / "work.db"
    work.chmod(0o666)
    with pytest.raises(PermissionError,match="OWNER_WORK_DATABASE_UNVERIFIED"):
        service.pending_request_ids()


def test_owner_http_lists_pending_ids_with_no_private_payload_and_no_effect(tmp_path):
    root, repo, ident, service = fixture(tmp_path)
    class Config:
        data_dir = str(root)
        work_db = "work.db"
    app = OperatorApplication(Config(), object(), csrf_token="test-csrf",
                              development_review=service)
    server = serve(app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    before = (root / "work.db").read_bytes()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port)
        conn.request("GET", "/development/review")
        res = conn.getresponse()
        page = res.read().decode()
        conn.close()
        # Review pages are frozen: nothing is listed or disclosed.
        assert res.status == 503
        assert "fresh-ui-review" not in page
        assert "Modify src/ai_foundation/sample.py" not in page
        assert (root / "work.db").read_bytes() == before
        assert not (root / "development").exists()
    finally:
        server.shutdown()
        server.server_close()
def test_readonly_pending_readiness_distinguishes_exact_source_and_test_failures(tmp_path):
    root, repo, ident, service = fixture(tmp_path)
    assert service.pending_review_statuses() == (
        {"ticket_id": ident, "state": "PREVIEW_READY"},)
    test = repo / "tests/test_sample.py"
    test.unlink()
    git(repo, "add", "-u")
    git(repo, "commit", "-qm", "remove unavailable fixed test")
    assert service.pending_review_statuses() == (
        {"ticket_id": ident, "state": "LIVE_OPERATOR_SOURCE_UNVERIFIED"},)
    test.parent.mkdir(parents=True,exist_ok=True)
    test.write_text("def test_sample():\n    assert True\n")
    source = repo / "src/ai_foundation/sample.py"
    source.unlink()
    git(repo, "add", "-u")
    git(repo, "commit", "-qm", "remove unavailable source")
    assert service.pending_review_statuses() == (
        {"ticket_id": ident, "state": "LIVE_OPERATOR_SOURCE_UNVERIFIED"},)


def test_readonly_pending_review_scope_and_dirty_worktree_are_safe(tmp_path):
    root, repo, ident, service = fixture(tmp_path)
    with sqlite3.connect(root / "work.db") as db:
        db.execute("UPDATE work_steps SET result=?", (
            json.dumps({"ticket_id": ident, "instruction": "Please improve this feature."}),))
    state = service.pending_review_statuses()
    assert state == ({"ticket_id": ident, "state": "REVIEW_SCOPE_SELECTION_REQUIRED"},)
    repo_file = repo / "src/ai_foundation/sample.py"
    repo_file.write_text("VALUE = 200\n")
    state = service.pending_review_statuses()
    assert state == ({"ticket_id": ident, "state": "REVIEW_SCOPE_SELECTION_REQUIRED"},)
    page = render_review("csrf",pending_ids=(ident,),
        pending_states={ident:"REVIEW_SCOPE_SELECTION_REQUIRED"})
    assert "変更対象のファイル指定が不足" in page
    assert "fresh-ui-review の内容を確認" not in page
    assert "<script>" not in page
    assert not (root / "development").exists()


def test_owner_http_pending_reviews_do_not_disclose_private_error_or_source(tmp_path):
    root, repo, ident, service = fixture(tmp_path)
    with sqlite3.connect(root / "work.db") as db:
        db.execute("UPDATE work_steps SET result=?", (
            json.dumps({"ticket_id": ident, "instruction":
                        "Please inspect TOKEN=PLACEHOLDER"}),))
    class Config:
        data_dir = str(root)
        work_db = "work.db"
    app = OperatorApplication(Config(), object(), csrf_token="test-csrf",
                              development_review=service)
    server = serve(app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port)
        conn.request("GET", "/development/review")
        response = conn.getresponse()
        page = response.read().decode()
        conn.close()
        # Frozen page discloses neither the reason nor any source text.
        assert response.status == 503
        assert "TOKEN=PLACEHOLDER" not in page
        assert "<script>" not in page
        assert "fresh-ui-review" not in page
    finally:
        server.shutdown()
        server.server_close()
def test_source_review_falls_back_only_to_live_installed_immutable_worktree(
        tmp_path, monkeypatch):
    root, repo, ident, service = fixture(tmp_path)
    before = git(repo, "rev-parse", "HEAD")
    # Locally committed files exist in the installed release but not at the
    # owner's old working branch. Never change the owner's HEAD to repair it.
    (repo / "src/ai_foundation/sample.py").unlink()
    git(repo, "add", "-u")
    git(repo, "commit", "-qm", "old local checkout lacks source")
    owner_head = git(repo, "rev-parse", "HEAD")
    stage = tmp_path / "stage"
    git(repo, "worktree", "add", "--detach", str(stage), before)
    monkeypatch.setattr(prepare, "_installed_live_source_repo",
                        lambda base: stage if base == repo else None)
    preview = service.preview(ident)
    assert preview["target_text"] == "VALUE = 1\\n".replace("\\n","\n")
    assert preview["base_sha"] == before
    assert service.pending_review_statuses() == (
        {"ticket_id":ident, "state":"PREVIEW_READY"},)
    result = confirm(service, ident, preview["preview_token"], model="m1")
    assert result["status"] == "OWNER_REVIEW_SAVED"
    record = review.admission.reviewed_contract(root, stage, ident)
    assert record["base_sha"] == before
    assert git(repo, "rev-parse", "HEAD") == owner_head
    assert git(stage, "rev-parse", "HEAD") == before


def test_review_source_selection_fails_closed_without_verified_live_operator(
        tmp_path,monkeypatch):
    root, repo, ident, service = fixture(tmp_path)
    (repo / "src/ai_foundation/sample.py").unlink()
    git(repo, "add", "-u")
    git(repo, "commit", "-qm", "old local source missing")
    monkeypatch.setattr(prepare, "_installed_live_source_repo",
                        lambda _repo: (_ for _ in ()).throw(
                            ValueError("OWNER_INSTALLED_REVIEW_SOURCE_UNVERIFIED")))
    with pytest.raises(ValueError,match="OWNER_INSTALLED_REVIEW_SOURCE_UNVERIFIED"):
        service.preview(ident)
    assert service.pending_review_statuses() == (
        {"ticket_id":ident, "state":"LIVE_OPERATOR_SOURCE_UNVERIFIED"},)
    assert not (root / "development").exists()


def test_valid_owner_source_never_probes_an_installed_operator_or_changes_head(
        tmp_path, monkeypatch):
    root, repo, ident, service = fixture(tmp_path)
    monkeypatch.setattr(prepare, "_installed_live_source_repo", lambda *_:
                        pytest.fail("owner HEAD already has the exact source/test"))
    before = git(repo,"rev-parse","HEAD")
    assert service.preview(ident)["base_sha"] == before
    assert service.pending_review_statuses()[0]["state"] == "PREVIEW_READY"
    assert git(repo,"rev-parse","HEAD") == before


def test_installed_review_source_requires_exact_loaded_verified_owner_worktree(
        tmp_path, monkeypatch):
    from types import SimpleNamespace
    from scripts import m1_operator_release_cli as cli
    root, repo, ident, service = fixture(tmp_path)
    sha = git(repo, "rev-parse", "HEAD")
    stage = (tmp_path / ".ai-foundation-tunnel-sources" / sha)
    stage.parent.mkdir()
    git(repo, "worktree", "add", "--detach", str(stage), sha)
    receipt = SimpleNamespace(status="VERIFIED",
                              candidate_authority="github-commit:" + sha)
    monkeypatch.setattr(cli, "_guard_gate", lambda home, readonly=False, source_root=None:
                        SimpleNamespace(registry=SimpleNamespace(
                            get=lambda key: receipt if key == "m1-operator" else None)))
    monkeypatch.setattr(cli, "_owner_staged_source", lambda head, home, path:
                        path if head == sha and path == stage else
                        pytest.fail("unexpected source authority"))
    loaded = [True]
    class Host:
        def __init__(self, *_args, **_kwargs): pass
        def verified_current_release(self, record):
            assert record is receipt
            return loaded[0]
    monkeypatch.setattr(cli, "FixedOperatorHost", Host)
    assert prepare._installed_live_source_repo(repo, home=tmp_path) == stage
    loaded[0] = False
    with pytest.raises(ValueError, match="OWNER_INSTALLED_REVIEW_SOURCE_UNVERIFIED"):
        prepare._installed_live_source_repo(repo, home=tmp_path)
    receipt.status = "PREPARED"
    loaded[0] = True
    with pytest.raises(ValueError, match="OWNER_INSTALLED_REVIEW_SOURCE_UNVERIFIED"):
        prepare._installed_live_source_repo(repo, home=tmp_path)



def test_live_review_html_and_preview_share_one_exact_installed_source(
        tmp_path, monkeypatch):
    """The frozen page never contradicts the preview gate it no longer shows."""
    root, repo, ident, service = fixture(tmp_path)
    original = git(repo, "rev-parse", "HEAD")
    (repo / "src/ai_foundation/sample.py").unlink()
    git(repo, "add", "-u")
    git(repo, "commit", "-qm", "old owner checkout missing released source")
    stage = tmp_path / "stage"
    git(repo, "worktree", "add", "--detach", str(stage), original)
    live_verified = [True]
    calls = []
    def currently_loaded(base):
        calls.append(base)
        if not live_verified[0]:
            raise ValueError("OWNER_INSTALLED_REVIEW_SOURCE_UNVERIFIED")
        assert base == repo.resolve()
        return stage
    monkeypatch.setattr(prepare, "_installed_live_source_repo",
                        currently_loaded)
    class Config:
        data_dir = str(root)
        work_db = "work.db"
    app = OperatorApplication(Config(), object(), csrf_token="test-csrf",
                              development_review=service)
    server = serve(app)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    def page():
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=4)
        try:
            conn.request("GET", "/development/review")
            response = conn.getresponse()
            return response.status, response.read().decode("utf-8")
        finally:
            conn.close()
    try:
        status, html = page()
        assert status == 503
        assert service.preview(ident)["base_sha"] == original
        live_verified[0] = False
        status, html = page()
        assert status == 503
        with pytest.raises(ValueError, match="OWNER_INSTALLED_REVIEW_SOURCE_UNVERIFIED"):
            service.preview(ident)
        assert len(calls) >= 2
        assert not (root / "development").exists()
    finally:
        server.shutdown()
        server.server_close()
def test_readonly_review_guard_is_bound_to_verified_owner_repo_not_cli_copy(
        tmp_path, monkeypatch):
    """Exact Guard registry source is independent of installed module __file__."""
    from types import SimpleNamespace
    from scripts import m1_operator_release_cli as cli
    from scripts import m1_development_ticket_factory as factory
    trusted = tmp_path / "owner-repo"
    trusted.mkdir()
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    main = tmp_path / "main.json"
    main.write_text("{}")
    # The selected registry must remain original even after root selection.
    ledgers = []
    class Host:
        def __init__(self, source_root, *, home=None):
            assert source_root == trusted.resolve()
        def select_release_registry(self, path, *, scope=None):
            ledgers.append((path, scope))
            return main
    monkeypatch.setattr(factory, "_owner_local_repo", lambda: trusted)
    monkeypatch.setattr(cli, "_guard_path", lambda home:
                        (tmp_path / "guard.db", main))
    monkeypatch.setattr(cli, "FixedOperatorHost", Host)
    monkeypatch.setattr(cli, "_owner_file", lambda *a, **kw:b"{}")
    monkeypatch.setattr(cli, "ReadOnlyGuardStore", lambda _: object())
    monkeypatch.setattr(cli, "SQLiteGuardStore", lambda _:
                        pytest.fail("writable Guard not permitted"))
    monkeypatch.setattr(cli, "GuardReleaseGate",
                        lambda store,path: SimpleNamespace(registry_path=path))
    # An existing historical ledger triggers the exact original selector.
    (tmp_path / ("operator-owner-main-release-" + "a"*20 + ".json")).write_text("{}")
    receipt = cli._guard_gate(tmp_path,readonly=True,source_root=trusted)
    assert receipt.registry_path == main and len(ledgers)==1
    with pytest.raises(cli.OwnerReleaseDenied,match="REVIEW_GUARD_SOURCE_UNVERIFIED"):
        cli._guard_gate(tmp_path,readonly=True,source_root=foreign)
    with pytest.raises(cli.OwnerReleaseDenied,match="REVIEW_GUARD_SOURCE_UNVERIFIED"):
        cli._guard_gate(tmp_path,readonly=False,source_root=trusted)
