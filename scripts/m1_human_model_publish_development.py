"""Publish two supplied project instructions and prepare one real owner binding.

No Raw import, learned personality, model installation, cloud call, service
restart, Operator release replacement or Native dispatch. Public output is
aggregate only; all source data and receipts stay on the external volume.
"""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import sqlite3
import subprocess
import sys
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
sys.path.insert(0, str(ROOT/'experiments/human_model'))
from development_sources import publish, source_rows, VIEW, SCOPE
from human_model_ledger import Ledger
from storage_location import validate_external_root, validated_ledger_path
from cognee_bridge import CogneeSearch, child_directory
from m1_human_model_activation_readiness import existing_ledger_roots, inspect_installed_runtime
from ai_foundation.human_model_context import HumanModelBinding, HumanModelContext, _source_reader, build_human_model_context
from ai_foundation.core import GuardState
from ai_foundation.guard import GuardCore


def atomic_create_json(path, value):
    """Create exclusively on external filesystems without hard-link support.

    Readback is required before claiming readiness. An interrupted invalid JSON
    file fails closed; existing configurations are never silently replaced.
    """
    if path.is_symlink(): raise PermissionError('symlinked host configuration')
    if path.exists():
        if json.loads(path.read_text()) != value: raise ValueError('host configuration differs')
        return False
    descriptor = os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(value, stream, ensure_ascii=False); stream.flush(); os.fsync(stream.fileno())
    if json.loads(path.read_text()) != value: raise ValueError('configuration readback failed')
    return True


def existing_owner_id():
    docker = shutil.which('docker') or next((p for p in (
        '/usr/local/bin/docker', '/opt/homebrew/bin/docker') if Path(p).is_file()), None)
    if not docker: raise RuntimeError('DOCKER_UNAVAILABLE')
    code = "const a=db.users.find({},{_id:1}).limit(2).toArray();print(JSON.stringify({count:a.length,owner:a.length===1?String(a[0]._id):null}));"
    cp = subprocess.run([docker,'exec','chat-mongodb','mongosh','--quiet','LibreChat','--eval',code],
                        capture_output=True,text=True,timeout=15,check=True)
    lines = [s for s in cp.stdout.splitlines() if s.startswith('{')]
    if len(lines) != 1: raise ValueError('server owner response')
    row = json.loads(lines[0]); owner = row.get('owner')
    if row.get('count') != 1 or not isinstance(owner,str) or not re.fullmatch('[0-9a-fA-F]{24}',owner):
        raise RuntimeError('SERVER_OWNER_NOT_UNIQUE')
    return owner


def existing_binding_path(home=None):
    home = Path.home() if home is None else Path(home)
    plist = home/'Library/LaunchAgents/dev.quest7070.ai-foundation.operator.plist'
    agent = plistlib.loads(plist.read_bytes()); args = agent['ProgramArguments']
    if args.count('--config') != 1: raise ValueError('explicit Operator configuration required')
    working = Path(agent.get('WorkingDirectory','/')).resolve(strict=True)
    config_path = Path(args[args.index('--config')+1])
    if not config_path.is_absolute(): config_path = working/config_path
    config = json.loads(config_path.read_text())
    data = Path(config['data_dir']).expanduser()
    if not data.is_absolute(): data = working/data
    # Owner binding is host configuration in the already established Operator
    # state directory. Only originals/graphs/logs must be on HumanModel's USB
    # volume. Honor the canonical state's existing location and symlink layout.
    data = data.resolve(strict=True)
    if not data.is_dir() or data in (Path('/'),home.resolve()):
        raise ValueError('existing scoped Operator state required')
    # Stage the binding. Promoting it into the active filename belongs to the
    # reviewed runtime integration, including a valid local-only output route.
    return data/'human-model-bindings.prepared.json'


def installed_index_model():
    """Use the single owner-pinned local 9B; never select 2B/4B or start it blindly."""
    from ai_foundation.shared_ollama9b_adapter import SharedOllama9BDiscovery, MODEL
    rows = SharedOllama9BDiscovery()()
    if (len(rows) != 1
            or rows[0].binding != 'local:ollama-shared9b:general'
            or rows[0].model != MODEL
            or rows[0].health != 'ONLINE'):
        raise RuntimeError('EXISTING_PINNED_9B_UNAVAILABLE')
    return MODEL


