from pathlib import Path
import os
import pytest
from ai_foundation.core import CanonContract, GuardState, TaskPlan
from ai_foundation.guard import GuardCore
from ai_foundation.store import SQLiteGuardStore
from ai_foundation.toolhive import ToolHiveFilesystemPort

ROOT=Path(__file__).parents[1]
THV=ROOT/'.tools/toolhive/thv'
MOUNT=Path('/tmp/ai-foundation-toolhive')


def test_toolhive_read_missing_file_fails_explicitly():
    port=ToolHiveFilesystemPort('/nonexistent','x',MOUNT)
    missing=MOUNT/'definitely-missing-foundation-file.txt'
    missing.unlink(missing_ok=True)
    with pytest.raises(FileNotFoundError,match='file not found in bound scope'):
        port.observe(TaskPlan('missing','read',str(missing),canon_revision='c1'))

@pytest.mark.skipif(os.getenv('AI_FOUNDATION_TOOLHIVE_E2E') != '1' or not THV.exists(), reason='live ToolHive E2E is opt-in')
def test_guard_toolhive_real_mcp_effect_e2e(tmp_path):
    target=MOUNT/'guard-e2e.txt'
    target.unlink(missing_ok=True)
    port=ToolHiveFilesystemPort(THV,'ai-foundation-fs',MOUNT)
    store=SQLiteGuardStore(tmp_path/'g.db')
    plan=TaskPlan('toolhive-e2e','write',str(target),text='guard-toolhive-verified',canon_revision='c1',exclusive_target=True)
    assert GuardCore(store.load(),100,store).execute(plan,CanonContract('repo','c1'),port,'guard-toolhive-verified') == 'VERIFIED_COMPLETE'
    assert target.read_text() == 'guard-toolhive-verified'
    assert store.load().effects['toolhive-e2e'].status.value == 'VERIFIED'

def test_toolhive_port_rejects_target_outside_mount():
    port=ToolHiveFilesystemPort('/nonexistent','x',MOUNT)
    with pytest.raises(ValueError,match='outside'):
        port.execute(TaskPlan('r','write','/tmp/outside.txt',text='x',canon_revision='c1'))


def test_toolhive_port_rejects_parent_escape():
    port=ToolHiveFilesystemPort('/nonexistent','x',MOUNT)
    with pytest.raises(ValueError,match='outside'):
        port.execute(TaskPlan('r2','write',str(MOUNT/'..'/'escaped.txt'),text='x',canon_revision='c1'))

@pytest.mark.skipif(os.getenv('AI_FOUNDATION_TOOLHIVE_E2E') != '1' or not THV.exists(), reason='live ToolHive E2E is opt-in')
def test_toolhive_server_itself_denies_outside_mount():
    import subprocess
    cp=subprocess.run([str(THV),'mcp','call','read_text_file','--server','ai-foundation-fs','--format','json','--args','{"path":"/etc/passwd"}'],capture_output=True,text=True,timeout=30)
    assert cp.returncode != 0
    assert 'Access denied' in cp.stdout

@pytest.mark.skipif(os.getenv('AI_FOUNDATION_TOOLHIVE_E2E') != '1' or not THV.exists(), reason='live ToolHive E2E is opt-in')
def test_guard_reconciles_real_mcp_effect_after_lost_response(tmp_path):
    target=MOUNT/'lost-response.txt'
    target.unlink(missing_ok=True)
    base=ToolHiveFilesystemPort(THV,'ai-foundation-fs',MOUNT)
    class LostResponsePort:
        def __init__(self): self.execute_count=0
        def execute(self,plan):
            self.execute_count += 1
            base.execute(plan)
            raise ConnectionError('simulated response loss after MCP effect')
        def observe(self,plan): return base.observe(plan)
    port=LostResponsePort()
    store=SQLiteGuardStore(tmp_path/'g.db')
    plan=TaskPlan('toolhive-lost-response','write',str(target),text='effect-once',canon_revision='c1',exclusive_target=True)
    canon=CanonContract('repo','c1')
    first=GuardCore(store.load(),100,store).execute(plan,canon,port,'effect-once')
    assert first == 'UNCERTAIN_RECONCILE_REQUIRED'
    assert target.read_text() == 'effect-once'
    second=GuardCore(store.load(),100,store).execute(plan,canon,port,'effect-once')
    assert second == 'VERIFIED_COMPLETE'
    assert port.execute_count == 1
    assert store.load().effects[plan.run_id].status.value == 'VERIFIED'

