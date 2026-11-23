#!/usr/bin/env python3
"""Safe live-provider readiness check. Never reads or prints raw secrets."""
import argparse,json,sqlite3,sys
from pathlib import Path

def main():
 p=argparse.ArgumentParser(); p.add_argument('--registry',required=True); a=p.parse_args(); db=Path(a.registry)
 if not db.exists(): print(json.dumps({'ready':False,'reason':'registry_not_found'})); return 2
 with sqlite3.connect(db) as c:
  rows=c.execute('SELECT binding,provider,tier,health FROM provider_credentials ORDER BY provider,tier,binding').fetchall()
 from ai_foundation.native_credentials import MacOSNativeCredentialStore
 store=MacOSNativeCredentialStore()
 out=[]
 for binding,provider,tier,health in rows:
  out.append({'provider':provider,'tier':tier,'health':health,'credential_present':store.available(binding)})
 print(json.dumps({'ready':any(x['credential_present'] for x in out),'providers':out},ensure_ascii=False))
 return 0
if __name__=='__main__': sys.exit(main())
