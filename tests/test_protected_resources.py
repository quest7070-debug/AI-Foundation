from pathlib import Path
import pytest
from ai_foundation.protected_resources import ProtectedResources,production_protected_resources
from ai_foundation.file_execution import FileScope,ScopedFileExecution
from ai_foundation.guard import GuardCore
from ai_foundation.core import GuardState
class Port:
 def execute(self,p):pass
 def observe(self,p):return ''
def test_four_model_mutation_surfaces_are_denied(tmp_path):
 model=tmp_path/'models';p=ProtectedResources((str(model),))
 for target in (model/'q.gguf',model/'registry.json',model/'llama-swap.yaml',model/'active-model'):
  with pytest.raises(PermissionError):p.validate_write(target)
 for action in ('fine-tune-model','train_lora','model-register','model-switch','model-load','model-replace'):
  with pytest.raises(PermissionError):p.validate_action(action)
def test_model_file_suffix_denied_even_outside_known_root(tmp_path):
 p=ProtectedResources()
 for name in ('x.gguf','x.safetensors','x.ckpt'):
  with pytest.raises(PermissionError):p.validate_write(tmp_path/name)
def test_write_scope_cannot_be_rooted_inside_protected_tree(tmp_path):
 protected=tmp_path/'local-compute';protected.mkdir()
 with pytest.raises(PermissionError):
  ScopedFileExecution(GuardCore(GuardState()),Port(),FileScope(str(protected),write=True),protected=ProtectedResources((str(protected),)))
def test_normal_repo_write_scope_still_allowed(tmp_path):
 repo=tmp_path/'repo';repo.mkdir();model=tmp_path/'models';model.mkdir()
 x=ScopedFileExecution(GuardCore(GuardState()),Port(),FileScope(str(repo),write=True),protected=ProtectedResources((str(model),)))
 assert x.scope.write
def test_production_set_covers_foundation_runtime_and_model_caches(tmp_path,monkeypatch):
 home=tmp_path/'home'
 home.mkdir()
 monkeypatch.setenv('HOME',str(home))
 p=production_protected_resources(tmp_path)
 assert p.protects_path(tmp_path/'local-compute'/'llama-swap.yaml')
 assert any('.cache/huggingface' in x for x in p.normalized_roots())
 assert p.protects_path(home/'.cache'/'huggingface'/'tokenizer.json')
