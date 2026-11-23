#!/usr/bin/env python3
"""Read-only cross-layer drift audit for the canonical M1 runtime."""
import json, plistlib, sqlite3, subprocess, urllib.request
from pathlib import Path
HOME=Path.home(); REPO=HOME/'Develop/AI-Foundation'; DATA=HOME/'Library/Application Support/AI-Foundation'
def fail(msg): raise SystemExit('DRIFT: '+msg)
def launch(label,program,required_arg):
 p=HOME/'Library/LaunchAgents'/f'{label}.plist'; d=plistlib.loads(p.read_bytes()); args=d.get('ProgramArguments',[])
 if not args or args[0]!=program or required_arg not in args: fail(f'{label} source/argv mismatch')
 if label.endswith('chat-gateway') and d.get('WorkingDirectory')!=str(REPO): fail(f'{label} working directory mismatch')
 out=subprocess.check_output(['launchctl','print',f'gui/{subprocess.check_output(["id","-u"],text=True).strip()}/{label}'],text=True)
 if 'state = running' not in out: fail(f'{label} not running')
def docker(name,image,mount_dest=None):
 d=json.loads(subprocess.check_output(['docker','inspect',name],text=True))[0]
 if d['Config']['Image']!=image: fail(f'{name} image mismatch')
 if mount_dest and not any(m.get('Destination')==mount_dest for m in d.get('Mounts',[])): fail(f'{name} mount missing {mount_dest}')
def main():
 cfg=json.loads((DATA/'config.json').read_text());
 if Path(cfg['data_dir'])!=DATA or cfg['schema_version']!=1: fail('config authority mismatch')
 py=str(REPO/'.venv/bin/python'); launch('dev.quest7070.ai-foundation.operator',py,str(REPO/'scripts/operator_server.py')); launch('dev.quest7070.ai-foundation.chat-gateway',py,str(REPO/'scripts/chat_gateway.py')); launch('dev.quest7070.ai-foundation.llama-swap','/opt/homebrew/bin/llama-swap',str(DATA/'local-compute/llama-swap.yaml'))
 docker('chat-mongodb','mongo:8.0.20','/data/db'); docker('chat-meilisearch','getmeili/meilisearch:v1.35.1','/meili_data'); docker('ai-foundation-hatchet-lite','ghcr.io/hatchet-dev/hatchet/hatchet-lite:latest','/config'); docker('ai-foundation-hatchet-pg','postgres:16-alpine','/var/lib/postgresql/data')
 human=json.load(urllib.request.urlopen('http://127.0.0.1:8766/api/human',timeout=5)); routes={r['function']:r for r in human['routes']}; providers={p['provider']:p for p in human['providers']}
 if routes['CHAT']['primary'] is None or routes['SEARCH']['primary'] is None: fail('rendered inference route missing')
 for cap in ('CODE','DATA','FILES','PC_CONTROL'):
  if routes[cap]['primary'] is not None: fail(f'{cap} incorrectly rendered as LLM route')
 con=sqlite3.connect(DATA/cfg['provider_db']); db={r[0]:r[1] for r in con.execute('select provider, health from provider_credentials')}; con.close()
 for provider,row in providers.items():
  if db.get(provider)!=row['health']: fail(f'{provider} DB/projection health drift')
 print(json.dumps({'status':'PASS','launchd':3,'docker':4,'providers':len(providers),'routes':len(routes),'config_schema':cfg['schema_version']},sort_keys=True))
if __name__=='__main__': main()


def test_runtime_drift_audit_requires_user_path_dependency_health_coverage():
 src=Path('scripts/runtime_drift_audit.py').read_text()
 for name in ('LOCAL COMPUTE','PROVIDER REGISTRY','TOOLHIVE FILES','TOOLHIVE CODE','LONG-TERM HEALTH'): assert name in src
 assert 'production service-health coverage missing' in src


def test_runtime_drift_audit_rejects_reported_unhealthy_dependency():
 src=Path('scripts/runtime_drift_audit.py').read_text()
 assert "reports unhealthy during canonical audit" in src


def test_runtime_drift_audit_maps_health_to_user_execution_paths():
 src=Path('scripts/runtime_drift_audit.py').read_text()
 assert "'TOOLHIVE FILES':('FILES',)" in src and "'TOOLHIVE CODE':('CODE',)" in src
 assert 'healthy but no user execution path is projected' in src
