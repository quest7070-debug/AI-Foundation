import io,json
import pytest
from ai_foundation.openai_local_adapter import OpenAILocalDiscovery,OpenAILocalExecution,OpenAILocalModelPolicy,LocalExecutionDispatcher

class Resp(io.BytesIO):
 def __enter__(self):return self
 def __exit__(self,*a):pass

def test_remote_local_requires_explicit_host_allowlist():
 with pytest.raises(ValueError):OpenAILocalDiscovery('http://10.0.0.50:8000',binding_prefix='local:mainpc',allowed_hosts=(),models=())

def test_discovery_grants_only_host_policy_not_runtime_claims():
 def op(req,timeout=0):return Resp(json.dumps({'data':[{'id':'model-a'},{'id':'evil'}]}).encode())
 d=OpenAILocalDiscovery('http://mainpc:8000',binding_prefix='local:mainpc',allowed_hosts=('mainpc',),models=(OpenAILocalModelPolicy('model-a','general',('CHAT',),('CHAT',)),),opener=op)
 rows=d();assert len(rows)==1 and rows[0].binding=='local:mainpc:general' and rows[0].capabilities==('CHAT',) and rows[0].model=='model-a' and rows[0].slot=='general'

def test_execution_maps_host_alias_to_runtime_model():
 seen={}
 def op(req,timeout=0):
  seen['body']=json.loads(req.data);return Resp(json.dumps({'choices':[{'message':{'content':'OK'}}]}).encode())
 x=OpenAILocalExecution('http://mainpc:8000',allowed_hosts=('mainpc',),alias_to_model={'general':'model-a'},opener=op)
 assert x.chat('hello',model='general')=='OK';assert seen['body']['model']=='model-a'
 with pytest.raises(ValueError):x.chat('x',model='untrusted')

def test_dispatcher_is_mechanical_by_selected_binding():
 a=object();b=object();d=LocalExecutionDispatcher(a,(('local:mainpc',b),))
 assert d.for_binding('local:mainpc:general') is b and d.for_binding('local:llama-swap:x') is a

def test_dispatcher_nonstrings_fail_closed_without_changing_exact_prefixes():
    default = object()
    strata = object()
    d = LocalExecutionDispatcher(
        default, by_prefix=(("local:mainpc-strata", strata),))
    for invalid in (None, False, 0, [], {}):
        assert d.for_binding(invalid) is default
    assert d.for_binding("local:mainpc-strata:code-agent") is strata
    assert d.for_binding("local:mainpc-strata-unauthorized") is default


def test_discovery_sends_bearer_auth_when_api_key_provided():
    seen={}
    def op(req,timeout=0):
        seen['auth']=req.headers.get('Authorization')
        return Resp(json.dumps({'data':[{'id':'model-a'}]}).encode())
    d=OpenAILocalDiscovery('http://mainpc:8000',binding_prefix='local:mainpc',allowed_hosts=('mainpc',),models=(OpenAILocalModelPolicy('model-a','general',('CHAT',),('CHAT',)),),opener=op,api_key='test-key')
    rows=d();assert len(rows)==1 and rows[0].health=='ONLINE'
    assert seen['auth']=='Bearer test-key'

def test_discovery_sends_no_auth_header_without_api_key():
    seen={}
    def op(req,timeout=0):
        seen['auth']=req.headers.get('Authorization')
        return Resp(json.dumps({'data':[{'id':'model-a'}]}).encode())
    d=OpenAILocalDiscovery('http://mainpc:8000',binding_prefix='local:mainpc',allowed_hosts=('mainpc',),models=(OpenAILocalModelPolicy('model-a','general',('CHAT',),('CHAT',)),),opener=op)
    d();assert seen['auth'] is None

