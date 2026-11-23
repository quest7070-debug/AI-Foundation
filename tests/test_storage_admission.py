from collections import namedtuple
import pytest
from ai_foundation.storage_admission import StorageAdmission,StorageCapacityError
from ai_foundation.task_intake import TaskIntake
from ai_foundation.attachment_handoff import AttachmentHandoff,AttachmentRecord
Usage=namedtuple('Usage','total used free')
def test_capacity_gate_blocks_before_task_durable_write(tmp_path):
 gate=StorageAdmission(tmp_path,min_free_bytes=100,disk_usage=lambda _:Usage(1000,950,50));intake=TaskIntake(tmp_path/'w.db',storage_admission=gate)
 with pytest.raises(StorageCapacityError):intake.submit('must not persist')
 assert intake.recent()==[]
def test_capacity_gate_recovers_when_space_returns(tmp_path):
 free=[50];gate=StorageAdmission(tmp_path,min_free_bytes=100,disk_usage=lambda _:Usage(1000,1000-free[0],free[0]));intake=TaskIntake(tmp_path/'w.db',storage_admission=gate)
 with pytest.raises(StorageCapacityError):intake.submit('first')
 free[0]=500;assert intake.submit('second').text=='second'
def test_capacity_gate_blocks_attachment_before_partial_file(tmp_path):
 root=tmp_path/'uploads';root.mkdir();gate=StorageAdmission(root,min_free_bytes=100,disk_usage=lambda _:Usage(1000,950,50));h=AttachmentHandoff(root,lambda *_:AttachmentRecord('f','u',text='secret'),storage_admission=gate)
 with pytest.raises(StorageCapacityError):h.resolve('u',['f'])
 assert not h.handoff_root.exists()

def test_capacity_gate_blocks_guard_authority_mutation(tmp_path):
 from ai_foundation.store import SQLiteGuardStore
 from ai_foundation.core import GuardState,EffectIntent,EffectStatus
 free=[500];gate=StorageAdmission(tmp_path,min_free_bytes=100,disk_usage=lambda _:Usage(1000,1000-free[0],free[0]));store=SQLiteGuardStore(tmp_path/'g.db',storage_admission=gate)
 free[0]=50
 state=GuardState(effects={'e':EffectIntent('e','r','t','x',EffectStatus.PLANNED,0)})
 with pytest.raises(StorageCapacityError):store.save(state)
 assert store.load().effects=={}
 free[0]=500;store.save(state);assert 'e' in store.load().effects

def test_capacity_gate_blocks_inference_evidence_before_dispatch_record(tmp_path):
 from ai_foundation.durable_inference import SQLiteInferenceAttemptStore
 free=[500];gate=StorageAdmission(tmp_path,min_free_bytes=100,disk_usage=lambda _:Usage(1000,1000-free[0],free[0]));store=SQLiteInferenceAttemptStore(tmp_path/'i.db',storage_admission=gate)
 free[0]=50
 with pytest.raises(StorageCapacityError):store.get_or_begin('r','cloud:x')
 assert store.get('r') is None
 free[0]=500;assert store.get_or_begin('r','cloud:x').status=='NEW'

def test_capacity_gate_blocks_reconciliation_recipe_write(tmp_path):
 from ai_foundation.reconciliation_registry import SQLiteReconciliationRegistry
 from ai_foundation.core import TaskPlan
 free=[500];gate=StorageAdmission(tmp_path,min_free_bytes=100,disk_usage=lambda _:Usage(1000,1000-free[0],free[0]));reg=SQLiteReconciliationRegistry(tmp_path/'r.db',storage_admission=gate)
 free[0]=50
 with pytest.raises(StorageCapacityError):reg.register('e',TaskPlan('r','write','t',effect_id='e'),'tool:x')
 assert reg.load('e') is None

def test_capacity_gate_blocks_provider_and_route_policy_mutations(tmp_path):
 from ai_foundation.provider_registry import SQLiteProviderRegistry
 from ai_foundation.routing import SQLiteRoutingPolicy
 free=[500];gate=StorageAdmission(tmp_path,min_free_bytes=100,disk_usage=lambda _:Usage(1000,1000-free[0],free[0]));reg=SQLiteProviderRegistry(tmp_path/'p.db',storage_admission=gate);route=SQLiteRoutingPolicy(tmp_path/'r.db',storage_admission=gate)
 free[0]=50
 with pytest.raises(StorageCapacityError):reg.upsert('b','GROQ')
 with pytest.raises(StorageCapacityError):route.optimize('CHAT',[{'binding':'b','health':'ONLINE','tier':'FREE'}])
 assert reg.bindings()==() and route.get('CHAT').primary is None

def test_capacity_gate_blocks_ui_preference_writes(tmp_path):
 from ai_foundation.notification_dismissal import NotificationDismissals
 from ai_foundation.presentation import PresentationPreferences
 free=[500];gate=StorageAdmission(tmp_path,min_free_bytes=100,disk_usage=lambda _:Usage(1000,1000-free[0],free[0]));n=NotificationDismissals(tmp_path/'w.db',gate);p=PresentationPreferences(tmp_path/'presentation.json',gate)
 free[0]=50
 with pytest.raises(StorageCapacityError):n.dismiss('x','WARN')
 with pytest.raises(StorageCapacityError):p.set('C')
 assert not n.hidden('x','WARN') and p.get()=='I'

def test_status_and_require_share_one_policy(tmp_path):
 free=[99];gate=StorageAdmission(tmp_path,min_free_bytes=100,disk_usage=lambda _:Usage(1000,1000-free[0],free[0]))
 status=gate.status();assert status.writable is False and status.free_bytes==99 and status.min_free_bytes==100
 with pytest.raises(StorageCapacityError):gate.require()
 free[0]=100;assert gate.status().writable is True and gate.require()==100

def test_long_term_health_uses_same_storage_admission_threshold(tmp_path):
 from ai_foundation.long_term_health import check_long_term_health
 free=[150];gate=StorageAdmission(tmp_path,min_free_bytes=200,disk_usage=lambda _:Usage(1000,1000-free[0],free[0]))
 health=check_long_term_health(tmp_path,storage_admission=gate,disk_warn_free_bytes=1)
 signal=next(x for x in health.signals if x.name=='free-space')
 assert signal.ok is False and '200 bytes required' in signal.detail
 free[0]=250;assert next(x for x in check_long_term_health(tmp_path,storage_admission=gate).signals if x.name=='free-space').ok is True