def main():
    report = {'status':'BLOCKED','phase':'preflight','new_model_downloads':0,
              'paid_api_calls':0,'raw_imports':0,'native_dispatches':0,
              'service_restarts':0,'private_content_logged':False}
    try:
        if sys.platform != 'darwin': raise RuntimeError('M1_REQUIRED')
        os.umask(0o077)
        roots = existing_ledger_roots()
        if len(roots) != 1: raise RuntimeError('EXTERNAL_ROOT_NOT_UNIQUE')
        root = roots[0]
        report['phase'] = 'existing_server_owner'; owner = existing_owner_id()
        report['phase'] = 'existing_operator_state'; binding_path = existing_binding_path()
        report['binding_config_uses_existing_operator_state'] = True
        binding = {'owner_id':owner,'root':str(root),'view_id':VIEW,
                   'scopes':[SCOPE],'max_privacy':'private'}
        config = {'version':1,'bindings':[binding]}
        if binding_path.exists() and json.loads(binding_path.read_text()) != config:
            raise ValueError('existing owner binding requires reconciliation')
        ledger_path = validated_ledger_path(root)
        if not ledger_path.is_file(): raise RuntimeError('EXISTING_LEDGER_REQUIRED')
        backups = child_directory(root,'backups')
        backup = backups/'before-development-source-publication-20261103.sqlite3'
        if backup.is_symlink(): raise PermissionError('symlinked ledger backup')
        if not backup.exists():
            with sqlite3.connect(ledger_path.as_uri()+'?mode=ro',uri=True) as origin:
                with sqlite3.connect(backup) as destination: origin.backup(destination)
        report['phase'] = 'publish_explicit_project_sources'
        ledger = Ledger(ledger_path)
        try: report.update(publish(ledger))
        finally: ledger.close()
        context = HumanModelContext(HumanModelBinding(**{**binding,'scopes':(SCOPE,)}),
                    _source_reader(ROOT),guard=GuardCore(GuardState()),run_id='development-source-readback')
        snapshot = json.loads(context.read(owner,SCOPE))
        expected = {r['source_revision'] for r in source_rows()}
        if snapshot.get('status') != 'AVAILABLE' or {r['source_revision'] for r in snapshot['records']} != expected:
            raise RuntimeError('SOURCE_READBACK_FAILED')
        report['owner_bound_original_readback'] = True
        report['phase'] = 'existing_model_derived_index'
        model = installed_index_model()
        # This prepares the optional project index only; no general inference
        # model or Operator route is changed by this setting.
        source = {k:v for k,v in snapshot.items() if k not in ('source','status','execution_authority')}
        source['_privacy_ceiling'] = 'private'
        found = CogneeSearch(root,model,ROOT)(source,'人間モデル')
        if not found['records'] or any(r not in snapshot['records'] for r in found['records']):
            raise RuntimeError('COGNEE_ORIGINAL_READBACK_FAILED')
        tools = child_directory(root,'tools'); install = child_directory(tools,'cognee-1.6.5')
        atomic_create_json(install/'enabled.json',{'version':1,'enabled':True,'model':model})
        report['cognee_project_index_model'] = model
        parent = root/'indexes/cognee'
        # Counts only, from the exact snapshot/model workspace just read back.
        from cognee_memory import ADAPTER_REVISION, VERSION, digest
        key = digest({'snapshot':digest(source),'engine':VERSION,
                      'adapter_revision':ADAPTER_REVISION,'model':model})
        pointer = json.loads((parent/key/'workspace.json').read_text())['workspace']
        receipt = json.loads((parent/pointer/'receipt.json').read_text())
        report['rejected_interpretation_records'] = receipt['rejected_interpretation_records']
        report['grounded_interpretations'] = receipt['interpretation_count']
        report['cognee_source_search_verified'] = True
        report['phase'] = 'prepare_host_binding'
        atomic_create_json(binding_path,config)
        rebound = build_human_model_context(binding_path,owner,repository_root=ROOT,
                         guard=GuardCore(GuardState()),run_id='prepared-owner-binding-readback')
        result = json.loads(rebound.search(owner,SCOPE,'人間モデル'))
        if result.get('status') != 'AVAILABLE' or not rebound.local_required:
            raise RuntimeError('BOUND_CURRENT_SOURCE_SEARCH_FAILED')
        report['host_binding_prepared'] = True
        report['active_binding_changed'] = False
        report['promotion_requires_local_output_route'] = True
        report['private_turn_requires_local'] = True
        report['runtime'] = inspect_installed_runtime()
        report['canonical_runtime_activated'] = False
        report.update(status='SOURCE_AND_BINDING_PREPARED',phase='complete')
        receipts = child_directory(root,'publication')
        atomic_create_json(receipts/'development-instructions-source-manifest-v1.json',{
            'origin':'explicit user messages supplied in the development conversation',
            'conversation_id':None,'source_event_times_known':False,
            'source_uris':[r['source_uri'] for r in source_rows()],
            'source_hashes':sorted(expected),'view_id':VIEW,'scope':SCOPE,
            'personal_traits_inferred':False})
        print(json.dumps(report,sort_keys=True)); return 0
    except Exception as exc:
        report['error_type'] = type(exc).__name__
        if isinstance(exc,RuntimeError) and re.fullmatch('[A-Z_]{1,80}',str(exc)):
            report['reason_code'] = str(exc)
        if hasattr(exc,'worker_error_type'): report['worker_error_type'] = exc.worker_error_type
        print(json.dumps(report,sort_keys=True)); return 2


if __name__ == '__main__': raise SystemExit(main())
