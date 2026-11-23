"""External Hatchet client/worker bootstrap. Secrets enter only through environment/config."""
from __future__ import annotations
import os
from dataclasses import dataclass

@dataclass(frozen=True)
class ExternalHatchetConfig:
 token:str
 host_port:str='127.0.0.1:17070'
 server_url:str='http://127.0.0.1:18888'
 tls_strategy:str='none'

 @classmethod
 def from_native_store(cls,store,binding='hatchet-client',env=None):
  e=os.environ if env is None else env
  if not store.available(binding): raise RuntimeError('external Hatchet client token not configured')
  token=store.load(binding)
  if not token: raise RuntimeError('external Hatchet client token not configured')
  return cls(
   token,
   (e.get('HATCHET_CLIENT_HOST_PORT') or '127.0.0.1:17070').strip(),
   (e.get('HATCHET_CLIENT_SERVER_URL') or 'http://127.0.0.1:18888').strip(),
   (e.get('HATCHET_CLIENT_TLS_STRATEGY') or 'none').strip(),
  )

 @classmethod
 def from_env(cls,env=None):
  e=os.environ if env is None else env
  token=(e.get('HATCHET_CLIENT_TOKEN') or '').strip()
  if not token: raise RuntimeError('external Hatchet client token not configured')
  return cls(
   token,
   (e.get('HATCHET_CLIENT_HOST_PORT') or '127.0.0.1:17070').strip(),
   (e.get('HATCHET_CLIENT_SERVER_URL') or 'http://127.0.0.1:18888').strip(),
   (e.get('HATCHET_CLIENT_TLS_STRATEGY') or 'none').strip(),
  )

def build_client(config,hatchet_cls=None):
 if hatchet_cls is None:
  from hatchet_sdk import Hatchet as hatchet_cls
 from hatchet_sdk.config import ClientConfig,ClientTLSConfig
 cc=ClientConfig(
  token=config.token,
  host_port=config.host_port,
  server_url=config.server_url,
  tls_config=ClientTLSConfig(strategy=config.tls_strategy),
 )
 return hatchet_cls(config=cc)