@pytest.mark.skipif(os.getenv('AI_FOUNDATION_TOOLHIVE_E2E') != '1' or not THV.exists(), reason='live ToolHive E2E is opt-in')
def test_real_process_death_after_mcp_effect_reconciles_without_reexecution(tmp_path):
    import subprocess, sys, time
    db=tmp_path/'crash.db'; target=MOUNT/'real-process-crash.txt'; marker=tmp_path/'done'
    target.unlink(missing_ok=True)
    script=tmp_path/'child.py'
    script.write_text(f"""
import os
from pathlib import Path
from ai_foundation.core import CanonContract,TaskPlan
from ai_foundation.guard import GuardCore
from ai_foundation.store import SQLiteGuardStore
from ai_foundation.toolhive import ToolHiveFilesystemPort
db=SQLiteGuardStore({str(db)!r}); base=ToolHiveFilesystemPort({str(THV)!r},'ai-foundation-fs',{str(MOUNT)!r})
class Crash:
 def execute(self,p):
  base.execute(p); Path({str(marker)!r}).write_text('done'); os.kill(os.getpid(),9)
 def observe(self,p): return base.observe(p)
p=TaskPlan('real-process-crash','write',{str(target)!r},text='crash-once',canon_revision='c1',exclusive_target=True,paid_cost=1)
GuardCore(db.load(),100,db,claim_ttl=.2).execute(p,CanonContract('repo','c1'),Crash(),'crash-once')
""")
    env={**os.environ,'PYTHONPATH':str(ROOT/'src')}
    cp=subprocess.run([sys.executable,str(script)],cwd=ROOT,env=env,capture_output=True,text=True)
    assert cp.returncode != 0 and marker.exists() and target.read_text() == 'crash-once'
    store=SQLiteGuardStore(db); assert store.load().effects['real-process-crash'].status.value == 'EXECUTING'
    time.sleep(.25)
    class NoExecute(ToolHiveFilesystemPort):
        def execute(self,p): raise AssertionError('must reconcile, not execute again')
    port=NoExecute(THV,'ai-foundation-fs',MOUNT)
    p=TaskPlan('real-process-crash','write',str(target),text='crash-once',canon_revision='c1',exclusive_target=True,paid_cost=1)
    assert GuardCore(store.load(),100,store,claim_ttl=.2).execute(p,CanonContract('repo','c1'),port,'crash-once') == 'VERIFIED_COMPLETE'
    assert target.read_text() == 'crash-once'

