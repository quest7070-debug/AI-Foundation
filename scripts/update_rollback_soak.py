#!/usr/bin/env python3
"""Disposable multi-generation update/rollback/recovery soak; never touches canonical runtime."""
import json,tempfile,shutil
from pathlib import Path
from ai_foundation.migration import apply_update_transaction,inspect_interrupted_update,recover_interrupted_update
from ai_foundation.productization import FoundationConfig,sha256,backup

def pkg(root,n):
 p=root/f'pkg-{n}';p.mkdir();(p/'payload.txt').write_text(f'v{n}');(p/'update-manifest.json').write_text(json.dumps({'schema_version':1,'files':{'payload.txt':sha256(p/'payload.txt')}}));return p
def main():
 with tempfile.TemporaryDirectory(prefix='foundation-update-soak-') as td:
  root=Path(td);live=root/'live';live.mkdir();(live/'trace.jsonl').write_text('v0');c=FoundationConfig(str(live.resolve()));e=[]
  for n in range(1,7):
   p=pkg(root,n);b=root/f'backup-{n}';before=(live/'trace.jsonl').read_text()
   def apply(_p,n=n):(live/'trace.jsonl').write_text(f'v{n}')
   if n%2:
    r=apply_update_transaction(c,p,b,apply,lambda n=n:(live/'trace.jsonl').read_text()==f'v{n}',root/f'rollback-{n}');assert r.status=='VERIFIED';state='verified'
   else:
    try:apply_update_transaction(c,p,b,apply,lambda:False,root/f'rollback-{n}')
    except RuntimeError:pass
    assert (live/'trace.jsonl').read_text()==before;state='rolled-back'
   # Process-restart equivalent: reconstruct config and independently read authoritative tree/journal state.
   c=FoundationConfig(str(live.resolve()));c.validate();assert live.exists() and not (root/'.live.failed-update').exists();e.append(state)
  # interrupted generation: process dies after live quarantine; independent recovery restores LKG and preserves forensics.
  b=root/'backup-interrupted';backup(c,b);q=root/'.live.failed-update';live.replace(q);assert inspect_interrupted_update(c,b).status=='RECOVERY_REQUIRED';recover_interrupted_update(c,b,root/'.recovery-stage');assert live.exists() and q.exists()
  # no stale preview/source tree or listener/launch-agent is created by this data transaction soak.
  assert not list(root.glob('*.staging-*')) and not list(root.glob('.recovery-stage'))
  print(json.dumps({'status':'PASS','generations':6,'states':e,'interrupted_recovery':'PASS','canonical_runtime_touched':False},separators=(',',':')))
if __name__=='__main__':main()
