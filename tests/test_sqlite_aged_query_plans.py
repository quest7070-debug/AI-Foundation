import sqlite3
from ai_foundation.store import SQLiteGuardStore
from ai_foundation.durable_work import SQLiteWorkStore
from ai_foundation.durable_inference import SQLiteInferenceAttemptStore
from ai_foundation.task_intake import TaskIntake

def plan(db,sql,args=()):
    with sqlite3.connect(db) as c:return ' | '.join(r[3] for r in c.execute('EXPLAIN QUERY PLAN '+sql,args))

def test_aged_operator_and_retention_paths_have_dedicated_indexes(tmp_path):
    g=tmp_path/'g.db';w=tmp_path/'w.db';i=tmp_path/'i.db'
    SQLiteGuardStore(g);SQLiteWorkStore(w);SQLiteInferenceAttemptStore(i);TaskIntake(w)
    with sqlite3.connect(g) as c:
        c.executemany('INSERT INTO effects(effect_id,run_id,target,expected,status,paid_cost,updated_at) VALUES(?,?,?,?,?,?,?)',((f'e{x}',f'r{x}','t','x','FAILED' if x%10==0 else 'VERIFIED',0,x) for x in range(2000)))
        c.executemany('INSERT INTO approval_requests(run_id,action,target,updated_at) VALUES(?,?,?,?)',((f'r{x}','a','t',x) for x in range(2000)))
        c.executemany('INSERT INTO effect_claims VALUES(?,?,?)',((f'e{x}','o',x) for x in range(2000)))
    with sqlite3.connect(w) as c:
        c.executemany('INSERT INTO task_intake VALUES(?,?,?)',((f'j{x}','x',x) for x in range(2000)))
        c.executemany('INSERT INTO work_steps(job_id,position,name,status,result,updated_at) VALUES(?,?,?,?,?,?)',((f'j{x}',0,'n','FAILED' if x%10==0 else 'VERIFIED','',x) for x in range(2000)))
        c.executemany('INSERT INTO human_inputs VALUES(?,?,?,?,?,?)',((f'j{x}',0,'x',x,x if x%2 else None,'d') for x in range(2000)))
    with sqlite3.connect(i) as c:c.executemany('INSERT INTO inference_attempts VALUES(?,?,?,?,?)',((f'q{x}','b','FAILED','',x) for x in range(2000)))
    assert 'idx_effects_status_updated' in plan(g,"SELECT effect_id FROM effects WHERE status='FAILED' ORDER BY updated_at DESC LIMIT 100")
    assert 'idx_approval_requests_updated' in plan(g,'SELECT run_id FROM approval_requests ORDER BY updated_at DESC,run_id LIMIT 100')
    assert 'idx_effect_claims_expires' in plan(g,'DELETE FROM effect_claims WHERE expires<?',(1000,))
    assert 'idx_work_steps_status_updated' in plan(w,"SELECT job_id FROM work_steps WHERE status='FAILED' ORDER BY updated_at DESC LIMIT 100")
    assert 'idx_task_intake_recent' in plan(w,'SELECT job_id FROM task_intake ORDER BY created_at DESC,job_id DESC LIMIT 20')
    assert 'idx_human_inputs_pending' in plan(w,"SELECT response FROM human_inputs WHERE job_id='j1999' AND position=0 AND consumed_at IS NULL ORDER BY created_at LIMIT 1")
    assert 'idx_human_inputs_consumed' in plan(w,'DELETE FROM human_inputs WHERE consumed_at IS NOT NULL AND consumed_at<?',(1000,))
    assert 'idx_inference_terminal_updated' in plan(i,"DELETE FROM inference_attempts WHERE status IN ('VERIFIED','FAILED') AND updated_at<?",(1000,))

def test_runtime_guard_state_does_not_materialize_historical_authority(tmp_path):
    g=tmp_path/'g.db';store=SQLiteGuardStore(g)
    with sqlite3.connect(g) as c:
        c.executemany('INSERT INTO approvals(run_id) VALUES(?)',((f'r{x}',) for x in range(10_000)))
        c.executemany('INSERT INTO cancellations(run_id) VALUES(?)',((f'c{x}',) for x in range(10_000)))
        c.executemany('INSERT INTO effects(effect_id,run_id,target,expected,status,paid_cost,updated_at) VALUES(?,?,?,?,?,?,?)',((f'e{x}',f'r{x}','t','x','VERIFIED',0,x) for x in range(10_000)))
    state=store.runtime_state()
    assert state.effects=={} and state.approvals==set() and state.cancellations==set()
    assert store.is_approved('r9999') and store.is_cancelled('c9999') and store.get_effect('e9999').status.value=='VERIFIED'