@pytest.mark.skipif(os.getenv('AI_FOUNDATION_TOOLHIVE_E2E') != '1' or not THV.exists(), reason='live ToolHive E2E is opt-in')
def test_container_restart_after_ambiguous_effect_reconciles_without_duplicate(tmp_path):
    import subprocess
    target=MOUNT/'container-restart.txt'; target.unlink(missing_ok=True)
    base=ToolHiveFilesystemPort(THV,'ai-foundation-fs',MOUNT)
    store=SQLiteGuardStore(tmp_path/'container.db')
    plan=TaskPlan('container-restart','write',str(target),text='persisted-once',canon_revision='c1',exclusive_target=True)
    class Lost:
        def __init__(self): self.execute_count=0
        def execute(self,p):
            self.execute_count += 1
            base.execute(p)
            raise ConnectionError('ambiguous completion before container restart')
        def observe(self,p): return base.observe(p)
    lost=Lost()
    assert GuardCore(store.load(),100,store).execute(plan,CanonContract('repo','c1'),lost,'persisted-once') == 'UNCERTAIN_RECONCILE_REQUIRED'
    assert lost.execute_count == 1 and target.read_text() == 'persisted-once'
    env={**os.environ,'AI_FOUNDATION_THV':str(THV)}
    lifecycle=ROOT/'scripts/toolhive-filesystem.sh'
    subprocess.run([str(lifecycle),'stop'],cwd=ROOT,env=env,check=True,capture_output=True,text=True,timeout=30)
    subprocess.run([str(lifecycle),'ensure'],cwd=ROOT,env=env,check=True,capture_output=True,text=True,timeout=60)
    class NoExecute(ToolHiveFilesystemPort):
        def execute(self,p): raise AssertionError('must reconcile, not execute twice')
    port=NoExecute(THV,'ai-foundation-fs',MOUNT)
    assert GuardCore(store.load(),100,store).execute(plan,CanonContract('repo','c1'),port,'persisted-once') == 'VERIFIED_COMPLETE'
    assert target.read_text() == 'persisted-once'
    assert store.load().effects[plan.run_id].status.value == 'VERIFIED'

@pytest.mark.skipif(os.getenv('AI_FOUNDATION_TOOLHIVE_E2E') != '1' or not THV.exists(), reason='live ToolHive E2E is opt-in')
def test_agent_guarded_gateway_to_real_toolhive_mcp(tmp_path):
    from ai_foundation.agent_tools import GuardedToolGateway
    target=MOUNT/'agent-guarded-e2e.txt'; target.unlink(missing_ok=True)
    store=SQLiteGuardStore(tmp_path/'agent.db')
    port=ToolHiveFilesystemPort(THV,'ai-foundation-fs',MOUNT)
    tool=GuardedToolGateway(GuardCore(store.load(),100,store),CanonContract('repo','c1'),port)
    assert tool.write(run_id='agent-mcp',target=str(target),content='agent-via-guard',canon_revision='c1') == 'VERIFIED_COMPLETE'
    assert target.read_text() == 'agent-via-guard'
    assert store.load().effects['agent-mcp'].status.value == 'VERIFIED'

@pytest.mark.skipif(os.getenv('AI_FOUNDATION_TOOLHIVE_E2E') != '1' or not THV.exists(), reason='live ToolHive E2E is opt-in')
def test_cancel_during_real_mcp_effect_reconciles_without_duplicate(tmp_path):
    import threading
    target=MOUNT/'cancel-real-mcp.txt'; target.unlink(missing_ok=True)
    base=ToolHiveFilesystemPort(THV,'ai-foundation-fs',MOUNT)
    store=SQLiteGuardStore(tmp_path/'cancel.db'); started=threading.Event(); release=threading.Event()
    class DelayedReturn:
        def __init__(self): self.execute_count=0
        def execute(self,p):
            self.execute_count += 1; base.execute(p); started.set(); release.wait(5)
        def observe(self,p): return base.observe(p)
    port=DelayedReturn(); plan=TaskPlan('cancel-real','write',str(target),text='remote-once',canon_revision='c1',exclusive_target=True)
    out=[]; g=GuardCore(store.load(),100,store)
    t=threading.Thread(target=lambda: out.append(g.execute(plan,CanonContract('repo','c1'),port,'remote-once')))
    t.start(); assert started.wait(5)
    GuardCore(store.load(),100,store).cancel('cancel-real'); release.set(); t.join(5)
    assert out == ['CANCELLED_RECONCILE_REQUIRED'] and port.execute_count == 1 and target.read_text() == 'remote-once'
    assert store.load().effects['cancel-real'].status.value == 'UNCERTAIN'
    assert GuardCore(store.load(),100,store).execute(plan,CanonContract('repo','c1'),port,'remote-once') == 'DENY'
    assert port.execute_count == 1

