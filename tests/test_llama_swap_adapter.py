import io,json,pytest
from ai_foundation.llama_swap_adapter import LlamaSwapDiscovery,LlamaSwapExecution
class Resp(io.BytesIO):
 def __enter__(self):return self
 def __exit__(self,*a):pass
def test_discovery_online():
 def op(req,timeout=0):return Resp(json.dumps({'data':[{'id':'local-general','status':{'value':'unloaded'}}]}).encode())
 x=LlamaSwapDiscovery(opener=op)()[0];assert x.health=='ONLINE' and x.active and x.binding=='local:llama-swap:local-general' and x.model=='local-general'
def test_discovery_fail_closed():
 x=LlamaSwapDiscovery(opener=lambda *a,**k:(_ for _ in ()).throw(OSError()))()[0];assert x.health=='UNAVAILABLE'
def test_execution():
 seen={}
 def op(req,timeout=0):
  seen['body']=json.loads(req.data);return Resp(json.dumps({'choices':[{'message':{'content':'ok'}}]}).encode())
 assert LlamaSwapExecution(opener=op).chat('ping')=='ok';assert seen['body']['model']=='local-general'
def test_loopback_only():
 with pytest.raises(ValueError):LlamaSwapDiscovery('http://10.0.0.2:9292')
 with pytest.raises(ValueError):LlamaSwapExecution('http://10.0.0.2:9292')

def test_live_model_candidate_exposes_supported_llm_work_classes():
 d=LlamaSwapDiscovery(opener=lambda *a,**k: Resp(json.dumps({'data':[{'id':'local-general'}]}).encode()))
 c=d()[0]
 assert set(c.capabilities)=={'CHAT'} and c.roles==('CHAT',)
 assert 'COMPUTER_ACTION' not in c.capabilities

def test_local_execution_supplies_runtime_identity_context():
 seen={}
 def op(req,timeout=0):
  seen.update(json.loads(req.data));return Resp(json.dumps({'choices':[{'message':{'content':'local-general'}}]}).encode())
 assert LlamaSwapExecution(opener=op).chat('who are you')=='local-general'
 assert seen['messages'][0]['role']=='system' and 'Do not claim to be Gemini' in seen['messages'][0]['content']

def test_manifest_identity_slot_and_characteristics_are_separate_and_dynamic(tmp_path):
 manifest=tmp_path/'llama-swap.yaml'
 first_artifact=tmp_path/'models--org--First-Code-9B-GGUF/blobs/a'
 second_artifact=tmp_path/'models--org--Replacement-Code-12B-GGUF/blobs/b'
 for path in (first_artifact,second_artifact):
  path.parent.mkdir(parents=True);path.write_bytes(b'synthetic test artifact')
 manifest.write_text(f'''models:\n  local-code-agent:\n    cmd: >\n      llama-server --model "{first_artifact}"\n''')
 op=lambda *a,**k: Resp(json.dumps({'data':[{'id':'local-code-agent'}]}).encode())
 first=LlamaSwapDiscovery(opener=op,manifest_path=manifest)()[0]
 assert first.model=='org/First-Code-9B-GGUF'
 assert first.slot=='local-code-agent'
 assert first.characteristics==('CODE GENERATION',)
 assert first.capabilities==('CODE',)
 manifest.write_text(f'''models:\n  local-code-agent:\n    cmd: >\n      llama-server --model "{second_artifact}"\n''')
 second=LlamaSwapDiscovery(opener=op,manifest_path=manifest)()[0]
 assert second.model=='org/Replacement-Code-12B-GGUF'
 assert second.slot=='local-code-agent'
 assert second.capabilities==('CODE',)

