#!/usr/bin/env python3
"""Disposable real llama-swap lifecycle E2E using cached production artifacts, never production config/process."""
import json,subprocess,tempfile,time,urllib.request,urllib.error,threading
from pathlib import Path
from ai_foundation.llama_swap_adapter import LlamaSwapDiscovery,LlamaSwapExecution
from ai_foundation.local_compute_registry import LocalComputeRegistry
from ai_foundation.compute_routing import ComputeRouter

PORT=19292
BASE=f'http://127.0.0.1:{PORT}'
def wait_models(want,timeout=15):
 end=time.time()+timeout
 while time.time()<end:
  try:
   with urllib.request.urlopen(BASE+'/v1/models',timeout=1) as r: ids={x['id'] for x in json.load(r)['data']}
   if want(ids): return ids
  except Exception: pass
  time.sleep(.2)
 raise RuntimeError('isolated llama-swap inventory did not converge')
def chat(alias): return LlamaSwapExecution(BASE,timeout=90).chat('Reply with exactly LIFECYCLE_OK',model=alias)
def manifest(alias,artifact,ttl=10):
 return f'''models:\n  {alias}:\n    cmd: >\n      /opt/homebrew/bin/llama-server\n      --offline\n      --model "{artifact}"\n      --no-mmproj\n      --host 127.0.0.1\n      --port ${{PORT}}\n      --ctx-size 1024\n      --parallel 1\n      --n-gpu-layers 999\n      --reasoning off\n    ttl: {ttl}\n    concurrencyLimit: 1\n'''
def main():
 prod=Path.home()/'Library/Application Support/AI-Foundation/local-compute/llama-swap.yaml'
 text=prod.read_text(); import re
 art=re.search(r'local-general:.*?--model\s+"([^"]+)"',text,re.S).group(1)
 with tempfile.TemporaryDirectory(prefix='foundation-local-lifecycle-') as td:
  td=Path(td);base=td/'base.yaml';add=td/'add';add.mkdir();base.write_text(manifest('local-general',art));extra=add/'specialist.yaml'
  cmd=['/opt/homebrew/bin/llama-swap','-config',str(base),'-config-dir',str(add),'-watch-config','-listen',f'127.0.0.1:{PORT}']
  log=open(td/'runtime.log','w');p=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT)
  try:
   assert wait_models(lambda x:x=={'local-general'})=={'local-general'}
   extra.write_text(manifest('local-code-agent',art));ids=wait_models(lambda x:{'local-general','local-code-agent'}<=x)
   discovery=LlamaSwapDiscovery(BASE,manifest_path=prod);rows={x.slot:x for x in discovery()};assert rows['local-code-agent'].capabilities==('CODE',)
   class Settings:
    def choose_route(self,*a,**k):return None
    def route_label(self,b):return b
   route=ComputeRouter(Settings(),LocalComputeRegistry(discovery)).choose('CODE',prefer_local=True);assert route.binding.endswith(':local-code-agent')
   result=chat('local-code-agent');assert 'LIFECYCLE_OK' in result
   # LLM13: mutate inventory while a real request is in flight. The selected alias is immutable for that effect;
   # removal is restart-authoritative, so the in-flight request must finish on the original alias, never rebind.
   box={}
   t=threading.Thread(target=lambda:box.update(result=chat('local-code-agent')),daemon=True);t.start();time.sleep(.05);extra.unlink();t.join(90)
   assert not t.is_alive() and 'LIFECYCLE_OK' in box.get('result','')
   # llama-swap merges watched additions; authoritative removal is restart-based.
   assert 'local-code-agent' in wait_models(lambda x:'local-code-agent' in x)
  finally:
   p.terminate();p.wait(timeout=10);log.close()
  log=open(td/'runtime2.log','w');p=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT)
  try:
   ids=wait_models(lambda x:x=={'local-general'});assert ids=={'local-general'}
   rows=LlamaSwapDiscovery(BASE,manifest_path=prod)();assert all(x.slot!='local-code-agent' for x in rows)
   try: chat('local-code-agent');raise AssertionError('removed alias executed')
   except urllib.error.HTTPError as e: assert e.code==404
   assert 'LIFECYCLE_OK' in chat('local-general')
  finally:p.terminate();p.wait(timeout=10);log.close()
 print(json.dumps({'status':'PASS','isolated':True,'add':'local-code-agent','role':'CODE','inference':True,'remove_requires_restart':True,'removed_alias_http':404,'unaffected_general':True,'inflight_inventory_mutation':'SAFE_ORIGINAL_BINDING'},separators=(',',':')))
if __name__=='__main__':main()
