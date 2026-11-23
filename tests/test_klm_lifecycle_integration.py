"""Isolated lifecycle acceptance; no network, model, production data or grants."""
import hashlib
import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from ai_foundation.knowledge_lifecycle import (SourcePointer, Meaning, OwnerTarget,
    ReadonlyReceiptJournal, decompose_verified_span)
from ai_foundation.durable_work import SQLiteWorkStore
from ai_foundation.orchestration import WorkStatus
from ai_foundation.klm_projection import apply_runtime_projection, projection_run_id


def atom(record='one', *, revision='1', privacy='shareable', **meaning):
    raw = b'fixture evidence'
    source = SourcePointer('foundation_runtime', 'fixture', record, revision, 'fixture', privacy)
    m = Meaning('observation', 'assertion', 'positive', 'fixture', 'status', 'ready', **meaning)
    return decompose_verified_span(source, raw, source_sha256=hashlib.sha256(raw).hexdigest(),
                                   start=0, end=len(raw), meaning=m)


def test_incremental_candidates_replay_and_boundary(tmp_path):
    j = ReadonlyReceiptJournal(tmp_path/'work.db')
    a, b = atom(), atom('two')
    unrelated = replace(b, meaning=replace(b.meaning, subject='different'))
    # Construct a valid atom ID for unrelated meaning, not a forged dataclass ID.
    raw=b'fixture evidence'
    unrelated = decompose_verified_span(unrelated.source,raw,source_sha256=hashlib.sha256(raw).hexdigest(),
                                        start=0,end=len(raw),meaning=unrelated.meaning)
    for x in (a,b,unrelated,atom('restricted',privacy='private')): j.record_atom(x)
    assert j.reconcile_atom(b.atom_id,domain='runtime_observation')['evaluated']==2  # same record + same subject
    assert j.reconcile_atom(b.atom_id)['boundary_reviews']==1
    with sqlite3.connect(j.path) as db:
        before=db.execute('SELECT COUNT(*) FROM klm_relation_reviews').fetchone()[0]
    j.reconcile_atom(b.atom_id)
    with sqlite3.connect(j.path) as db:
        assert db.execute('SELECT COUNT(*) FROM klm_relation_reviews').fetchone()[0]==before
        assert {r[0] for r in db.execute('SELECT status FROM klm_relation_reviews')}=={'UNRESOLVED'}
    assert b'fixture evidence' not in j.path.read_bytes()


def test_qualifier_revision_and_legacy_are_not_silent(tmp_path):
    j=ReadonlyReceiptJournal(tmp_path/'work.db')
    a,b,c=atom(),atom('two',condition='only tomorrow'),atom(revision='2')
    for x in (a,b,c): j.record_atom(x)
    j.reconcile_atom(b.atom_id);j.reconcile_atom(c.atom_id)
    with sqlite3.connect(j.path) as db:
        reasons={r[0] for r in db.execute('SELECT reason FROM klm_relation_reviews')}
        assert 'CONDITION_TIME_OR_ATTRIBUTION_REVIEW' in reasons
        assert 'REVISION_OR_REINTERPRETATION_REVIEW' in reasons
        db.execute('DELETE FROM klm_atom_features WHERE atom_id=?',(a.atom_id,))
    work=SQLiteWorkStore(j.path)
    result=j.audit_due(work,now=1794000000)
    assert result['daily']['missing_features']==1
    assert j.audit_due(work,now=1794000001)['daily']=='ALREADY_VERIFIED'
    # An authenticated replay of one legacy atom rebuilds its derived index.
    assert j.record_atom(a)=='ALREADY_RECORDED'
    assert j.reconcile_atom(a.atom_id)['status']=='PROPOSED_NO_EFFECT'



def test_explicit_negation_not_masked_by_object_difference(tmp_path):
    """Review a negation even when the wording of the value also changes."""
    j = ReadonlyReceiptJournal(tmp_path / 'work.db')
    before = atom('positive-record')
    original = atom('negative-record')
    raw = b'fixture evidence'
    negative = decompose_verified_span(
        original.source, raw, source_sha256=hashlib.sha256(raw).hexdigest(),
        start=0, end=len(raw),
        meaning=replace(original.meaning, polarity='negative', object='not ready'))
    j.record_atom(before)
    j.record_atom(negative)
    assert j.reconcile_atom(negative.atom_id)['status'] == 'PROPOSED_NO_EFFECT'
    with sqlite3.connect(j.path) as db:
        reasons = {row[0] for row in db.execute(
            'SELECT reason FROM klm_relation_reviews')}
        statuses = {row[0] for row in db.execute(
            'SELECT status FROM klm_relation_reviews')}
    assert 'POTENTIAL_CONTRADICTION' in reasons
    assert statuses == {'UNRESOLVED'}


