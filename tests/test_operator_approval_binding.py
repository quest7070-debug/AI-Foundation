"""Existing Guard is the only source of UI authorization, with exact pending identity."""
import sqlite3
import threading
import urllib.error
import urllib.parse
import urllib.request

from ai_foundation.core import GuardState
from ai_foundation.guard import GuardCore
from ai_foundation.operator_actions import OperatorActions
from ai_foundation.operator_server import OperatorApplication, serve
from ai_foundation.productization import FoundationConfig
from ai_foundation.store import SQLiteGuardStore


def state(tmp_path):
    root = tmp_path / 'operator'
    root.mkdir()
    cfg = FoundationConfig(str(root))
    store = SQLiteGuardStore(root / cfg.guard_db)
    guard = GuardCore(store.load(), store=store)
    return cfg,store,guard


def test_identical_preflight_keeps_reference_but_changed_target_invalidates(tmp_path):
    cfg,store,guard = state(tmp_path)
    store.request_approval('run-101', 'production_deploy', 'development-instance-a', 'canon-test', 'effect-101')
    app = OperatorApplication(cfg,OperatorActions(guard))
    original = next(x for x in app.human_payload()['notices'] if x['subject'] == 'run-101')
    assert original['level'] == 4
    assert original['approval_ref'] and len(original['approval_ref']) == 64
    assert 'development-instance-a' not in str(app.human_payload())
    assert 'approval_ref' in app.page()

    store.request_approval('run-101','production_deploy','development-instance-a','canon-test','effect-101')
    identical = next(x for x in app.human_payload()['notices'] if x['subject'] == 'run-101')
    assert identical['approval_ref'] == original['approval_ref']

    store.request_approval('run-101','production_deploy','development-instance-b','canon-test','effect-101')
    changed = next(x for x in app.human_payload()['notices'] if x['subject'] == 'run-101')
    assert changed['approval_ref'] != original['approval_ref']
    assert not guard.approve_pending('run-101',original['approval_ref'])
    assert not store.is_approved('run-101')
    assert guard.approve_pending('run-101',changed['approval_ref'])
    assert store.is_approved('run-101')
    assert not guard.approve_pending('run-101',changed['approval_ref'])
    assert not any(x['subject'] == 'run-101' for x in app.human_payload()['notices'])


def test_http_approves_only_exact_pending_request_and_refuses_replay(tmp_path):
    cfg,store,guard=state(tmp_path)
    store.request_approval('run-202','production_deploy','approved-scope','canon-test','effect-202')
    app=OperatorApplication(cfg,OperatorActions(guard))
    srv=serve(app)
    t=threading.Thread(target=srv.serve_forever,daemon=True)
    t.start()
    try:
        base=f'http://127.0.0.1:{srv.server_port}'
        first=next(x for x in app.human_payload()['notices'] if x['subject']=='run-202')['approval_ref']
        store.request_approval('run-202','production_deploy','changed-scope','canon-test','effect-202')
        second=next(x for x in app.human_payload()['notices'] if x['subject']=='run-202')['approval_ref']
        def submit(ref):
            data=urllib.parse.urlencode({'csrf':app.csrf_token,'approval_ref':ref}).encode()
            req=urllib.request.Request(base+'/action/approve/run-202',method='POST',data=data)
            try:
                with urllib.request.urlopen(req,timeout=2) as response:
                    return response.status,response.read().decode()
            except urllib.error.HTTPError as exc:
                return exc.code,exc.read().decode()
        assert submit(first)[0] == 409
        assert submit('')[0] == 409
        assert not store.is_approved('run-202')
        assert submit(second)[0] == 200
        assert store.is_approved('run-202')
        assert submit(second)[0] == 409
    finally:
        srv.shutdown();srv.server_close();t.join(timeout=2)


