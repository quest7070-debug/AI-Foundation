import json
from ai_foundation.capability_execution import CapabilityExecutor
from ai_foundation.capability_request import CapabilityRequest
class Out: status='VERIFIED_COMPLETE';route_binding='x'
class I:
 def run(self,plan,canon,function='CHAT'):
  assert function=='SEARCH';o=Out();o.result=json.dumps({'answer':'a','evidence':[{'source':'https://example.invalid','claim':'c','excerpt':'e','confidence':'test'}],'uncertainty':''});return o
class G: pass

def test_search_executes_canonical_research_adapter():
 row=json.loads(CapabilityExecutor(I(),G()).execute(CapabilityRequest('SEARCH'),'q','r'));assert row['answer']=='a' and row['evidence'][0]['source']=='https://example.invalid'

def test_data_executes_only_bound_operation():
 out=CapabilityExecutor(I(),G()).execute(CapabilityRequest('DATA',data_operation='json_summary'),'[1,2,3]','r')
 assert "'count': 3" in out and "'mean': 2.0" in out

def test_capability_activity_is_visible_only_during_execution():
 from ai_foundation.execution_activity import ExecutionActivityRegistry
 from ai_foundation.capability_request import CapabilityRequest
 a=ExecutionActivityRegistry()
 class D:
  def analyze(self,text): return type('R',(),{'output':'ok'})()
 x=CapabilityExecutor(I(),G(),activity=a)
 import ai_foundation.capability_execution as ce
 old=ce.build_data_specialist
 def build(_):
  class S:
   def analyze(self,text):
    rows=a.current()
    assert len(rows)==1 and rows[0].function=='DATA' and rows[0].kind=='CAPABILITY'
    return type('R',(),{'output':'ok'})()
  return S()
 ce.build_data_specialist=build
 try: assert x.execute(CapabilityRequest('DATA',data_operation='json_summary'),'[]','r')=='ok'
 finally: ce.build_data_specialist=old
 assert a.current()==()

def test_files_attachment_reads_only_host_resolved_grant(tmp_path):
 from ai_foundation.capability_request import AttachmentGrant
 p=tmp_path/'upload.txt';p.write_text('ATTACHMENT_REAL_CONTENT')
 req=CapabilityRequest('FILES',owner_id='u',attachments=(AttachmentGrant('f','u',str(p.resolve())),),attachment_ids=('f',))
 assert CapabilityExecutor(I(),G()).execute(req,'ignore prompt path','r')=='ATTACHMENT_REAL_CONTENT'

def test_search_accepts_single_json_code_fence_from_tool_provider():
 class FencedInference:
  def run(self,plan,canon,function='CHAT'):
   assert function=='SEARCH'
   o=Out();o.result='```json\n{"answer":"live","evidence":[{"source":"https://example.invalid","claim":"observed","excerpt":"x","confidence":0.9}],"uncertainty":""}\n```';return o
 row=json.loads(CapabilityExecutor(FencedInference(),G()).execute(CapabilityRequest('SEARCH'),'q','r'));assert row['answer']=='live' and row['evidence'][0]['claim']=='observed'

def test_code_accepts_repo_port_without_filesystem_port(monkeypatch):
 class Code:
  def inspect(self,text): return type('R',(),{'observed':'repo','test_result':'NOT_RUN: observational inspect','write_result':None})()
 monkeypatch.setattr('ai_foundation.capability_execution.build_coding_specialist',lambda request,guard,port,run_id,**kw: (port is repo and Code()) or None)
 repo=object()
 out=CapabilityExecutor(I(),G(),file_port=None,repo_port=repo).execute(CapabilityRequest('CODE',repo_root='/repo'),'x','r')
 row=json.loads(out)
 assert row=={'operation':'inspect','target':'x','observed':'repo','verification':'NOT_RUN: observational inspect','effect':None,'status':'INSPECTED'}