def test_generic_mcp_client_binds_server_and_discovered_tool(monkeypatch):
    import subprocess, json
    from ai_foundation.toolhive import ToolHiveMCPClient
    calls=[]
    def fake(argv,**kwargs):
        calls.append(argv)
        if argv[2]=='list':
            return subprocess.CompletedProcess(argv,0,json.dumps({'tools':[{'name':'echo','inputSchema':{'type':'object'}}]}),'')
        return subprocess.CompletedProcess(argv,0,json.dumps({'content':[{'type':'text','text':'ok'}]}),'')
    monkeypatch.setattr(subprocess,'run',fake)
    c=ToolHiveMCPClient('/thv','safe-server')
    assert set(c.discover())=={'echo'}
    assert c.call('echo',{'message':'hi'})['content'][0]['text']=='ok'
    assert all(a[a.index('--server')+1]=='safe-server' for a in calls)

def test_generic_mcp_client_rejects_unknown_tool_before_call(monkeypatch):
    import subprocess, json, pytest
    from ai_foundation.toolhive import ToolHiveMCPClient
    calls=[]
    def fake(argv,**kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv,0,json.dumps({'tools':[{'name':'echo'}]}),'')
    monkeypatch.setattr(subprocess,'run',fake)
    with pytest.raises(ValueError,match='unknown'):
        ToolHiveMCPClient('/thv','safe-server').call('write_anything',{})
    assert len(calls)==1 and calls[0][2]=='list'

def test_generic_mcp_client_redacts_process_failure(monkeypatch):
    import subprocess, pytest
    from ai_foundation.toolhive import ToolHiveMCPClient
    monkeypatch.setattr(subprocess,'run',lambda *a,**k: subprocess.CompletedProcess(a[0],1,'secret-output','secret-error'))
    with pytest.raises(RuntimeError,match='ToolHive MCP operation failed') as e:
        ToolHiveMCPClient('/thv','safe-server').discover()
    assert 'secret' not in str(e.value)


def test_generic_mcp_client_schema_change_invalidates_old_tool(monkeypatch):
    import subprocess,json,pytest
    from ai_foundation.toolhive import ToolHiveMCPClient
    inventories=[[{'name':'old','inputSchema':{'type':'object'}}],[{'name':'new','inputSchema':{'type':'object'}}]]
    calls=[]
    def fake(argv,**kwargs):
        calls.append(argv)
        if argv[2]=='list':
            tools=inventories.pop(0) if inventories else [{'name':'new','inputSchema':{'type':'object'}}]
            return subprocess.CompletedProcess(argv,0,json.dumps({'tools':tools}),'')
        return subprocess.CompletedProcess(argv,0,json.dumps({'content':[]}),'')
    monkeypatch.setattr(subprocess,'run',fake)
    c=ToolHiveMCPClient('/thv','safe-server')
    assert set(c.discover())=={'old'}
    with pytest.raises(ValueError,match='unknown MCP tool'):
        c.call('old',{})
    assert not any(a[2]=='call' for a in calls)

def test_generic_mcp_clients_same_tool_name_remain_server_bound(monkeypatch):
    import subprocess,json
    from ai_foundation.toolhive import ToolHiveMCPClient
    calls=[]
    def fake(argv,**kwargs):
        calls.append(argv)
        server=argv[argv.index('--server')+1]
        if argv[2]=='list': return subprocess.CompletedProcess(argv,0,json.dumps({'tools':[{'name':'echo'}]}),'')
        return subprocess.CompletedProcess(argv,0,json.dumps({'content':[{'type':'text','text':server}]}),'')
    monkeypatch.setattr(subprocess,'run',fake)
    a=ToolHiveMCPClient('/thv','server-a'); b=ToolHiveMCPClient('/thv','server-b')
    assert a.call('echo',{})['content'][0]['text']=='server-a'
    assert b.call('echo',{})['content'][0]['text']=='server-b'
    assert [x[x.index('--server')+1] for x in calls if x[2]=='call']==['server-a','server-b']