def test_existing_relation_is_flagged_after_source_revision_change(tmp_path):
    from ai_foundation.knowledge_lifecycle import RelationProposal
    journal = ReadonlyReceiptJournal(tmp_path / 'work.db')
    old = atom('canonical', revision='1')
    linked = atom('dependent')
    for item in (old, linked):
        journal.record_atom(item)
    journal.record_relation(RelationProposal('depends_on', linked.atom_id, old.atom_id))
    newer = atom('canonical', revision='2')
    journal.record_atom(newer)
    work = SQLiteWorkStore(journal.path)
    receipt = journal.audit_due(work, now=1794000000)['daily']
    assert receipt['relation_revision_review_candidates'] == 1
    assert receipt['external_writes'] == 0 and receipt['model_calls'] == 0
    assert work.load('klm-audit:daily:2026-11-06')[0].status is WorkStatus.VERIFIED
    with sqlite3.connect(journal.path) as db:
        assert db.execute('SELECT status FROM klm_relations').fetchone()[0] == 'proposed'


def test_interrupted_audit_is_preserved(tmp_path):
    j=ReadonlyReceiptJournal(tmp_path/'work.db'); work=SQLiteWorkStore(j.path)
    j.audit_due(work,now=1794000000)
    with sqlite3.connect(j.path) as db:
        db.execute("UPDATE work_steps SET status='RUNNING' WHERE job_id LIKE 'klm-audit:daily:%'")
    assert j.audit_due(work,now=1794000001)['daily']=='RECONCILE_REQUIRED'


class Port:
    writes=0
    fail_after_effect=False
    def observe(self,plan): return Path(plan.target).read_text()
    def execute(self,plan):
        self.writes+=1
        Path(plan.target).write_text(plan.text)
        if self.fail_after_effect: raise OSError('fixture disconnect')


@pytest.fixture
def projection(tmp_path):
    from ai_foundation.core import GuardState
    from ai_foundation.guard import GuardCore
    from ai_foundation.capability_request import CapabilityRequest
    p=tmp_path/'result.txt';p.write_text('before')
    target=OwnerTarget('foundation_runtime',str(tmp_path),'result.txt',
                      'sha256:'+hashlib.sha256(b'before').hexdigest(),'fixture','shareable','projection')
    request=CapabilityRequest('FILES',owner_id='fixture-owner',file_read_root=str(tmp_path),file_write_root=str(tmp_path))
    j=ReadonlyReceiptJournal(tmp_path/'work.db');w=SQLiteWorkStore(j.path)
    args=dict(atom=atom(),target=target,content='after',request=request,guard=GuardCore(GuardState()),port=Port())
    return j,w,args,p


def test_existing_guard_approval_effect_and_independent_readback(projection):
    j,w,args,p=projection
    first=apply_runtime_projection(j,w,**args)
    assert first['status']=='WAITING_HUMAN' and args['port'].writes==0
    assert w.load(first['run_id'])[0].status is WorkStatus.WAITING_HUMAN
    # Fixture host approves its exact generated plan; never a model-generated bool.
    args['guard'].approve(first['run_id'])
    assert apply_runtime_projection(j,w,**args)['status']=='VERIFIED'
    assert p.read_text()=='after' and args['port'].writes==1
    assert apply_runtime_projection(j,w,**args)['status']=='VERIFIED'
    assert args['port'].writes==1
    assert len(args['guard'].state.effects)==1


def test_ambiguous_effect_recovers_by_readback_without_duplicate_write(projection):
    j,w,args,p=projection
    run=projection_run_id(args['atom'],args['target'],args['content'],owner_id=args['request'].owner_id)
    args['guard'].approve(run);args['port'].fail_after_effect=True
    assert apply_runtime_projection(j,w,**args)['status']=='RECONCILE_REQUIRED'
    assert apply_runtime_projection(j,w,**args)['status']=='VERIFIED'
    assert args['port'].writes==1



def test_owner_cancellation_during_projection_effect_is_not_overwritten(projection):
    journal, work, args, target = projection
    run = projection_run_id(args['atom'], args['target'], args['content'],
                            owner_id=args['request'].owner_id)
    args['guard'].approve(run)
    execute = args['port'].execute

    def effect_then_owner_cancels(plan):
        execute(plan)
        assert work.transition(run, 0, WorkStatus.RUNNING,
                               WorkStatus.CANCELLED, 'OWNER_CANCELLED')

    args['port'].execute = effect_then_owner_cancels
    outcome = apply_runtime_projection(journal, work, **args)
    assert outcome['status'] == 'RECONCILE_REQUIRED'
    step = work.load(run)[0]
    assert step.status is WorkStatus.CANCELLED and step.result == 'OWNER_CANCELLED'
    assert target.read_text() == 'after'
    assert apply_runtime_projection(journal, work, **args)['status'] == 'RECONCILE_REQUIRED'
    assert args['port'].writes == 1