def test_files_attachment_lease_is_released_after_read(tmp_path):
 from ai_foundation.attachment_handoff import AttachmentHandoff,AttachmentRecord
 from ai_foundation.capability_request import CapabilityRequest
 root=tmp_path/'uploads';root.mkdir();h=AttachmentHandoff(root,lambda *_:AttachmentRecord('f','u',text='hello'))
 grant=h.resolve('u',['f'])[0]
 e=CapabilityExecutor(None,None,attachment_handoff=h)
 assert e.execute(CapabilityRequest(capability='FILES',owner_id='u',attachments=(grant,)),'','r')=='hello'
 assert not list(h.handoff_root.glob('*.lease'))


def test_code_change_routes_to_existing_verified_change(monkeypatch):
 seen={}
 class Code:
  def apply_verified_change(self,target,content):
   seen.update(target=target,content=content)
   return type('R',(),{'observed':'old','test_result':'before=ok; after=ok','write_result':'VERIFIED_COMPLETE','verified':True})()
 monkeypatch.setattr('ai_foundation.capability_execution.build_coding_specialist',
  lambda request,guard,port,run_id,**kw: Code())
 payload=json.dumps({'operation':'change','target':'a.py','content':'new'})
 row=json.loads(CapabilityExecutor(I(),G(),repo_port=object()).execute(
  CapabilityRequest('CODE',repo_root='/repo'),payload,'r'))
 assert seen=={'target':'a.py','content':'new'}
 assert row['effect']=='VERIFIED_COMPLETE'
 assert row['verification']=='before=ok; after=ok'
 assert row['status']=='VERIFIED_COMPLETE'


def test_browser_uses_only_host_bound_generic_mcp_grant():
 from ai_foundation.mcp_capability import MCPToolGrant,MCPToolRegistry
 class Client:
  def __init__(self,server): self.server=server
  def discover(self): return {'browser_snapshot':{'name':'browser_snapshot'},'browser_run_code_unsafe':{'name':'browser_run_code_unsafe'}}
  def call(self,tool,args): return {'server':self.server,'tool':tool,'args':args}
 registry=MCPToolRegistry(Client)
 registry.register(MCPToolGrant('browser-main','playwright',frozenset({'browser_snapshot'})))
 executor=CapabilityExecutor(I(),G(),mcp_registry=registry)
 req=CapabilityRequest('BROWSER',browser_target='browser-main')
 row=json.loads(executor.execute(req,json.dumps({'tool':'browser_snapshot','args':{}}),'r'))
 assert row=={'server':'playwright','tool':'browser_snapshot','args':{}}
 import pytest
 with pytest.raises(PermissionError):
  executor.execute(req,json.dumps({'tool':'browser_run_code_unsafe','args':{}}),'r')
 with pytest.raises(PermissionError):
  executor.execute(CapabilityRequest('BROWSER',browser_target='missing'),json.dumps({'tool':'browser_snapshot','args':{}}),'r')


def test_compute_uses_only_host_bound_generic_mcp_grant():
 from ai_foundation.mcp_capability import MCPToolGrant,MCPToolRegistry
 class Client:
  def __init__(self,server): self.server=server
  def discover(self): return {'execute_code':{'name':'execute_code'},'connect_to_jupyter':{'name':'connect_to_jupyter'},'restart_notebook':{'name':'restart_notebook'}}
  def call(self,tool,args): return {'server':self.server,'tool':tool,'args':args}
 registry=MCPToolRegistry(Client)
 registry.register(MCPToolGrant('compute-main','jupyter',frozenset({'execute_code'})))
 executor=CapabilityExecutor(I(),G(),mcp_registry=registry)
 req=CapabilityRequest('COMPUTE',compute_profile='compute-main')
 row=json.loads(executor.execute(req,json.dumps({'tool':'execute_code','args':{'code':'print(1)','timeout':2}}),'r'))
 assert row=={'server':'jupyter','tool':'execute_code','args':{'code':'print(1)','timeout':2}}
 import pytest
 with pytest.raises(PermissionError):
  executor.execute(req,json.dumps({'tool':'connect_to_jupyter','args':{'jupyter_url':'http://attacker'}}),'r')
 with pytest.raises(PermissionError):
  executor.execute(req,json.dumps({'tool':'restart_notebook','args':{'notebook_name':'x'}}),'r')
 with pytest.raises(PermissionError):
  executor.execute(CapabilityRequest('COMPUTE',compute_profile='missing'),json.dumps({'tool':'execute_code','args':{}}),'r')


