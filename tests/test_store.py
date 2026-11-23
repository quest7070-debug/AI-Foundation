
def test_existing_effect_schema_migrates_and_transition_sets_recency(tmp_path):
 import sqlite3,time
 from ai_foundation.store import SQLiteGuardStore
 from ai_foundation.core import EffectStatus
 p=tmp_path/'g.db'
 with sqlite3.connect(p) as d:
  d.execute('CREATE TABLE effects (effect_id TEXT PRIMARY KEY,run_id TEXT NOT NULL,target TEXT NOT NULL,expected TEXT NOT NULL,status TEXT NOT NULL,paid_cost INTEGER NOT NULL DEFAULT 0)')
  d.execute("INSERT INTO effects VALUES ('e','r','t','x','EXECUTING',0)")
 s=SQLiteGuardStore(p)
 with sqlite3.connect(p) as d: assert 'updated_at' in {r[1] for r in d.execute('PRAGMA table_info(effects)')}
 assert s.transition_effect('e',EffectStatus.EXECUTING,EffectStatus.UNCERTAIN)
 with sqlite3.connect(p) as d: assert d.execute("SELECT updated_at FROM effects WHERE effect_id='e'").fetchone()[0]>0

def test_effect_save_only_advances_recency_on_status_change(tmp_path):
 import sqlite3,time
 from ai_foundation.store import SQLiteGuardStore
 from ai_foundation.core import GuardState,EffectIntent,EffectStatus
 p=tmp_path/'recency.db';s=SQLiteGuardStore(p);state=GuardState(effects={'e':EffectIntent('e','r','t','x',EffectStatus.EXECUTING,0)})
 s.save(state)
 with sqlite3.connect(p) as d:first=d.execute("select updated_at from effects where effect_id='e'").fetchone()[0]
 s.save(state)
 with sqlite3.connect(p) as d:assert d.execute("select updated_at from effects where effect_id='e'").fetchone()[0]==first
 state.effects['e'].status=EffectStatus.UNCERTAIN;s.save(state)
 with sqlite3.connect(p) as d:assert d.execute("select updated_at from effects where effect_id='e'").fetchone()[0]>=first
