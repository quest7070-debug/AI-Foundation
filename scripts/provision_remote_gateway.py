#!/usr/bin/env python3
"""Provision Foundation remote-gateway secrets without exposing them on argv/stdout."""
from __future__ import annotations
import secrets
from ai_foundation.native_credentials import MacOSNativeCredentialStore
SESSION='remote:gateway:session-secret'
def provision(store=None):
 s=store or MacOSNativeCredentialStore()
 created=[]
 if not s.available(SESSION):s.save(SESSION,secrets.token_urlsafe(48));created.append(SESSION)
 return tuple(created)
if __name__=='__main__':
 c=provision();print('PROVISIONED' if c else 'ALREADY_PRESENT')
