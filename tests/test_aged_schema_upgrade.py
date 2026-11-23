import sqlite3
from ai_foundation.store import SQLiteGuardStore
from ai_foundation.durable_work import SQLiteWorkStore
from ai_foundation.provider_registry import SQLiteProviderRegistry

def test_representative_legacy_sqlite_shapes_upgrade_without_data_loss(tmp_path):
    n=10_000; g=tmp_path/'g.db'; w=tmp_path/'w.db'; p=tmp_path/'p.sqlite'
    with sqlite3.connect(g) as d:
        d.execute('CREATE TABLE effects(effect_id TEXT PRIMARY KEY,run_id TEXT NOT NULL,target TEXT NOT NULL,expected TEXT NOT NULL,status TEXT NOT NULL,paid_cost INTEGER NOT NULL DEFAULT 0)')
        d.executemany('INSERT INTO effects VALUES(?,?,?,?,?,?)',((f'e{x}',f'r{x}','t','x','VERIFIED',x%7) for x in range(n)))
    with sqlite3.connect(w) as d:
        d.execute('CREATE TABLE work_steps(job_id TEXT,position INTEGER,name TEXT,status TEXT,result TEXT,PRIMARY KEY(job_id,position))')
        d.execute('CREATE TABLE human_inputs(job_id TEXT NOT NULL,position INTEGER NOT NULL,response TEXT NOT NULL,created_at REAL NOT NULL,consumed_at REAL,PRIMARY KEY(job_id,position,created_at))')
        d.executemany('INSERT INTO work_steps VALUES(?,?,?,?,?)',((f'j{x}',0,'n','VERIFIED',f'r{x}') for x in range(n)))
        d.executemany('INSERT INTO human_inputs VALUES(?,?,?,?,?)',((f'j{x}',0,'x',x,x) for x in range(n)))
    with sqlite3.connect(p) as d:
        d.execute('CREATE TABLE provider_credentials(binding TEXT PRIMARY KEY,provider TEXT NOT NULL,tier TEXT NOT NULL,health TEXT NOT NULL,short_remaining REAL,short_reset TEXT,long_remaining REAL,long_reset TEXT,active INTEGER NOT NULL DEFAULT 0,reason TEXT,updated_at REAL NOT NULL, future_marker TEXT)')
        d.executemany('INSERT INTO provider_credentials VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',((f'b{x}','P','FREE','ONLINE',None,None,None,None,0,None,x,'keep') for x in range(n)))
    SQLiteGuardStore(g); SQLiteWorkStore(w); SQLiteProviderRegistry(p)
    with sqlite3.connect(g) as d:
        assert d.execute('SELECT COUNT(*),SUM(paid_cost),SUM(updated_at) FROM effects').fetchone()==(n,sum(x%7 for x in range(n)),0.0)
        assert d.execute('PRAGMA quick_check').fetchone()[0]=='ok'
    with sqlite3.connect(w) as d:
        assert d.execute('SELECT COUNT(*),SUM(length(result)),SUM(updated_at) FROM work_steps').fetchone()==(n,sum(len(f'r{x}') for x in range(n)),0.0)
        assert d.execute('SELECT COUNT(*),COUNT(context_digest) FROM human_inputs').fetchone()==(n,0)
        assert d.execute('PRAGMA quick_check').fetchone()[0]=='ok'
    with sqlite3.connect(p) as d:
        cols={r[1] for r in d.execute('PRAGMA table_info(provider_credentials)')}
        assert {'endpoint','model','auth_style','protocol','capabilities','future_marker'}<=cols
        assert d.execute("SELECT COUNT(*) FROM provider_credentials WHERE future_marker='keep'").fetchone()[0]==n
        assert d.execute('PRAGMA quick_check').fetchone()[0]=='ok'