def test_revision_conflict_and_private_projection_fail_closed(projection):
    j,w,args,p=projection
    run=projection_run_id(args['atom'],args['target'],args['content'],owner_id=args['request'].owner_id)
    args['guard'].approve(run);p.write_text('changed by owner')
    assert apply_runtime_projection(j,w,**args)['status']=='TARGET_REVISION_CONFLICT'
    assert args['port'].writes==0
    args['atom']=atom(privacy='private')
    with pytest.raises(PermissionError): apply_runtime_projection(j,w,**args)


def test_retry_one_preserves_failure_and_rejects_changed_source(tmp_path):
    from ai_foundation.klm_drive_input import DriveState
    from ai_foundation.klm_drive_work import IntakeQueue,inbox_records
    w=SQLiteWorkStore(tmp_path/'work.db');q=IntakeQueue(DriveState(w))
    record=inbox_records([['intake_id','text'],['fixture','fixture']],owner='fixture')[0]
    q.enqueue(record);job='klm-drive:'+record['intake_id']
    w.set(job,0,WorkStatus.FAILED,'ValueError')
    raw=b'fixture';h=hashlib.sha256(raw).hexdigest()
    read=lambda _:dict(revision=record['source_revision'],sha256=h,raw=raw)
    assert q.requeue_failed(record['intake_id'],expected_revision=record['source_revision'],expected_sha256=h,read_source=read)=='REQUEUED_ONE'
    with sqlite3.connect(w.path) as db:
        assert db.execute('SELECT previous_result FROM klm_retry_history').fetchone()[0]=='ValueError'
    w.set(job,0,WorkStatus.FAILED,'ValueError')
    assert q.requeue_failed(record['intake_id'],expected_revision=record['source_revision'],expected_sha256=h,read_source=read)=='REPEATED_FAILURE_REVIEW_REQUIRED'
    with pytest.raises(ValueError):
        q.requeue_failed(record['intake_id'],expected_revision=record['source_revision'],expected_sha256='f'*64,read_source=read)
    for attempted,expected in ((1,'REQUEUED_ONE'),(2,'REPEATED_FAILURE_REVIEW_REQUIRED')):
        w.set(job,0,WorkStatus.FAILED,json.dumps({'error_type':'TimeoutError',
            'phase':'MODEL_AND_DERIVATION','last_attempt':attempted,'source_sha256':h}))
        assert q.requeue_failed(record['intake_id'],expected_revision=record['source_revision'],expected_sha256=h,read_source=read)==expected


def test_explicit_dependency_invalidated_when_target_revision_changes(tmp_path):
    from ai_foundation.knowledge_lifecycle import RelationProposal
    j=ReadonlyReceiptJournal(tmp_path/'work.db')
    a,b,c=atom(),atom('dependent'),atom(revision='2')
    for x in (a,b,c): j.record_atom(x)
    j.record_relation(RelationProposal('depends_on',b.atom_id,a.atom_id))
    j.reconcile_atom(c.atom_id)
    with sqlite3.connect(j.path) as db:
        assert db.execute("SELECT COUNT(*) FROM klm_relation_reviews WHERE reason='DEPENDENCY_REVIEW'").fetchone()[0]==1


def test_relation_window_overflow_cannot_finalize_success(tmp_path):
    from ai_foundation.klm_9b_handler import Existing9BKlmHandler
    j=ReadonlyReceiptJournal(tmp_path/'work.db')
    j.reconcile_atom=lambda *a,**kw: {'status':'CANDIDATE_WINDOW_EXCEEDED'}
    raw=b'{"text":"fixture"}'
    reply=json.dumps({'atoms':[{'candidate_id':1,'meaning':{
        'kind':'observation','modality':'assertion','polarity':'positive',
        'subject':'fixture','predicate':'state','object':'ready'}}]})
    handler=Existing9BKlmHandler(j,infer=lambda *a,**kw:reply,clock=lambda:100)
    pointer=dict(source_id='fixture',record_id='fixture',source_revision='1',privacy_scope='shareable')
    with pytest.raises(ValueError,match='CANDIDATE_WINDOW_EXCEEDED'):
        handler(pointer,dict(raw=raw,sha256=hashlib.sha256(raw).hexdigest()),deadline=200)
