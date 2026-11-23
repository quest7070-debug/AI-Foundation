#!/usr/bin/env python3
"""Materialize one Keychain secret into a mode-0400 runtime file; never stdout/argv."""
from __future__ import annotations
import argparse,os
from pathlib import Path
from ai_foundation.native_credentials import MacOSNativeCredentialStore

def materialize(binding:str,target:str)->Path:
 if not binding: raise ValueError('binding required')
 secret=MacOSNativeCredentialStore().load(binding)
 if not secret: raise RuntimeError('empty secret')
 path=Path(target).expanduser()
 path.parent.mkdir(parents=True,exist_ok=True)
 tmp=path.with_name(path.name+'.tmp')
 fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o400)
 try:
  os.write(fd,secret.encode())
  os.fsync(fd)
 finally: os.close(fd)
 os.chmod(tmp,0o400);os.replace(tmp,path)
 return path

if __name__=='__main__':
 p=argparse.ArgumentParser()
 p.add_argument('--binding',default='foundation:attachment-handoff')
 p.add_argument('--target',required=True)
 a=p.parse_args();materialize(a.binding,a.target)
