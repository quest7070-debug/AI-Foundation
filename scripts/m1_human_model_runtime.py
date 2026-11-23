"""Inspect the live daily Operator independently of the Native release on 8768."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import html
import shutil
import sqlite3
import time
from urllib.error import HTTPError
from urllib.request import Request
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
PHASE='inspect'
ROLLBACK_VERIFIED=False


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def listeners(port):
    cp = subprocess.run(['/usr/sbin/lsof','-nP','-t',f'-iTCP:{port}','-sTCP:LISTEN'],
                        capture_output=True,text=True,timeout=10)
    return sorted({int(s) for s in cp.stdout.splitlines() if s.isdigit()})


def service_pid(label):
    cp = subprocess.run(['/bin/launchctl','print',f'gui/{os.getuid()}/{label}'],
                        capture_output=True,text=True,timeout=10)
    if cp.returncode: return None
    found = re.search(r'^\s*pid = (\d+)\s*$',cp.stdout,re.M)
    return int(found.group(1)) if found else None


def daily_host(home=None):
    home = Path.home() if home is None else Path(home)
    path = home/'Library/LaunchAgents/dev.quest7070.ai-foundation.operator.plist'
    if path.is_symlink(): raise PermissionError('symlinked daily LaunchAgent')
    definition = plistlib.loads(path.read_bytes()); args = definition['ProgramArguments']
    label = definition['Label']
    if label != 'dev.quest7070.ai-foundation.operator': raise ValueError('daily label required')
    scripts = [Path(a) for a in args if isinstance(a,str) and a.endswith((
        '/scripts/operator_server.py','/scripts/human_model_operator_launcher.py'))]
    if len(scripts) != 1 or not scripts[0].is_file(): raise ValueError('daily source required')
    port = int(args[args.index('--port')+1]) if '--port' in args else 8766
    if port != 8766: raise ValueError('daily port must be 8766')
    working = Path(definition.get('WorkingDirectory','/')).resolve(strict=True)
    config_path = Path(args[args.index('--config')+1])
    if not config_path.is_absolute(): config_path = working/config_path
    data = Path(json.loads(config_path.read_text())['data_dir']).expanduser()
    if not data.is_absolute(): data = working/data
    data = data.resolve(strict=True)
    if not data.is_dir(): raise ValueError('existing daily state required')
    pid = service_pid(label)
    if pid is None or listeners(8766) != [pid]: raise RuntimeError('DAILY_LIVE_OWNERSHIP_UNVERIFIED')
    return {'path':path,'definition':definition,'args':args,'script':scripts[0],
            'source':scripts[0].parent.parent,'data':data,'pid':pid}


def inspect():
    host = daily_host(); source = host['source']; text = host['script'].read_text()
    legacy_source=source
    if host['script'].name=='human_model_operator_launcher.py':
        manifest=json.loads((source/'runtime.json').read_text())
        legacy_script=Path(manifest['legacy_script'])
        if sha(legacy_script)!=manifest['legacy_script_sha256']:raise RuntimeError('LEGACY_SOURCE_CHANGED')
        legacy_source=legacy_script.parent.parent
        source_ast=ast.parse(legacy_script.read_text())
    else:source_ast = ast.parse(text)
    factories = [n for n in ast.walk(source_ast) if isinstance(n,ast.FunctionDef) and n.name=='auto_agent_factory']
    auto = legacy_source/'src/ai_foundation/auto_agent.py'
    payload = {'status':'LIVE_DAILY_OPERATOR_IDENTIFIED','daily_live_owned':True,
        'daily_port':8766,'native_port':8768,'native_listener_count':len(listeners(8768)),
        'source_sha256':sha(host['script']),'launchagent_sha256':sha(host['path']),
        'context_code_present':(source/'src/ai_foundation/human_model_context.py').is_file(),
        'context_factory_present':('build_human_model_context' in text or 'install_legacy_agent_factory' in text),
        'native_work_producer_present':'work_producer' in auto.read_text(),
        'agent_factory_count':len(factories),
        'prepared_binding_present':(host['data']/'human-model-bindings.prepared.json').is_file(),
        'active_binding_present':(host['data']/'human-model-bindings.json').is_file(),
        'modifications':0,'model_calls':0,'native_dispatches':0}
    command=[host['args'][0],'-c',
        'import importlib.metadata as m,json,sys;print(json.dumps({"python":list(sys.version_info[:2]),"pydantic_ai":m.version("pydantic-ai-slim")}))']
    cp=subprocess.run(command,capture_output=True,text=True,timeout=15,check=True)
    payload['runtime_versions']=json.loads(cp.stdout)
    try:
        cp=subprocess.run(['/usr/bin/git','-C',str(legacy_source),'rev-parse','HEAD'],
                          capture_output=True,text=True,timeout=10,check=True)
        value=cp.stdout.strip()
        if re.fullmatch('[a-f0-9]{40}',value):payload['source_git_revision']=value
    except subprocess.CalledProcessError:pass
    print(json.dumps(payload,sort_keys=True))


RUNTIME_FILES=(
    'src/ai_foundation/human_model_context.py','src/ai_foundation/human_model_runtime.py',
    'src/ai_foundation/gateway_csrf.py','scripts/gateway_support.py',
    'src/ai_foundation/local_model_availability.py',
    'scripts/human_model_gateway_launcher.py',
    'scripts/human_model_operator_launcher.py','scripts/cognee_snapshot_worker.py',
    *('experiments/human_model/'+s+'.py' for s in (
        'foundation_readonly','human_model_ledger','storage_location','cognee_bridge',
        'cognee_memory','cognee_software_runtime')),
)
EXPECTED_DAILY_SCRIPT='6d943d423b8c40f9430b22e95aa63c492287c8e676eacfe404f02655af83994d'
EXPECTED_AGENT='e19d4621b8c928c2ca4d2a2b7eba42b7efa45519082924016ce6ec67fc5efcf8'


def get_json(port,path):
    with urlopen(f'http://127.0.0.1:{port}{path}',timeout=15) as response:
        return json.loads(response.read(2*1024*1024))


def gateway_host():
    path=Path.home()/'Library/LaunchAgents/dev.quest7070.ai-foundation.chat-gateway.plist'
    if path.is_symlink():raise PermissionError('symlinked gateway definition')
    definition=plistlib.loads(path.read_bytes());args=definition['ProgramArguments']
    label=definition['Label'];pid=service_pid(label)
    scripts=[Path(a) for a in args if isinstance(a,str) and a.endswith('/chat_gateway.py')]
    port=int(args[args.index('--port')+1]) if '--port' in args else 8767
    upstream=int(args[args.index('--upstream')+1]) if '--upstream' in args else 8766
    if label!='dev.quest7070.ai-foundation.chat-gateway' or port!=8767 or upstream!=8766:
        raise RuntimeError('GATEWAY_CONFIGURATION_CHANGED')
    if len(scripts)!=1 or sha(scripts[0])!='39963690c50896f8f02193306ad33d1daebc3b321f9c50aa6458b6f34e12371c':
        raise RuntimeError('GATEWAY_SOURCE_CHANGED')
    if pid is None or listeners(8767)!=[pid]:raise RuntimeError('GATEWAY_OWNERSHIP_UNVERIFIED')
    return {'path':path,'definition':definition,'args':args,'script':scripts[0],'pid':pid}


def stage():
    global PHASE
    PHASE='stage_preflight'
    from m1_human_model_activation_readiness import existing_ledger_roots
    from m1_human_model_publish_development import atomic_create_json,existing_owner_id
    sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'experiments/human_model'))
    import project_reference_sources as project
    from human_model_ledger import Ledger
    from storage_location import validated_ledger_path
    from cognee_bridge import child_directory
    from ai_foundation.human_model_context import build_human_model_context
    from ai_foundation.guard import GuardCore
    from ai_foundation.core import GuardState
    host=daily_host();gateway=gateway_host()
    if sha(host['script'])!=EXPECTED_DAILY_SCRIPT or sha(host['path'])!=EXPECTED_AGENT:
        raise RuntimeError('DAILY_BASELINE_CHANGED')
    surface=get_json(8766,'/api/human')
    if surface.get('activity'):raise RuntimeError('DAILY_OPERATOR_BUSY')
    native=listeners(8768)
    roots=existing_ledger_roots()
    if len(roots)!=1:raise RuntimeError('EXTERNAL_LEDGER_NOT_UNIQUE')
    data_root=roots[0];ledger_path=validated_ledger_path(data_root)
    backup=child_directory(data_root,'backups')/'before-project-reference-20261103.sqlite3'
    if backup.is_symlink():raise PermissionError('symlinked source backup')
    if not backup.exists():
        with sqlite3.connect(ledger_path.as_uri()+'?mode=ro',uri=True) as origin:
            with sqlite3.connect(backup) as destination:origin.backup(destination)
    ledger=Ledger(ledger_path)
    try:published=project.publish(ledger,ROOT)
    finally:ledger.close()
    PHASE='project_source_index'
    print(json.dumps({'checkpoint':'project_documents_published','project_documents':2,
                      'private_originals_reclassified':0}),flush=True)
    owner=existing_owner_id()
    config={'version':1,'bindings':[{'owner_id':owner,'root':str(data_root),
            'view_id':project.VIEW,'scopes':[project.SCOPE],'max_privacy':'shareable'}]}
    prepared=host['data']/'human-model-bindings.project-reference.prepared.json'
    active=host['data']/'human-model-bindings.json'
    if active.exists():raise RuntimeError('ACTIVE_BINDING_ALREADY_EXISTS')
    atomic_create_json(prepared,config)
    context=build_human_model_context(prepared,owner,repository_root=ROOT,
                    guard=GuardCore(GuardState()),run_id='project-index-staging')
    found=json.loads(context.search(owner,project.SCOPE,'HumanModel'))
    if found.get('status')!='AVAILABLE' or context.local_required:
        raise RuntimeError('PROJECT_CONTEXT_INDEX_UNAVAILABLE')
    if any(r['privacy']!='shareable' for r in found['records']):
        raise RuntimeError('PRIVATE_SOURCE_IN_PROJECT_VIEW')
    PHASE='stage_additive_runtime'
    files={p:sha(ROOT/p) for p in RUNTIME_FILES}
    identity=hashlib.sha256(json.dumps({'files':files,'legacy':EXPECTED_DAILY_SCRIPT},sort_keys=True).encode()).hexdigest()
    parent=Path.home()/'Library/Application Support/HumanModel/runtimes'
    if str(parent.resolve()).startswith('/Volumes/'):raise RuntimeError('INTERNAL_SOFTWARE_REQUIRED')
    root=child_directory(parent,'daily-context-'+identity[:20])
    for relative,pin in files.items():
        path=root/relative;path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        if path.is_symlink():raise PermissionError('symlinked runtime source')
        if path.exists() and sha(path)!=pin:raise RuntimeError('RUNTIME_SOURCE_CONFLICT')
        if not path.exists():shutil.copyfile(ROOT/relative,path)
    legacy_files={str(p.relative_to(host['source'])):sha(p)
                  for p in (host['source']/'src/ai_foundation').rglob('*.py')}
    audit_dir=child_directory(child_directory(data_root,'evaluation'),'daily-runtime')
    manifest={'legacy_script':str(host['script']),'legacy_script_sha256':EXPECTED_DAILY_SCRIPT,
        'files':files,'legacy_files':legacy_files,'prepared_binding':str(prepared),
        'active_binding':str(active),'audit_path':str(audit_dir/'context-audit.jsonl'),
        'source_ids':published['source_ids'],'project_scope':project.SCOPE,
        'gateway':{'script':str(gateway['script']),'script_sha256':sha(gateway['script']),
                   'plist':str(gateway['path']),'plist_sha256':sha(gateway['path']),
                   'label':gateway['definition']['Label']}}
    atomic_create_json(root/'runtime.json',manifest)
    original=host['path'].read_bytes();saved=root/'previous-launchagent.plist'
    if saved.exists() and saved.read_bytes()!=original:raise RuntimeError('DAILY_BACKUP_CONFLICT')
    if not saved.exists():saved.write_bytes(original)
    definition=dict(host['definition']);args=list(host['args'])
    args[args.index(str(host['script']))]=str(root/'scripts/human_model_operator_launcher.py')
    definition['ProgramArguments']=args
    environment=dict(definition.get('EnvironmentVariables',{}))
    environment['PYTHONDONTWRITEBYTECODE']='1'
    definition['EnvironmentVariables']=environment
    candidate=root/'candidate-launchagent.plist';candidate.write_bytes(plistlib.dumps(definition))
    gateway_original=gateway['path'].read_bytes()
    previous_gateway=root/'previous-gateway-launchagent.plist'
    if previous_gateway.exists() and previous_gateway.read_bytes()!=gateway_original:
        raise RuntimeError('GATEWAY_BACKUP_CONFLICT')
    if not previous_gateway.exists():previous_gateway.write_bytes(gateway_original)
    gateway_definition=dict(gateway['definition']);gateway_args=list(gateway['args'])
    gateway_args[gateway_args.index(str(gateway['script']))]=str(root/'scripts/human_model_gateway_launcher.py')
    gateway_definition['ProgramArguments']=gateway_args
    gateway_definition['EnvironmentVariables']={**gateway_definition.get('EnvironmentVariables',{}),'PYTHONDONTWRITEBYTECODE':'1'}
    (root/'candidate-gateway-launchagent.plist').write_bytes(plistlib.dumps(gateway_definition))
    private_log=root/'self-check-private.log'
    PHASE='legacy_agent_self_check'
    with private_log.open('a') as log:
        subprocess.run([args[0],'-B',str(root/'scripts/human_model_operator_launcher.py'),'--self-check'],
            check=True,capture_output=False,stdout=log,stderr=log,timeout=90,
            env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
    if listeners(8768)!=native or sha(host['path'])!=EXPECTED_AGENT or service_pid(host['definition']['Label'])!=host['pid']:
        raise RuntimeError('HOST_CHANGED_DURING_STAGE')
    if service_pid(gateway['definition']['Label'])!=gateway['pid'] or sha(gateway['path'])!=manifest['gateway']['plist_sha256']:
        raise RuntimeError('GATEWAY_CHANGED_DURING_STAGE')
    receipt={'status':'DAILY_CONTEXT_STAGED','project_documents':2,'private_originals_reclassified':0,
        'source_index_verified':True,'legacy_agent_self_check':True,
        'free_online_provider_groups':sum(p.get('tier')=='FREE' and p.get('health')=='ONLINE'
                                           for p in surface.get('providers',[])),
        'native_pid_unchanged':True,'services_restarted':0,'model_downloads':0}
    staged_path=root/'staged.json'
    if staged_path.exists():
        previous=json.loads(staged_path.read_text())
        stable=lambda value:{k:v for k,v in value.items() if k!='free_online_provider_groups'}
        if stable(previous)!=stable(receipt):raise RuntimeError('STAGED_RECEIPT_CONFLICT')
    else:atomic_create_json(staged_path,receipt)
    return root,host,manifest,native,receipt


def checked_launchctl(*args):
    cp=subprocess.run(['/bin/launchctl',*args],capture_output=True,text=True,timeout=25)
    if cp.returncode:
        if args[0]=='bootout':
            state=subprocess.run(['/bin/launchctl','print',args[1]],capture_output=True,text=True,timeout=10)
            if state.returncode:return
        raise RuntimeError('DAILY_LAUNCHD_REQUEST_FAILED')



def wait_stopped(label,port,seconds=15):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        cp=subprocess.run(['/bin/launchctl','print',f'gui/{os.getuid()}/{label}'],
                          capture_output=True,text=True,timeout=10)
        if cp.returncode and not listeners(port):return
        time.sleep(.25)
    raise RuntimeError('DAILY_SERVICE_UNLOAD_NOT_COMPLETE')


def wait_owned(label,seconds=45,port=8766):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        pid=service_pid(label)
        if pid is not None and listeners(port)==[pid]:
            try:
                if get_json(port,'/v1/models').get('data'):return pid
            except Exception:pass
        time.sleep(1)
    raise RuntimeError('DAILY_RESTART_NOT_READY')


def live_chat(manifest):
    from ai_foundation.native_credentials import MacOSNativeCredentialStore
    from ai_foundation.librechat_signing_contract import sign_serialized_body
    owner=json.loads(Path(manifest['prepared_binding']).read_text())['bindings'][0]['owner_id']
    audit=Path(manifest['audit_path']);offset=audit.stat().st_size if audit.exists() else 0
    gateway=Path.home()/'Library/LaunchAgents/dev.quest7070.ai-foundation.chat-gateway.plist'
    definition=plistlib.loads(gateway.read_bytes());args=definition['ProgramArguments']
    label=definition['Label'];pid=service_pid(label)
    upstream=int(args[args.index('--upstream')+1]) if '--upstream' in args else 8766
    port=int(args[args.index('--port')+1]) if '--port' in args else 8767
    if label!='dev.quest7070.ai-foundation.chat-gateway' or upstream!=8766 or port!=8767 or listeners(8767)!=[pid]:
        raise RuntimeError('SIGNED_CHAT_GATEWAY_OWNERSHIP_UNVERIFIED')
    binding=args[args.index('--attachment-binding')+1] if '--attachment-binding' in args else 'foundation:attachment-handoff'
    if binding!='foundation:attachment-handoff':raise RuntimeError('UNEXPECTED_CHAT_SIGNER_BINDING')
    payload={'model':'foundation-auto','stream':False,'messages':[{'role':'user','content':
        'human_model_search または human_model_context を使って ai-foundation-project の原典を参照してください。'
        'このプロジェクトでは判断やパーソナライズをどこから参照し、9Bの追加導入は必要としていますか。根拠のevidence IDを挙げて短く回答してください。'}]}
    serialized=json.dumps(payload,ensure_ascii=False).encode()
    secret=MacOSNativeCredentialStore().load(binding)
    timestamp=int(time.time())
    signature=sign_serialized_body(secret,owner,serialized,timestamp=timestamp)
    del secret
    request=Request('http://127.0.0.1:8767/v1/chat/completions',data=serialized,
        headers={'Content-Type':'application/json','X-Foundation-Owner':owner,
                 'X-Foundation-Capability':'CHAT','X-Foundation-Attachments':'[]',
                 'X-Foundation-Attachment-Timestamp':str(timestamp),
                 'X-Foundation-Attachment-Signature':signature})
    with urlopen(request,timeout=240) as response:result=json.loads(response.read(2*1024*1024))
    answer=result['choices'][0]['message'].get('content','')
    with audit.open('rb') as stream:
        stream.seek(offset);events=[json.loads(s) for s in stream.read().splitlines() if s]
    owner_hash=hashlib.sha256(owner.encode()).hexdigest();expected=set(manifest['source_ids'])
    verified=[e for e in events if e.get('owner_hash')==owner_hash and e.get('status')=='AVAILABLE'
        and e.get('scope')==manifest['project_scope'] and e.get('evidence_ids')
        and set(e['evidence_ids'])<=expected]
    cited=sum(i in answer for i in expected)
    if not answer.strip() or not verified or cited<1:
        raise RuntimeError('LIVE_CHAT_DID_NOT_CITE_PROJECT_SOURCE')
    proof={'status':'LIVE_DAILY_CONTEXT_VERIFIED','project_documents':2,
           'owner_bound_source_calls':len(verified),'evidence_ids_cited':cited,
           'tools_used':sorted({e['tool'] for e in verified}),'private_originals_shared':0,
           'signed_chat_gateway_verified':True,'chat_gateway_pid_unchanged_during_request':service_pid(label)==pid,
           'general_model_route_changed':False,'new_model_downloads':0,'native_dispatches':0}
    # Response stays private; only structural proof is returned to Actions.
    (audit.parent/'live-chat-response-private.json').write_text(json.dumps(result,ensure_ascii=False))
    return proof


def activate():
    global PHASE,ROLLBACK_VERIFIED
    from m1_human_model_publish_development import atomic_create_json
    root,host,manifest,native,receipt=stage();label=host['definition']['Label']
    if get_json(8766,'/api/human').get('activity'):raise RuntimeError('DAILY_OPERATOR_BUSY')
    if sha(host['path'])!=EXPECTED_AGENT or listeners(8768)!=native:raise RuntimeError('CUTOVER_BASELINE_CHANGED')
    config=json.loads(Path(manifest['prepared_binding']).read_text())
    active=Path(manifest['active_binding'])
    original=host['path'].read_bytes();changed=False;binding_created=False;gateway_changed=False
    gateway=manifest.get('gateway')
    if gateway and sha(gateway['plist'])!=gateway['plist_sha256']:
        raise RuntimeError('GATEWAY_BASELINE_CHANGED')
    try:
        PHASE='daily_owned_cutover'
        changed=True
        checked_launchctl('bootout',f'gui/{os.getuid()}/{label}')
        wait_stopped(label,8766)
        deadline=time.monotonic()+10
        while listeners(8766) and time.monotonic()<deadline:time.sleep(.25)
        if listeners(8766):raise RuntimeError('DAILY_PORT_NOT_RELEASED')
        binding_created=atomic_create_json(active,config)
        temporary=host['path'].with_suffix('.human-model-new.plist')
        temporary.write_bytes((root/'candidate-launchagent.plist').read_bytes())
        os.replace(temporary,host['path'])
        checked_launchctl('bootstrap',f'gui/{os.getuid()}',str(host['path']))
        pid=wait_owned(label)
        if gateway:
            PHASE='daily_gateway_cutover'
            gateway_changed=True
            checked_launchctl('bootout',f"gui/{os.getuid()}/{gateway['label']}")
            wait_stopped(gateway['label'],8767)
            deadline=time.monotonic()+10
            while listeners(8767) and time.monotonic()<deadline:time.sleep(.25)
            if listeners(8767):raise RuntimeError('GATEWAY_PORT_NOT_RELEASED')
            gateway_path=Path(gateway['plist']);temporary=gateway_path.with_suffix('.human-model-new.plist')
            temporary.write_bytes((root/'candidate-gateway-launchagent.plist').read_bytes())
            os.replace(temporary,gateway_path)
            checked_launchctl('bootstrap',f'gui/{os.getuid()}',str(gateway_path))
            wait_owned(gateway['label'],port=8767)
            from gateway_support import current_csrf
            token=current_csrf(8766);del token
        PHASE='live_owner_chat'
        proof=live_chat(manifest)
        proof['gateway_restart_verified']=gateway_changed
        if listeners(8768)!=native:raise RuntimeError('NATIVE_PID_CHANGED')
        proof.update(daily_restart_verified=True,native_pid_unchanged=True)
        (root/'active-proof.json').write_text(json.dumps(proof,sort_keys=True))
        print(json.dumps(proof,sort_keys=True))
    except Exception as original_error:
        print(json.dumps({'status':'LIVE_CHAT_FAILURE_BEFORE_ROLLBACK',
            'error_type':type(original_error).__name__,
            'http_status':original_error.code if isinstance(original_error,HTTPError) else None,
            'reason_code':str(original_error) if re.fullmatch('[A-Z_]{1,80}',str(original_error)) else None,
            'phase':PHASE}),flush=True)
        if gateway_changed:
            if service_pid(gateway['label']) is not None:
                checked_launchctl('bootout',f"gui/{os.getuid()}/{gateway['label']}")
            wait_stopped(gateway['label'],8767)
            Path(gateway['plist']).write_bytes((root/'previous-gateway-launchagent.plist').read_bytes())
            checked_launchctl('bootstrap',f'gui/{os.getuid()}',gateway['plist'])
        if changed:
            if service_pid(label) is not None:
                checked_launchctl('bootout',f'gui/{os.getuid()}/{label}')
            wait_stopped(label,8766)
            host['path'].write_bytes(original)
            if binding_created and active.is_file() and json.loads(active.read_text())==config:active.unlink()
            checked_launchctl('bootstrap',f'gui/{os.getuid()}',str(host['path']))
            wait_owned(label)
            if listeners(8768)!=native:raise RuntimeError('ROLLBACK_NATIVE_STATE_CHANGED')
            if gateway_changed:wait_owned(gateway['label'],port=8767)
            ROLLBACK_VERIFIED=True
        raise




def verify_active():
    """Read back exact deployed software, binding, originals and prior live receipt."""
    global PHASE
    PHASE='verify_active_runtime'
    host=daily_host();root=host['source']
    if host['script'].name!='human_model_operator_launcher.py':
        raise RuntimeError('CONTEXT_RUNTIME_NOT_ACTIVE')
    manifest=json.loads((root/'runtime.json').read_text())
    if host['path'].read_bytes()!=(root/'candidate-launchagent.plist').read_bytes():
        raise RuntimeError('ACTIVE_DAILY_DEFINITION_CHANGED')
    for relative,pin in manifest['files'].items():
        if sha(root/relative)!=pin or sha(ROOT/relative)!=pin:
            raise RuntimeError('DEPLOYED_SOURCE_REVISION_MISMATCH')
    legacy=Path(manifest['legacy_script']).parent.parent
    for relative,pin in manifest['legacy_files'].items():
        if sha(legacy/relative)!=pin:raise RuntimeError('LEGACY_SOURCE_CHANGED')
    gateway=manifest['gateway'];gateway_path=Path(gateway['plist'])
    if gateway_path.read_bytes()!=(root/'candidate-gateway-launchagent.plist').read_bytes():
        raise RuntimeError('ACTIVE_GATEWAY_DEFINITION_CHANGED')
    gateway_pid=service_pid(gateway['label'])
    if gateway_pid is None or listeners(8767)!=[gateway_pid]:
        raise RuntimeError('ACTIVE_GATEWAY_OWNERSHIP_UNVERIFIED')
    prepared=json.loads(Path(manifest['prepared_binding']).read_text())
    active=json.loads(Path(manifest['active_binding']).read_text())
    if active!=prepared:raise RuntimeError('ACTIVE_BINDING_CHANGED')
    from m1_human_model_publish_development import existing_owner_id
    from ai_foundation.human_model_context import load_bindings,_source_reader
    owner=existing_owner_id();binding=load_bindings(manifest['active_binding']).get(owner)
    if (binding is None or binding.max_privacy!='shareable'
            or binding.scopes!=(manifest['project_scope'],)):
        raise RuntimeError('ACTIVE_OWNER_OR_SCOPE_MISMATCH')
    snapshot=_source_reader(ROOT)(binding.root,view_id=binding.view_id,
                                  scope=manifest['project_scope'],max_privacy='shareable')
    if (set(row['id'] for row in snapshot['records'])!=set(manifest['source_ids'])
            or any(row['privacy']!='shareable' for row in snapshot['records'])):
        raise RuntimeError('ACTIVE_SOURCE_READBACK_MISMATCH')
    proof=json.loads((root/'active-proof.json').read_text())
    if (proof.get('status')!='LIVE_DAILY_CONTEXT_VERIFIED'
            or proof.get('evidence_ids_cited',0)<1
            or not proof.get('signed_chat_gateway_verified')
            or proof.get('private_originals_shared')!=0):
        raise RuntimeError('LIVE_SOURCE_RECEIPT_MISSING')
    from gateway_support import current_csrf
    token=current_csrf(8766);del token
    print(json.dumps({'status':'LIVE_DAILY_CONTEXT_READBACK_VERIFIED',
        'project_documents':len(snapshot['records']),'owner_binding_matches':True,
        'deployed_source_matches_checkout':True,'source_snapshot_verified':True,
        'prior_live_evidence_ids_cited':proof['evidence_ids_cited'],
        'daily_owned':True,'gateway_owned':True,'private_originals_shared':0,
        'model_calls':0,'new_model_downloads':0,'native_dispatches':0},sort_keys=True))


def recover():
    """Restore only exact backed-up daily definitions; no inference or Native operations."""
    global PHASE,ROLLBACK_VERIFIED
    PHASE='recover_daily_services'
    native=listeners(8768)
    home=Path.home();base=home/'Library/Application Support/HumanModel/runtimes'
    paths={
        'operator':home/'Library/LaunchAgents/dev.quest7070.ai-foundation.operator.plist',
        'gateway':home/'Library/LaunchAgents/dev.quest7070.ai-foundation.chat-gateway.plist'}
    current={k:p.read_bytes() for k,p in paths.items()}
    matches=[]
    if base.is_dir():
        for root in base.iterdir():
            if root.is_symlink() or not root.is_dir():continue
            candidate=root/'candidate-launchagent.plist'
            if candidate.is_file() and candidate.read_bytes()==current['operator']:
                matches.append(root)
    if not matches and hashlib.sha256(current['operator']).hexdigest()==EXPECTED_AGENT:
        # The failed rollback may already have restored the plist before launchd
        # rejected bootstrap. Equivalent pinned backups are interchangeable.
        candidates=[]
        for root in base.iterdir():
            if root.is_symlink() or not root.is_dir():continue
            try:
                item=json.loads((root/'runtime.json').read_text())
                old=(root/'previous-gateway-launchagent.plist').read_bytes()
                candidate=(root/'candidate-gateway-launchagent.plist').read_bytes()
                daily=(root/'previous-launchagent.plist').read_bytes()
            except (OSError,ValueError):continue
            if (daily==current['operator'] and current['gateway'] in (old,candidate)
                    and hashlib.sha256(old).hexdigest()==item.get('gateway',{}).get('plist_sha256')):
                candidates.append(root)
        if candidates:
            backups={(p/'previous-gateway-launchagent.plist').read_bytes() for p in candidates}
            if len(backups)==1:matches=[max(candidates,key=lambda p:(p/'runtime.json').stat().st_mtime_ns)]
    if len(matches)!=1:
        print(json.dumps({'status':'RECOVERY_DEFINITION_INSPECTED',
                          'daily_is_original':hashlib.sha256(current['operator']).hexdigest()==EXPECTED_AGENT,
                          'matching_candidates':len(matches)}),flush=True)
        raise RuntimeError('RECOVERY_CANDIDATE_NOT_UNIQUE')
    root=matches[0];manifest=json.loads((root/'runtime.json').read_text())
    old_daily=(root/'previous-launchagent.plist').read_bytes()
    old_gateway=(root/'previous-gateway-launchagent.plist').read_bytes()
    if hashlib.sha256(old_daily).hexdigest()!=EXPECTED_AGENT:
        raise RuntimeError('RECOVERY_DAILY_BACKUP_CHANGED')
    gateway=manifest.get('gateway',{})
    if (gateway.get('plist')!=str(paths['gateway'])
            or hashlib.sha256(old_gateway).hexdigest()!=gateway.get('plist_sha256')):
        raise RuntimeError('RECOVERY_GATEWAY_BACKUP_CHANGED')
    candidate_gateway=(root/'candidate-gateway-launchagent.plist').read_bytes()
    if current['gateway'] not in (old_gateway,candidate_gateway):
        raise RuntimeError('RECOVERY_GATEWAY_BASELINE_CHANGED')
    for relative,pin in manifest['files'].items():
        if sha(root/relative)!=pin:raise RuntimeError('RECOVERY_RUNTIME_CHANGED')
    definitions={'operator':old_daily,'gateway':old_gateway}
    labels={'operator':'dev.quest7070.ai-foundation.operator',
            'gateway':'dev.quest7070.ai-foundation.chat-gateway'}
    ports={'operator':8766,'gateway':8767}
    active=Path(manifest['active_binding'])
    prepared=json.loads(Path(manifest['prepared_binding']).read_text())
    if active.exists() and json.loads(active.read_text())!=prepared:
        raise RuntimeError('RECOVERY_BINDING_CHANGED')
    state=[]
    for key,label in labels.items():
        definition=plistlib.loads(definitions[key])
        if definition.get('Label')!=label:raise RuntimeError('RECOVERY_LABEL_CHANGED')
        pid=service_pid(label);owners=listeners(ports[key])
        if owners and owners!=[pid]:raise RuntimeError('RECOVERY_PORT_OWNERSHIP_UNVERIFIED')
        cp=subprocess.run(['/bin/launchctl','print',f'gui/{os.getuid()}/{label}'],
                          capture_output=True,text=True,timeout=10)
        state.append({'service':key,'registered':cp.returncode==0,'listener_count':len(owners)})
    print(json.dumps({'status':'DAILY_RECOVERY_INSPECTED','services':state,'native_dispatches':0}),flush=True)
    # Stop both exact daily labels before replacing definitions. A waiting/failed
    # launchd job may be registered without a PID, so registration is authoritative.
    for key,label in labels.items():
        target=f'gui/{os.getuid()}/{label}'
        cp=subprocess.run(['/bin/launchctl','print',target],capture_output=True,text=True,timeout=10)
        if cp.returncode==0:
            stopped=subprocess.run(['/bin/launchctl','bootout',target],capture_output=True,text=True,timeout=25)
            remaining=subprocess.run(['/bin/launchctl','print',target],capture_output=True,text=True,timeout=10)
            if stopped.returncode and remaining.returncode==0:
                print(json.dumps({'status':'RECOVERY_LAUNCHD_REJECTED','service':key,'action':'bootout',
                                  'exit_code':stopped.returncode}),flush=True)
                raise RuntimeError('RECOVERY_BOOTOUT_REJECTED')
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            registered=subprocess.run(['/bin/launchctl','print',target],capture_output=True,text=True,timeout=10)
            if registered.returncode and not listeners(ports[key]):break
            time.sleep(.25)
        else:raise RuntimeError('RECOVERY_SERVICE_NOT_RELEASED')
    for key,path in paths.items():
        temporary=path.with_suffix('.human-model-recovery.plist')
        temporary.write_bytes(definitions[key]);os.replace(temporary,path)
    if active.exists():active.unlink()
    for key,label in labels.items():
        cp=subprocess.run(['/bin/launchctl','bootstrap',f'gui/{os.getuid()}',str(paths[key])],
                          capture_output=True,text=True,timeout=25)
        if cp.returncode:
            print(json.dumps({'status':'RECOVERY_LAUNCHD_REJECTED','service':key,'action':'bootstrap',
                              'exit_code':cp.returncode}),flush=True)
            raise RuntimeError('RECOVERY_BOOTSTRAP_REJECTED')
        wait_owned(label,port=ports[key])
    if listeners(8768)!=native:raise RuntimeError('RECOVERY_NATIVE_STATE_CHANGED')
    if any(paths[k].read_bytes()!=definitions[k] for k in paths):
        raise RuntimeError('RECOVERY_DEFINITION_READBACK_FAILED')
    ROLLBACK_VERIFIED=True
    print(json.dumps({'status':'DAILY_AND_GATEWAY_RECOVERY_VERIFIED','active_binding_present':False,
                      'daily_owned':True,'gateway_owned':True,'native_pid_unchanged':True,
                      'model_calls':0,'native_dispatches':0}),flush=True)


def diagnose():
    host=daily_host();report={'status':'DAILY_CONTEXT_DIAGNOSTIC','modifications':0,
        'model_calls':0,'native_dispatches':0,'daily_owned':True,'native_listener_count':len(listeners(8768))}
    cfgpath=Path(host['args'][host['args'].index('--config')+1])
    if not cfgpath.is_absolute():cfgpath=Path(host['definition'].get('WorkingDirectory','/'))/cfgpath
    cfg=json.loads(cfgpath.read_text());trace=host['data']/cfg.get('trace_file','trace.jsonl')
    filesystem={}
    cwd=subprocess.run(['/usr/sbin/lsof','-a','-p',str(host['pid']),'-d','cwd','-Fn'],
                       capture_output=True,text=True,timeout=10)
    actual=[line[1:] for line in cwd.stdout.splitlines() if line.startswith('n')]
    expected=Path(host['definition'].get('WorkingDirectory','/')).resolve()
    filesystem['process_cwd_matches_launch_directory']=len(actual)==1 and Path(actual[0]).resolve()==expected
    filesystem['configured_data_absolute']=Path(cfg['data_dir']).expanduser().is_absolute()
    databases={}
    for key,default in (('provider_db','providers.sqlite'),('routing_db','routing.sqlite'),
                        ('guard_db','guard.db'),('work_db','work.db')):
        path=host['data']/cfg.get(key,default)
        info={'exists':path.is_file(),'parent_exists':path.parent.is_dir(),
              'parent_writable':os.access(path.parent,os.W_OK)}
        if path.is_file():
            try:
                with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=2) as db:
                    db.execute('SELECT COUNT(*) FROM sqlite_master').fetchone()
                    if key=='provider_db':
                        info['credential_records']=db.execute('SELECT COUNT(*) FROM provider_credentials').fetchone()[0]
                info['read_only_open']='OK'
            except sqlite3.Error as exc:
                info['read_only_open']=type(exc).__name__
                info['reason_category']=next((kind for kind in (
                    'unable to open database file','database is locked','disk I/O error',
                    'attempt to write a readonly database','no such table') if kind in str(exc)),'OTHER')
        databases[key]=info
    filesystem['databases']=databases
    report['filesystem']=filesystem
    rows=[];cutoff=time.time_ns()-30*60*10**9
    report['trace_exists']=trace.is_file()
    report['trace_bytes']=trace.stat().st_size if trace.is_file() else 0
    names={}
    if trace.is_file():
        with trace.open('rb') as stream:
            stream.seek(max(0,trace.stat().st_size-2*1024*1024));lines=stream.read().splitlines()
        for line in lines:
            try:row=json.loads(line)
            except (ValueError,UnicodeDecodeError):continue
            if row.get('started_ns',0)<cutoff:continue
            name=str(row.get('name',''))
            if re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',name):names[name]=names.get(name,0)+1
            attrs=row.get('attributes',{})
            allowed=('provider','phase','attempt','fallback_reason','has_text','tool_call_count','tool_count','tool_names','timeout','finish_reason')
            safe={k:attrs[k] for k in allowed if k in attrs}
            if 'fallback_reason' in safe and not re.fullmatch(r'[A-Za-z0-9_:./-]{1,150}',str(safe['fallback_reason'])):
                safe['fallback_reason']='REDACTED'
            rows.append({'name':row['name'],'status':row.get('status'),'attributes':safe,
                         'elapsed_ms':round((row['ended_ns']-row['started_ns'])/1e6,1)})
    report['agent_trace']=rows[-40:]
    report['trace_event_counts']=names
    errors=set();statuses=[]
    path=host['definition'].get('StandardErrorPath')
    if path and Path(path).is_file():
        with Path(path).open('rb') as stream:
            stream.seek(max(0,Path(path).stat().st_size-256000));tail=stream.read().decode(errors='replace')
        errors.update(re.findall(r'\b([A-Za-z][A-Za-z0-9_]*(?:Error|Exception)):',tail))
        report['recent_stack_frames']=[{'module':Path(file).name,'line':int(line),'function':function}
            for file,line,function in re.findall(r'File "([^"\n]+)", line (\d+), in ([A-Za-z0-9_<>]+)',tail)][-25:]
        report['sqlite_error_categories']={kind:tail.count(kind) for kind in (
            'database is locked','database table is locked','unable to open database file',
            'disk I/O error','attempt to write a readonly database','database disk image is malformed') if kind in tail}
        report['sqlite_missing_objects']=re.findall(r'(?:no such table|no such column): ([A-Za-z0-9_.]+)',tail)[-10:]
        statuses=re.findall(r'POST /v1/chat/completions HTTP/1\.1" (\d{3})',tail)[-10:]
    report['operator_exception_types']=sorted(errors);report['recent_chat_http_statuses']=statuses
    gateway=Path.home()/'Library/LaunchAgents/dev.quest7070.ai-foundation.chat-gateway.plist'
    definition=plistlib.loads(gateway.read_bytes());path=definition.get('StandardErrorPath')
    scripts=[Path(a) for a in definition['ProgramArguments'] if isinstance(a,str) and a.endswith('/chat_gateway.py')]
    if len(scripts)==1 and scripts[0].is_file():
        source=scripts[0].read_text()
        report['gateway_has_verification_audit']='foundation.trust' in source
        report['gateway_script_sha256']=sha(scripts[0])
    if path and Path(path).is_file():
        with Path(path).open('rb') as stream:
            stream.seek(max(0,Path(path).stat().st_size-32000));tail=stream.read().decode(errors='replace')
        report['gateway_trust_results']=re.findall(r'foundation\.trust (verified|absent|rejected:[a-z-]+)',tail)[-10:]
    from m1_human_model_activation_readiness import existing_ledger_roots
    roots=existing_ledger_roots()
    if len(roots)==1:
        audit=roots[0]/'evaluation/daily-runtime/context-audit.jsonl'
        if audit.is_file():
            fake=hashlib.sha256(b'staged-self-check').hexdigest()
            events=[json.loads(s) for s in audit.read_text().splitlines() if s]
            real=[e for e in events if e.get('run_hash')!=fake and e.get('at',0)>time.time()-1800]
            report['real_context_calls']=len(real)
            report['real_context_statuses']=[e.get('status') for e in real][-10:]

    progress=Path.home()/'Library/Application Support/HumanModel'
    from m1_human_model_activation_readiness import existing_ledger_roots
    progress_roots=existing_ledger_roots()
    if len(progress_roots)==1:
        progress=progress_roots[0]/'evaluation/daily-runtime/agent-progress.jsonl'
        if progress.is_file():
            fake=hashlib.sha256(b'staged-self-check').hexdigest()
            entries=[json.loads(line) for line in progress.read_text().splitlines() if line]
            entries=[entry for entry in entries if entry.get('at',0)>time.time()-1800 and entry.get('run_hash')!=fake]
            report['agent_progress_events']=[entry.get('event') for entry in entries][-20:]
            approved={'human_model_runtime.py','human_model_context.py','auto_agent.py','agent.py',
                'routed_agent_model.py','compute_routing.py','settings_service.py','provider_registry.py',
                'macos_keychain.py','native_credentials.py','cloud_execution.py','http_transport.py',
                'llama_swap_adapter.py','openai_local_adapter.py','cognee_bridge.py','cognee_software_runtime.py',
                'request.py','client.py','ssl.py','function.py'}
            frames=[frame for entry in entries if entry.get('event')=='pending_after_60s'
                    for thread in entry.get('frames',[]) for frame in thread if frame.get('module') in approved]
            unique={(frame['module'],frame['line'],frame['function']) for frame in frames}
            report['pending_agent_frames']=[{'module':module,'line':line,'function':function}
                                           for module,line,function in sorted(unique)]

    from gateway_support import current_csrf
    started=time.monotonic()
    try:
        token=current_csrf(8766)
        report['gateway_csrf_probe']={'status':'AVAILABLE','token_logged':False}
        del token
    except Exception as exc:
        report['gateway_csrf_probe']={'status':'UNAVAILABLE','error_type':type(exc).__name__}
    report['gateway_csrf_probe']['elapsed_ms']=round((time.monotonic()-started)*1000)
    if report['gateway_csrf_probe']['status']=='UNAVAILABLE' and service_pid(host['definition']['Label'])==host['pid']:
        sample=subprocess.run(['/usr/bin/sample',str(host['pid']),'1','1'],
                              capture_output=True,text=True,timeout=15)
        profile=sample.stdout+sample.stderr
        symbols=('SecKeychainFindGenericPassword','SecItemCopyMatching','SecKeychainItemCopyContent',
                 'CFMessagePortSendRequest','securityd','sqlite3_step','sqlite3_prepare','sqlite3_busy',
                 'sqlite3_open','sqlite3_close','fcntl','flock','SSL_read','SSL_connect','connect',
                 'pthread_mutex_lock','pthread_cond_wait','semaphore_wait_trap','mach_msg')
        report['owned_operator_sample']={'exit_code':sample.returncode,
            'known_wait_symbols':{name:profile.count(name) for name in symbols if name in profile},
            'raw_profile_logged':False}
    print(json.dumps(report,sort_keys=True))


if __name__=='__main__':
    parser=argparse.ArgumentParser();mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--inspect',action='store_true');mode.add_argument('--stage',action='store_true')
    mode.add_argument('--activate',action='store_true');mode.add_argument('--diagnose',action='store_true')
    mode.add_argument('--recover',action='store_true');mode.add_argument('--verify',action='store_true')
    args=parser.parse_args()
    os.umask(0o077)
    try:
        if args.inspect:inspect()
        elif args.stage:print(json.dumps(stage()[-1],sort_keys=True))
        elif args.diagnose:diagnose()
        elif args.recover:recover()
        elif args.verify:verify_active()
        else:activate()
    except Exception as exc:
        print(json.dumps({'status':'BLOCKED','error_type':type(exc).__name__,
            'reason_code':str(exc) if re.fullmatch('[A-Z_]{1,80}',str(exc)) else None,
            'phase':PHASE,'http_status':exc.code if isinstance(exc,HTTPError) else None,
            'source_or_candidate_writes_possible':args.stage or args.activate or args.recover,
            'activation_attempted':args.activate,'rollback_verified':ROLLBACK_VERIFIED,
            'native_dispatches':0}));raise SystemExit(2)