def test_execution_sends_bearer_auth_and_request_defaults():
    seen={}
    def op(req,timeout=0):
        seen['auth']=req.headers.get('Authorization'); seen['timeout']=timeout; seen['body']=json.loads(req.data)
        return Resp(json.dumps({'choices':[{'message':{'content':'OK'}}]}).encode())
    x=OpenAILocalExecution('http://mainpc:8000',allowed_hosts=('mainpc',),alias_to_model={'general':'model-a'},opener=op,timeout=77,api_key='test-key',request_defaults={'reasoning_effort':'medium','max_tokens':123})
    assert x.chat('hi',model='general')=='OK'
    assert seen['auth']=='Bearer test-key' and seen['timeout']==77
    assert seen['body']['reasoning_effort']=='medium' and seen['body']['max_tokens']==123
    assert seen['body']['model']=='model-a' and seen['body']['stream'] is False

def test_execution_request_defaults_do_not_override_explicit_payload_fields():
    seen={}
    def op(req,timeout=0):
        seen['body']=json.loads(req.data)
        return Resp(json.dumps({'choices':[{'message':{'content':'OK'}}]}).encode())
    x=OpenAILocalExecution('http://mainpc:8000',allowed_hosts=('mainpc',),alias_to_model={'general':'model-a'},opener=op,request_defaults={'reasoning_effort':'medium','max_tokens':123})
    x.chat_payload({'messages':[{'role':'user','content':'x'}],'reasoning_effort':'high'},model='general')
    assert seen['body']['reasoning_effort']=='high' and seen['body']['max_tokens']==123

def test_execution_no_auth_and_default_timeout_unchanged_without_new_fields():
    seen={}
    def op(req,timeout=0):
        seen['auth']=req.headers.get('Authorization'); seen['timeout']=timeout
        return Resp(json.dumps({'choices':[{'message':{'content':'OK'}}]}).encode())
    x=OpenAILocalExecution('http://mainpc:8000',allowed_hosts=('mainpc',),alias_to_model={'general':'model-a'},opener=op)
    x.chat('hi',model='general')
    assert seen['auth'] is None and seen['timeout']==120

import json as _json

def test_local_endpoint_config_resolves_api_key_env_and_wires_options(tmp_path, monkeypatch):
    from ai_foundation.local_endpoint_config import load_local_endpoints
    monkeypatch.setenv('TEST_LOCAL_API_KEY','test-secret')
    p=tmp_path/'x.json';p.write_text(_json.dumps({'version':1,'endpoints':[{'name':'mainpc','base_url':'http://mainpc:8000','allowed_hosts':['mainpc'],'api_key_env':'TEST_LOCAL_API_KEY','discovery_timeout':9,'timeout':77,'request_defaults':{'reasoning_effort':'medium','max_tokens':64},'models':[{'runtime_model':'qwen','alias':'general','capabilities':['CHAT']}]}]}))
    _prefix, registry, execution = load_local_endpoints(p)[0]
    assert execution.api_key=='test-secret' and execution.timeout==77
    assert execution.request_defaults=={'reasoning_effort':'medium','max_tokens':64}
    discovery=registry.discovery
    assert discovery.api_key=='test-secret' and discovery.timeout==9

def test_local_endpoint_config_missing_api_key_env_raises(tmp_path, monkeypatch):
    from ai_foundation.local_endpoint_config import load_local_endpoints
    monkeypatch.delenv('MISSING_LOCAL_API_KEY', raising=False)
    p=tmp_path/'x.json';p.write_text(_json.dumps({'version':1,'endpoints':[{'name':'mainpc','base_url':'http://mainpc:8000','allowed_hosts':['mainpc'],'api_key_env':'MISSING_LOCAL_API_KEY','models':[{'runtime_model':'qwen','alias':'general','capabilities':['CHAT']}]}]}))
    with pytest.raises(ValueError):
        load_local_endpoints(p)

def test_local_endpoint_config_without_new_fields_preserves_defaults(tmp_path):
    from ai_foundation.local_endpoint_config import load_local_endpoints
    p=tmp_path/'x.json';p.write_text(_json.dumps({'version':1,'endpoints':[{'name':'mainpc','base_url':'http://mainpc:8000','allowed_hosts':['mainpc'],'models':[{'runtime_model':'qwen','alias':'general','capabilities':['CHAT']}]}]}))
    _prefix, registry, execution = load_local_endpoints(p)[0]
    assert execution.api_key is None and execution.timeout==120 and execution.request_defaults=={}
    discovery=registry.discovery
    assert discovery.api_key is None and discovery.timeout==2