def test_generic_mcp_concurrent_calls_keep_bound_server(monkeypatch):
    import subprocess,json,threading,time
    from ai_foundation.toolhive import ToolHiveMCPClient
    lock=threading.Lock(); calls=[]
    def fake(argv,**kwargs):
        time.sleep(.01)
        with lock: calls.append(tuple(argv))
        if argv[2]=='list': return subprocess.CompletedProcess(argv,0,json.dumps({'tools':[{'name':'echo'}]}),'')
        return subprocess.CompletedProcess(argv,0,json.dumps({'content':[{'type':'text','text':'ok'}]}),'')
    monkeypatch.setattr(subprocess,'run',fake)
    c=ToolHiveMCPClient('/thv','safe-server'); out=[]
    ts=[threading.Thread(target=lambda i=i: out.append(c.call('echo',{'i':i}))) for i in range(8)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert len(out)==8 and len(calls)==16
    assert all(a[a.index('--server')+1]=='safe-server' for a in calls)


def test_bound_generic_mcp_scope_exposes_only_host_allowed_tools(monkeypatch):
 import subprocess,json
 from ai_foundation.toolhive import ToolHiveMCPClient,BoundMCPTools
 calls=[]
 def fake_run(argv,**kw):
  calls.append(argv)
  if argv[2]=='list': return subprocess.CompletedProcess(argv,0,json.dumps({'tools':[{'name':'safe'},{'name':'admin'}]}),'')
  return subprocess.CompletedProcess(argv,0,json.dumps({'content':[{'type':'text','text':'SAFE_OK'}]}),'')
 monkeypatch.setattr(subprocess,'run',fake_run)
 bound=BoundMCPTools(ToolHiveMCPClient('/thv','server-a'),{'safe'})
 assert set(bound.inventory())=={'safe'}
 assert bound.call('safe',{})['content'][0]['text']=='SAFE_OK'
 with pytest.raises(PermissionError): bound.call('admin',{})
 assert all('--server' in x and x[x.index('--server')+1]=='server-a' for x in calls)

def test_bound_generic_mcp_removed_tool_loses_authority(monkeypatch):
 import subprocess,json
 from ai_foundation.toolhive import ToolHiveMCPClient,BoundMCPTools
 inventories=iter([{'tools':[{'name':'safe'}]},{'tools':[]}])
 def fake_run(argv,**kw):
  if argv[2]=='list': return subprocess.CompletedProcess(argv,0,json.dumps(next(inventories)),'')
  raise AssertionError('removed tool must not dispatch')
 monkeypatch.setattr(subprocess,'run',fake_run)
 bound=BoundMCPTools(ToolHiveMCPClient('/thv','server-a'),{'safe'})
 assert 'safe' in bound.inventory()
 with pytest.raises(ValueError,match='unknown MCP tool'): bound.call('safe',{})


def test_filesystem_port_retries_once_after_running_workload_refresh(tmp_path,monkeypatch):
 from types import SimpleNamespace
 p=ToolHiveFilesystemPort('/thv','srv',tmp_path);target=tmp_path/'x';target.write_text('x')
 calls=[]
 def run(argv,**kw):
  calls.append(tuple(argv))
  if argv[1]=='status':
   assert argv==['/thv','status','srv','--format','json']
   return SimpleNamespace(returncode=0,stdout='{"name":"srv","status":"running"}',stderr='')
  n=sum(1 for x in calls if len(x)>1 and x[1]=='mcp')
  return SimpleNamespace(returncode=1 if n==1 else 0,stdout='{"content":[{"type":"text","text":"ok"}]}',stderr='')
 monkeypatch.setattr('ai_foundation.toolhive.subprocess.run',run)
 assert p.observe(TaskPlan('r','read',str(target)))=='ok'
 assert sum(1 for x in calls if len(x)>1 and x[1]=='mcp')==2



def test_toolhive_mcp_cli_nonzero_never_retries_possible_written_effect(tmp_path):
    import subprocess
    import pytest
    from ai_foundation.core import TaskPlan
    from ai_foundation.toolhive import ToolHiveFilesystemPort

    class LostReply(ToolHiveFilesystemPort):
        def __init__(self):
            super().__init__('/abs/toolhive/thv', 'files-server', tmp_path)
            self.calls = 0
        def _invoke(self, tool, args):
            self.calls += 1
            assert tool == 'write_file'
            assert args['content'] == 'only-once'
            return subprocess.CompletedProcess([], 1, '', 'SECRET_PRIVATE_ERROR')
        def _wait_running(self, timeout=10.0):
            raise AssertionError('no restart or redispatch before Guard reconcile')
    port = LostReply()
    plan = TaskPlan('synthetic', 'write', str(tmp_path/'one.txt'),
                    text='only-once', canon_revision='c1')
    with pytest.raises(RuntimeError, match='ToolHive MCP call failed') as error:
        port.execute(plan)
    assert port.calls == 1
    assert 'SECRET_PRIVATE' not in str(error.value)

@pytest.mark.parametrize('receipt', [
    {'isError': True, 'content': [{'type': 'text', 'text': 'error'}]},
    {'isError': 'false', 'content': [{'type': 'text', 'text': 'wrong'}]},
    {'content': []},
    {'content': [{'type': 'image', 'data': 'unexpected'}]},
    {'content': [{'type': 'text', 'text': 123}]},
    ['not-a-receipt'],
])
def test_toolhive_read_rejects_untrusted_mcp_receipts(tmp_path, receipt):
    target = tmp_path / 'read.txt'
    target.write_text('existing')
    port = ToolHiveFilesystemPort('/thv', 'server', tmp_path)
    port._call = lambda tool, args: receipt
    with pytest.raises(RuntimeError, match='ToolHive (file read failed|returned invalid file read)'):
        port.observe(TaskPlan('read-receipt', 'read', str(target)))


def test_toolhive_read_accepts_valid_text_receipt(tmp_path):
    target = tmp_path / 'read.txt'
    target.write_text('existing')
    port = ToolHiveFilesystemPort('/thv', 'server', tmp_path)
    port._call = lambda tool, args: {'content': [{'type': 'text', 'text': 'ok'}]}
    assert port.observe(TaskPlan('read-receipt', 'read', str(target))) == 'ok'


def test_owner_toolhive_running_status_uses_bound_json_not_display_text(tmp_path):
    import json
    from types import SimpleNamespace
    from unittest.mock import patch
    from ai_foundation.toolhive import ToolHiveFilesystemPort
    port=ToolHiveFilesystemPort("/fake/thv","ai-foundation-fs",tmp_path)
    valid=json.dumps({"name":"ai-foundation-fs","status":"running",
                      "url":"PRIVATE_LOCATION"})
    with patch("ai_foundation.toolhive.subprocess.run",
               return_value=SimpleNamespace(returncode=0,stdout=valid,stderr="PRIVATE")) as call:
        assert port._wait_running(timeout=.5) is True
        assert call.call_args.args[0]==[
            "/fake/thv","status","ai-foundation-fs","--format","json"]
    for rc,body in (
        (0,json.dumps({"name":"ai-foundation-fs","status":"stopped"})),
        (0,json.dumps({"name":"other-server","status":"running"})),
        (0,"Status: running"),
        (0,json.dumps({"name":"ai-foundation-fs","status":"unhealthy"})),
        (0,"X"*8193),
        (1,valid),
    ):
        with patch("ai_foundation.toolhive.subprocess.run",
                   return_value=SimpleNamespace(returncode=rc,stdout=body,stderr="PRIVATE")):
            assert port._wait_running(timeout=.025) is False
