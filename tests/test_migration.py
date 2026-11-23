import pytest
from ai_foundation.migration import Migrator,staged_update_preflight
from ai_foundation.productization import FoundationConfig

def test_current_schema_migration_is_noop(tmp_path):
 c=FoundationConfig(str((tmp_path/'data').resolve())); r=Migrator().migrate(c,tmp_path/'backup')
 assert not r.changed and r.from_version==r.to_version==1

def test_update_stage_must_be_empty_and_config_valid(tmp_path):
 c=FoundationConfig(str((tmp_path/'data').resolve())); stage=tmp_path/'stage'
 assert staged_update_preflight(c,stage)
 stage.mkdir(); (stage/'unknown').write_text('x')
 with pytest.raises(ValueError,match='empty'): staged_update_preflight(c,stage)

def test_cutover_registry_requires_rollback_metadata_and_fail_closed_transitions(tmp_path):
 from ai_foundation.migration import CutoverRegistry,UpdateRollbackError
 r=CutoverRegistry(tmp_path/'cutover.json')
 with pytest.raises(ValueError,match='complete'):r.prepare('local-inference','AI Home Server','', 'Foundation','127.0.0.1:8766','restore old endpoint')
 x=r.prepare('local-inference','AI Home Server','127.0.0.1:18787','Foundation','127.0.0.1:8766','restore authority to AI Home Server 127.0.0.1:18787 and read back','caller-config','authoritative-result')
 assert x.status=='PREPARED'
 with pytest.raises(UpdateRollbackError,match='conflict'):r.transition('local-inference','CUTOVER','ROLLED_BACK')
 assert r.transition('local-inference','PREPARED','CUTOVER').status=='CUTOVER'
 assert r.transition('local-inference','CUTOVER','ROLLED_BACK').status=='ROLLED_BACK'

def test_cutover_registry_survives_reconstruction(tmp_path):
 from ai_foundation.migration import CutoverRegistry
 p=tmp_path/'cutover.json';CutoverRegistry(p).prepare('local-inference','AI Home Server','127.0.0.1:18787','Foundation','127.0.0.1:8766','restore old endpoint then authoritative readback','caller-config','authoritative-result')
 assert CutoverRegistry(p).get('local-inference').previous_endpoint=='127.0.0.1:18787'


def test_cutover_prepare_rejects_unknown_switch_or_readback_target(tmp_path):
 from ai_foundation.migration import CutoverRegistry
 r=CutoverRegistry(tmp_path/'c.json')
 with pytest.raises(ValueError,match='complete'):
  r.prepare('local-inference','AI Home Server','127.0.0.1:18787','Foundation','127.0.0.1:8766','rollback','','')

def test_cutover_registry_preserves_rollback_and_recutover_history(tmp_path):
 from ai_foundation.migration import CutoverRegistry
 r=CutoverRegistry(tmp_path/'c.json')
 args=('human-console','HumanConsole','8790','Foundation','8793','restore HumanConsole','launchd','remote-readback')
 assert r.prepare(*args).generation==1
 r.transition('human-console','PREPARED','CUTOVER');r.transition('human-console','CUTOVER','ROLLED_BACK')
 assert r.prepare(*args).generation==2
 h=r.history('human-console')
 assert [(x.generation,x.status) for x in h]==[(1,'PREPARED'),(1,'CUTOVER'),(1,'ROLLED_BACK'),(2,'PREPARED')]
