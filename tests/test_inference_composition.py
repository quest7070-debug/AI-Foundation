from pathlib import Path
from types import SimpleNamespace
from ai_foundation import inference_composition as m
class X:
 def __init__(self,*a,**k):pass
class Settings(X):
 def __init__(self,*a,**k):self.registry='registry';self.secret_store='secrets';self.optimized=0
 def optimize_all_routes(self):self.optimized+=1
def test_shared_inference_composition_uses_one_settings_local_and_attempt_store(tmp_path,monkeypatch):
 monkeypatch.setattr(m,'LocalComputeRegistry',X);monkeypatch.setattr(m,'LiveProviderProbe',X);monkeypatch.setattr(m,'SettingsService',Settings);monkeypatch.setattr(m,'ComputeRouter',X);monkeypatch.setattr(m,'ProviderResponseObserver',X);monkeypatch.setattr(m,'SQLiteInferenceAttemptStore',X);monkeypatch.setattr(m,'ObservedCloudExecution',X);monkeypatch.setattr(m,'GuardedInferenceService',X)
 c=SimpleNamespace(inference_db='attempts.sqlite');out=m.build_inference_composition(root=tmp_path,config=c,guard='g',transport='t')
 assert out.settings.optimized==1 and out.transport=='t'
 # The host must not re-enroll legacy M1 GGUF models as LLM fallbacks.
 assert len(out.local_compute.registries) == 1


def test_configured_remote_coder_cannot_occupy_fixed_same_host_9b_namespace(tmp_path):
 import json
 path=tmp_path/'endpoints.json'
 def endpoint(name):
  return {'name':name,'base_url':'http://mainpc:8000','allowed_hosts':['mainpc'],
          'models':[{'runtime_model':'remote-code-model','alias':'general',
                     'capabilities':['CODE'],'roles':['CODE']}]}
 path.write_text(json.dumps({'version':1,'endpoints':[
  endpoint('ollama-shared9b'),endpoint('ollama-shared9b:nested'),
  endpoint('llama-swap'),endpoint('llama-swap:nested'),
  endpoint('mainpc-strata')]}))
 rows=m._configured_endpoints(path)
 assert [row[0] for row in rows]==['local:mainpc-strata']
 assert rows[0][2].models=={'general':'remote-code-model'}