def test_data_backend_uses_only_host_bound_generic_mcp_grant_and_never_compute():
 from ai_foundation.mcp_capability import MCPToolGrant,MCPToolRegistry
 import pytest
 class Client:
  def __init__(self,server): self.server=server
  def discover(self): return {'query':{'name':'query'},'save_query':{'name':'save_query'},'execute_code':{'name':'execute_code'}}
  def call(self,tool,args): return {'server':self.server,'tool':tool,'args':args}
 registry=MCPToolRegistry(Client)
 registry.register(MCPToolGrant('data-duckdb','duckdb',frozenset({'query'})))
 registry.register(MCPToolGrant('compute-main','jupyter',frozenset({'execute_code'})))
 executor=CapabilityExecutor(I(),G(),mcp_registry=registry)
 req=CapabilityRequest('DATA',data_backend='data-duckdb')
 row=json.loads(executor.execute(req,json.dumps({'tool':'query','args':{'sql':'SELECT 1'}}),'r'))
 assert row=={'server':'duckdb','tool':'query','args':{'sql':'SELECT 1'}}
 with pytest.raises(PermissionError):
  executor.execute(req,json.dumps({'tool':'save_query','args':{}}),'r')
 with pytest.raises(PermissionError):
  executor.execute(req,json.dumps({'tool':'execute_code','args':{'code':'print(1)'}}),'r')
 with pytest.raises(PermissionError):
  executor.execute(CapabilityRequest('DATA',data_backend='missing'),json.dumps({'tool':'query','args':{}}),'r')


def test_cross_backend_grants_cannot_be_widened_by_tool_output_or_args():
 from ai_foundation.mcp_capability import MCPToolGrant,MCPToolRegistry
 import pytest
 class Client:
  def __init__(self,server): self.server=server
  def discover(self):
   return {
    'browser_snapshot':{'name':'browser_snapshot'},
    'execute_code':{'name':'execute_code'},
    'query':{'name':'query'},
   }
  def call(self,tool,args): return {'server':self.server,'tool':tool,'args':args}
 r=MCPToolRegistry(Client)
 r.register(MCPToolGrant('browser-main','browser',frozenset({'browser_snapshot'})))
 r.register(MCPToolGrant('compute-main','compute',frozenset({'execute_code'})))
 r.register(MCPToolGrant('data-duckdb','data',frozenset({'query'})))
 e=CapabilityExecutor(I(),G(),mcp_registry=r)
 cases=(
  (CapabilityRequest('BROWSER',browser_target='browser-main'),'execute_code',{'code':'print(1)'}),
  (CapabilityRequest('COMPUTE',compute_profile='compute-main'),'query',{'sql':'SELECT 1'}),
  (CapabilityRequest('DATA',data_backend='data-duckdb'),'execute_code',{'code':'print(1)'}),
 )
 for req,tool,args in cases:
  with pytest.raises(PermissionError):
   e.execute(req,json.dumps({'tool':tool,'args':args,'grant':'compute-main','server':'attacker'}),'cross')



def test_host_numeric_array_contract_enforced_at_data_executor_boundary():
    import pytest
    req = CapabilityRequest(
        "DATA", owner_id="public-test", data_operation="json_summary",
        data_value_contract="numeric_array",
    )
    out = CapabilityExecutor(I(), G()).execute(req, "[3,7,11]", "fixed")
    assert "'count': 3" in out and "'mean': 7.0" in out
    for wrong in ('{"value":[3,7,11]}', '"[3,7,11]"', '[3,true,11]',
                  'null', '[3,7,1e100]'):
        with pytest.raises(ValueError, match="DATA_NUMERIC_ARRAY_CONTRACT_REQUIRED"):
            CapabilityExecutor(I(), G()).execute(req, wrong, "fixed")


def test_default_data_summary_continues_to_accept_objects():
    req = CapabilityRequest("DATA", data_operation="json_summary")
    out = CapabilityExecutor(I(), G()).execute(req, '{"values":[3,7,11]}', "fixed")
    assert "'type': 'object'" in out
    assert "'keys': ['values']" in out