def test_unknown_slot_is_visible_but_cannot_self_assign_authority(tmp_path):
 manifest=tmp_path/'llama-swap.yaml'
 manifest.write_text('''models:\n  local-new-slot:\n    cmd: >\n      llama-server --model "/cache/models--org--Mystery-GGUF/blobs/a"\n''')
 op=lambda *a,**k: Resp(json.dumps({'data':[{'id':'local-new-slot'}]}).encode())
 row=LlamaSwapDiscovery(opener=op,manifest_path=manifest)()[0]
 assert row.model=='org/Mystery-GGUF' and row.slot=='local-new-slot'
 assert row.capabilities==() and row.roles==() and row.characteristics==()
 assert row.reason=='UNASSIGNED_ROLE'

def test_host_owned_vision_role_is_explicitly_routable():
 op=lambda *a,**k: Resp(json.dumps({'data':[{'id':'local-vision','status':{'value':'unloaded'}}]}).encode())
 rows=LlamaSwapDiscovery(opener=op)()
 assert rows[0].capabilities==('VISION',) and rows[0].roles==('VISION',)


def test_missing_configured_artifact_is_not_an_online_routing_candidate(tmp_path):
 manifest=tmp_path/'llama-swap.yaml'
 manifest.write_text(f'models:\n  local-general:\n    cmd: server --model "{tmp_path}/absent-model.gguf"\n')
 op=lambda *a,**k: Resp(json.dumps({'data':[{'id':'local-general','status':{'value':'unloaded'}}]}).encode())
 row=LlamaSwapDiscovery(opener=op,manifest_path=manifest)()[0]
 assert row.health=='UNAVAILABLE' and not row.active
 assert row.reason=='MODEL_ARTIFACT_MISSING' and row.capabilities==() and row.roles==()

def test_existing_unloaded_artifact_with_spaces_remains_eligible(tmp_path):
 artifact=tmp_path/'model with spaces.gguf';artifact.write_bytes(b'synthetic test artifact')
 manifest=tmp_path/'llama-swap.yaml'
 manifest.write_text(f'models:\n  local-general:\n    cmd: server --model "{artifact}"\n')
 op=lambda *a,**k: Resp(json.dumps({'data':[{'id':'local-general','status':{'value':'unloaded'}}]}).encode())
 row=LlamaSwapDiscovery(opener=op,manifest_path=manifest)()[0]
 assert row.health=='ONLINE' and row.capabilities==('CHAT',)

def test_relative_artifact_path_is_not_resolved_in_a_guessed_working_directory(tmp_path):
 manifest=tmp_path/'llama-swap.yaml'
 manifest.write_text('models:\n  local-general:\n    cmd: server --model relative/model.gguf\n')
 op=lambda *a,**k: Resp(json.dumps({'data':[{'id':'local-general'}]}).encode())
 row=LlamaSwapDiscovery(opener=op,manifest_path=manifest)()[0]
 assert row.health=='ONLINE' and row.capabilities==('CHAT',)


def test_leased_llama_swap_call_is_deferred_without_sending_request(tmp_path):
 from ai_foundation.host_compute_lease import HostComputeLease, HostComputeBusy
 path=tmp_path/'owner'/'compute.lock'
 lease=HostComputeLease(path)
 calls=[]
 def op(req,timeout=0):
  calls.append(req)
  return Resp(json.dumps({'choices':[{'message':{'content':'ok'}}]}).encode())
 x=LlamaSwapExecution(opener=op,host_lease=lease)
 with lease.hold():
  with pytest.raises(HostComputeBusy):x.chat('hello')
 assert calls==[]
 assert x.chat('hello')=='ok' and len(calls)==1


@pytest.mark.parametrize("state", ["failed", "error", "unavailable", "disabled"])
def test_runtime_failure_is_not_a_healthy_service_or_active_model(state):
 op=lambda *a,**k: Resp(json.dumps({'data':[
  {'id':'local-code-agent','status':{'value':state}}]}).encode())
 row=LlamaSwapDiscovery(opener=op)()[0]
 assert row.health=='UNAVAILABLE' and row.active is False
 assert row.reason=='RUNTIME_'+state.upper()
 assert row.roles==() and row.capabilities==()