def test_cancellation_fails_closed_and_existing_requests_migrate(tmp_path):
    cfg,store,guard=state(tmp_path)
    store.request_approval('run-303','delete','test-only','canon-test','effect-303')
    reference=next(x for x in OperatorApplication(cfg,OperatorActions(guard)).human_payload()['notices']
                   if x['subject']=='run-303')['approval_ref']
    guard.cancel('run-303')
    assert not guard.approve_pending('run-303',reference)
    assert not store.is_approved('run-303')
    # A pre-nonce Guard database is adopted by the existing store migration.
    old=tmp_path/'old.db'
    with sqlite3.connect(old) as db:
        db.execute("CREATE TABLE approval_requests(run_id TEXT PRIMARY KEY, action TEXT NOT NULL, target TEXT NOT NULL, updated_at REAL NOT NULL)")
        db.execute("INSERT INTO approval_requests VALUES('legacy','delete','test',123)")
    migrated=SQLiteGuardStore(old)
    with migrated._connect() as db:
        row=db.execute("SELECT request_nonce FROM approval_requests WHERE run_id='legacy'").fetchone()
    assert row and len(row[0]) == 32


def test_deny_requires_exact_pending_revision_and_cannot_cancel_replaced_request(tmp_path):
    cfg,store,guard=state(tmp_path)
    store.request_approval('run-404','send_email','original-target','canon-test','effect-404')
    app=OperatorApplication(cfg,OperatorActions(guard))
    first=next(x for x in app.human_payload()['notices'] if x['subject']=='run-404')['approval_ref']
    assert not app.act('cancel','run-404').ok
    assert not store.is_cancelled('run-404')
    store.request_approval('run-404','send_email','replacement-target','canon-test','effect-404')
    second=next(x for x in app.human_payload()['notices'] if x['subject']=='run-404')['approval_ref']
    assert first!=second
    assert not app.act('cancel','run-404',first).ok
    assert app.act('cancel','run-404',second).ok
    assert store.is_cancelled('run-404')
    assert not app.act('cancel','run-404',second).ok
    assert not guard.approve_pending('run-404',second)


def test_http_deny_stale_ref_returns_conflict(tmp_path):
    cfg,store,guard=state(tmp_path)
    store.request_approval('run-505','production_deploy','original','canon-test','effect-505')
    app=OperatorApplication(cfg,OperatorActions(guard))
    srv=serve(app)
    t=threading.Thread(target=srv.serve_forever,daemon=True)
    t.start()
    try:
        first=next(x for x in app.human_payload()['notices'] if x['subject']=='run-505')['approval_ref']
        store.request_approval('run-505','production_deploy','new','canon-test','effect-505')
        second=next(x for x in app.human_payload()['notices'] if x['subject']=='run-505')['approval_ref']
        base=f'http://127.0.0.1:{srv.server_port}'
        def deny(ref):
            raw=urllib.parse.urlencode({'csrf':app.csrf_token,'approval_ref':ref}).encode()
            req=urllib.request.Request(base+'/action/cancel/run-505',data=raw,method='POST')
            try:
                with urllib.request.urlopen(req,timeout=2) as res:return res.status
            except urllib.error.HTTPError as exc:return exc.code
        assert deny(first)==409
        assert deny('')==409
        assert not store.is_cancelled('run-505')
        assert deny(second)==200
        assert store.is_cancelled('run-505')
        assert deny(second)==409
    finally:
        srv.shutdown();srv.server_close();t.join(timeout=2)


def test_after_approval_changed_target_canon_or_effect_cannot_reuse_run(tmp_path):
    from ai_foundation.core import TaskPlan, CanonContract, Decision
    cfg,store,guard=state(tmp_path)
    original=TaskPlan('reuse-1','send_email','recipient-a',
                      canon_revision='canon-v1',effect_id='effect-1')
    canon=CanonContract('source','canon-v1')
    assert guard.preflight(original,canon) is Decision.WAITING_HUMAN
    app=OperatorApplication(cfg,OperatorActions(guard))
    reference=next(x for x in app.human_payload()['notices']
                   if x['subject']=='reuse-1')['approval_ref']
    assert app.act('approve','reuse-1',reference).ok
    assert guard.preflight(original,canon) is Decision.ALLOW
    restarted=GuardCore(store.load(),store=store)
    assert restarted.preflight(original,canon) is Decision.ALLOW
    for changes,new_canon in [
        ({'target':'recipient-b'},canon),
        ({'action':'delete'},canon),
        ({'effect_id':'effect-2'},canon),
        ({'canon_revision':'canon-v2'},CanonContract('source','canon-v2')),
    ]:
        from dataclasses import replace
        changed=replace(original,**changes)
        assert guard.preflight(changed,new_canon) is Decision.DENY
        assert restarted.preflight(changed,new_canon) is Decision.DENY
    assert not store.has_pending('reuse-1')
    # The consumed run cannot even create another pending request.
    assert not store.request_approval('reuse-1','delete','recipient-b','canon-v2','effect-2')
    assert not store.has_pending('reuse-1')
    assert not any(x['subject']=='reuse-1' for x in app.human_payload()['notices'])


