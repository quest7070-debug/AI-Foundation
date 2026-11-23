import json,sqlite3
from dataclasses import asdict
from pathlib import Path
from .core import TaskPlan
class SQLiteReconciliationRegistry:
 """Durable non-secret recipe for reconstructing observe-only reconciliation."""
 def __init__(self,path,storage_admission=None):
  self.path=Path(path);self.storage_admission=storage_admission;self.path.parent.mkdir(parents=True,exist_ok=True)
  with sqlite3.connect(self.path) as d:d.execute('CREATE TABLE IF NOT EXISTS reconciliation_recipes(effect_id TEXT PRIMARY KEY, plan_json TEXT NOT NULL, port_binding TEXT NOT NULL)')
 def register(self,effect_id,plan,port_binding):
  if self.storage_admission:self.storage_admission.require('reconciliation recipe')
  if not effect_id or not port_binding: raise ValueError('effect_id and port_binding required')
  payload=json.dumps(asdict(plan),ensure_ascii=False,separators=(',',':'))
  with sqlite3.connect(self.path) as d:d.execute('INSERT INTO reconciliation_recipes VALUES(?,?,?) ON CONFLICT(effect_id) DO UPDATE SET plan_json=excluded.plan_json,port_binding=excluded.port_binding',(effect_id,payload,port_binding))
 def load(self,effect_id):
  with sqlite3.connect(self.path) as d:r=d.execute('SELECT plan_json,port_binding FROM reconciliation_recipes WHERE effect_id=?',(effect_id,)).fetchone()
  if not r:return None
  return TaskPlan(**json.loads(r[0])),r[1]
class ReconciliationService:
 def __init__(self,actions,registry,ports):self.actions=actions;self.registry=registry;self.ports=ports
 def capability(self,effect_id):
  recipe=self.registry.load(effect_id)
  if not recipe:return 'RECIPE_NOT_FOUND'
  return 'READY' if recipe[1] in self.ports else 'VERIFICATION_PORT_UNAVAILABLE'
 def can_reconcile(self,effect_id):return self.capability(effect_id)=='READY'
 def reconcile(self,effect_id):
  recipe=self.registry.load(effect_id)
  if not recipe:return {'ok':False,'status':'RECIPE_NOT_FOUND'}
  plan,binding=recipe;port=self.ports.get(binding)
  if port is None:return {'ok':False,'status':'VERIFICATION_PORT_UNAVAILABLE'}
  result=self.actions.reconcile_effect(effect_id,plan,port)
  return {'ok':result.ok,'status':result.status,'effect_id':effect_id}