def test_terminal_purge_handles_more_than_sql_variable_limit_without_python_id_list(tmp_path):
    w=tmp_path/'w.db';intake=TaskIntake(w)
    n=35_000
    with sqlite3.connect(w) as c:
        c.executemany('INSERT INTO task_intake VALUES(?,?,?)',((f'j{x}','x',x) for x in range(n)))
        c.executemany('INSERT INTO work_steps(job_id,position,name,status,result,updated_at) VALUES(?,?,?,?,?,?)',((f'j{x}',0,'n','VERIFIED','',x) for x in range(n)))
    assert intake.purge_terminal()==n
    with sqlite3.connect(w) as c:
        assert c.execute('SELECT COUNT(*) FROM task_intake').fetchone()[0]==0
        assert c.execute('SELECT COUNT(*) FROM work_steps').fetchone()[0]==0

def test_first_party_sqlite_reads_are_keyed_aggregate_or_explicitly_bounded():
    """Static regression: new SQLite reads cannot silently add an unbounded history scan."""
    import ast
    from pathlib import Path
    allowed_unbounded={
      ('store.py','SELECT run_id FROM approvals'),
      ('store.py','SELECT run_id FROM cancellations'),
      ('store.py','SELECT effect_id,run_id,target,expected,status,paid_cost FROM effects'),
      # Legacy load() is retained for compatibility/tests, but canonical startup/runtime does not call it.
      ('provider_registry.py','SELECT binding,provider,tier,health,short_remaining,short_reset,long_remaining,long_reset,active,reason,updated_at FROM provider_credentials ORDER BY provider,tier,binding'),
      ('provider_registry.py','SELECT binding,provider,tier,health,short_remaining,short_reset,long_remaining,long_reset,active,reason,updated_at,endpoint,model,auth_style,protocol,capabilities FROM provider_credentials ORDER BY binding'),
      ('provider_registry.py','SELECT binding FROM provider_credentials ORDER BY binding'),
    }
    offenders=[]; root=Path(__file__).parents[1]/'src'/'ai_foundation'
    for p in root.glob('*.py'):
      tree=ast.parse(p.read_text())
      for n in ast.walk(tree):
        if not isinstance(n,ast.Call) or not isinstance(n.func,ast.Attribute) or n.func.attr!='execute' or not n.args:continue
        try:q=ast.literal_eval(n.args[0])
        except Exception:continue
        if not isinstance(q,str) or not q.lstrip().upper().startswith('SELECT'):continue
        u=' '.join(q.upper().split())
        keyed=(' WHERE ' in u or ' LIMIT ' in u or 'COUNT(' in u or 'SUM(' in u or 'GROUP BY' in u or 'SQLITE_MASTER' in u)
        if not keyed and (p.name,q) not in allowed_unbounded:offenders.append((p.name,n.lineno,q))
    assert offenders==[]

def test_human_task_composition_batches_work_lookup(tmp_path,monkeypatch):
    from ai_foundation.human_operations import tasks
    w=tmp_path/'w.db'; intake=TaskIntake(w)
    with sqlite3.connect(w) as c:
        c.executemany('INSERT INTO task_intake VALUES(?,?,?)',((f'j{x}','x',x) for x in range(20)))
        c.executemany('INSERT INTO work_steps(job_id,position,name,status,result,updated_at) VALUES(?,?,?,?,?,?)',((f'j{x}',0,'n','FAILED','',x) for x in range(20)))
    calls={'many':0,'one':0}; orig_many=intake.store.load_many; orig_one=intake.store.load
    def many(ids):calls['many']+=1;return orig_many(ids)
    def one(job):calls['one']+=1;return orig_one(job)
    monkeypatch.setattr(intake.store,'load_many',many);monkeypatch.setattr(intake.store,'load',one)
    assert len(tasks(intake,20))==20
    assert calls=={'many':1,'one':0}

def test_attachment_and_reconciliation_lookup_are_single_keyed_owner_queries(tmp_path):
    from ai_foundation.librechat_attachment_lookup import LibreChatAttachmentLookup
    from ai_foundation.reconciliation_registry import SQLiteReconciliationRegistry
    from ai_foundation.core import TaskPlan
    seen=[]
    lookup=LibreChatAttachmentLookup(tmp_path,lambda q:(seen.append(q) or {'file_id':q['file_id'],'user':q['user'],'text':'x'}))
    assert lookup('f','u').text=='x' and seen==[{'file_id':'f','user':'u'}]
    reg=SQLiteReconciliationRegistry(tmp_path/'r.db'); plan=TaskPlan('r','READ','t','x')
    reg.register('e',plan,'p')
    assert reg.load('e')[1]=='p'
    assert 'sqlite_autoindex_reconciliation_recipes_1' in plan_query(tmp_path/'r.db','SELECT plan_json,port_binding FROM reconciliation_recipes WHERE effect_id=?',('e',))

def plan_query(db,sql,args=()):
    with sqlite3.connect(db) as c:return ' | '.join(r[3] for r in c.execute('EXPLAIN QUERY PLAN '+sql,args))