def test_legacy_unscoped_guard_grants_do_not_authorize_critical_effect(tmp_path):
    from ai_foundation.core import TaskPlan, CanonContract, Decision
    cfg,store,guard=state(tmp_path)
    guard.approve('legacy-run')
    assert store.is_approved('legacy-run')
    assert not store.is_approved_for('legacy-run','send_email','x','v1','effect-x')
    p=TaskPlan('legacy-run','send_email','x',canon_revision='v1',effect_id='effect-x')
    assert guard.preflight(p,CanonContract('source','v1')) is Decision.DENY
    assert not store.has_pending('legacy-run')


def test_migrated_unbound_request_requires_real_preflight_before_approval(tmp_path):
    from ai_foundation.core import TaskPlan, CanonContract, Decision
    from ai_foundation.store import approval_request_ref
    cfg,store,guard=state(tmp_path)
    # Simulate an upgraded pending row with nonce but no Canon/effect binding.
    store.request_approval('legacy-pending','send_email','test-recipient')
    with store._connect() as db:
        row=db.execute(
            "SELECT action,target,request_nonce,canon_revision,effect_id "
            "FROM approval_requests WHERE run_id='legacy-pending'"
        ).fetchone()
    assert row[3:] == ('','')
    forged=approval_request_ref('legacy-pending',*row)
    assert not guard.approve_pending('legacy-pending',forged)
    app=OperatorApplication(cfg,OperatorActions(guard))
    old_notice=next(n for n in app.human_payload()['notices'] if n['subject']=='legacy-pending')
    assert not old_notice['approval_ref']
    assert not app.act('approve','legacy-pending',forged).ok

    plan=TaskPlan('legacy-pending','send_email','test-recipient',
                  canon_revision='rev-real',effect_id='effect-real')
    assert guard.preflight(plan,CanonContract('repo','rev-real')) is Decision.WAITING_HUMAN
    refreshed=next(n for n in app.human_payload()['notices'] if n['subject']=='legacy-pending')
    assert refreshed['approval_ref'] and refreshed['approval_ref'] != forged
    assert app.act('approve','legacy-pending',refreshed['approval_ref']).ok
    assert guard.preflight(plan,CanonContract('repo','rev-real')) is Decision.ALLOW


def test_concurrent_preflight_cannot_reopen_consumed_approval_or_denial(tmp_path):
    from ai_foundation.core import TaskPlan, CanonContract, Decision
    cfg,store,guard=state(tmp_path)
    canon=CanonContract('repo','revision-1')
    first=TaskPlan('race-approved','send_email','target',
                   canon_revision='revision-1',effect_id='effect-approved')
    assert guard.preflight(first,canon) is Decision.WAITING_HUMAN
    app=OperatorApplication(cfg,OperatorActions(guard))
    ref=next(n for n in app.human_payload()['notices'] if n['subject']=='race-approved')['approval_ref']
    assert guard.approve_pending('race-approved',ref)
    # Represents a preflight whose first read occurred before approval.
    assert not store.request_approval('race-approved','send_email','target','revision-1','effect-approved')
    assert not store.has_pending('race-approved')
    assert guard.preflight(first,canon) is Decision.ALLOW

    second=TaskPlan('race-denied','delete','target',
                    canon_revision='revision-1',effect_id='effect-denied')
    assert guard.preflight(second,canon) is Decision.WAITING_HUMAN
    deny_ref=next(n for n in app.human_payload()['notices'] if n['subject']=='race-denied')['approval_ref']
    assert guard.cancel_pending('race-denied',deny_ref)
    assert not store.request_approval('race-denied','delete','target','revision-1','effect-denied')
    assert not store.has_pending('race-denied')
    assert guard.preflight(second,canon) is Decision.DENY
