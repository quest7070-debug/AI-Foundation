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
def docker(name,image,mount_dest=None,image_id=None):
 d=json.loads(subprocess.check_output(['docker','inspect',name],text=True))[0]
 if d['Config']['Image']!=image: fail(f'{name} image mismatch')
 if image_id and d.get('Image')!=image_id: fail(f'{name} immutable image mismatch')
 if mount_dest and not any(m.get('Destination')==mount_dest for m in d.get('Mounts',[])): fail(f'{name} mount missing {mount_dest}')
def main():
 cfg=json.loads((DATA/'config.json').read_text());
 if Path(cfg['data_dir'])!=DATA or cfg['schema_version']!=1: fail('config authority mismatch')
 py=str(REPO/'.venv/bin/python'); launch('dev.quest7070.ai-foundation.operator',py,str(REPO/'scripts/operator_server.py')); launch('dev.quest7070.ai-foundation.chat-gateway',py,str(REPO/'scripts/chat_gateway.py')); launch('dev.quest7070.ai-foundation.llama-swap','/opt/homebrew/bin/llama-swap',str(DATA/'local-compute/llama-swap.yaml'))
 docker('chat-mongodb','mongo:8.0.20','/data/db'); docker('chat-meilisearch','getmeili/meilisearch:v1.35.1','/meili_data'); manifest=json.loads((REPO/'ops/runtime/external-owner-images.json').read_text())['images']; docker('ai-foundation-hatchet-lite','ghcr.io/hatchet-dev/hatchet/hatchet-lite:latest','/config',manifest['ai-foundation-hatchet-lite']['image_id']); docker('ai-foundation-hatchet-pg','postgres:16-alpine','/var/lib/postgresql/data',manifest['ai-foundation-hatchet-pg']['image_id'])
 human=json.load(urllib.request.urlopen('http://127.0.0.1:8766/api/human',timeout=5)); routes={r['function']:r for r in human['routes']}; providers={p['provider']:p for p in human['providers']}; services={x['name']:x for x in human.get('services',[])}
 expected_services={'LOCAL COMPUTE','PROVIDER REGISTRY','TOOLHIVE FILES','TOOLHIVE CODE','LONG-TERM HEALTH'}
 if not expected_services.issubset(services): fail('production service-health coverage missing: '+','.join(sorted(expected_services-set(services))))
 for name in expected_services:
  if not services[name].get('ok'): fail(f'{name} reports unhealthy during canonical audit')
 # Health labels must map to a user-reachable execution path, not merely a live process.
 paths={'LOCAL COMPUTE':('CHAT','SEARCH'),'PROVIDER REGISTRY':('CHAT','SEARCH'),'TOOLHIVE FILES':('FILES',),'TOOLHIVE CODE':('CODE',)}
 for name,caps in paths.items():
  if not any(cap in routes for cap in caps): fail(f'{name} healthy but no user execution path is projected')
 if routes['CHAT']['primary'] is None or routes['SEARCH']['primary'] is None: fail('rendered inference route missing')
 for cap in ('CODE','DATA','FILES','PC_CONTROL'):
  if routes[cap]['primary'] is not None: fail(f'{cap} incorrectly rendered as LLM route')
 con=sqlite3.connect(DATA/cfg['provider_db']); db={r[0]:r[1] for r in con.execute('select provider, health from provider_credentials')}; con.close()
 for provider,row in providers.items():
  if db.get(provider)!=row['health']: fail(f'{provider} DB/projection health drift')
 print(json.dumps({'status':'PASS','launchd':3,'docker':4,'providers':len(providers),'routes':len(routes),'config_schema':cfg['schema_version'],'services':len(services)},sort_keys=True))
if __name__=='__main__': main()
