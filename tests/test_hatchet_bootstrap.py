import pytest
from ai_foundation.hatchet_bootstrap import ExternalHatchetConfig

def test_external_hatchet_config_fails_closed_without_token():
 with pytest.raises(RuntimeError):ExternalHatchetConfig.from_env({})
def test_external_hatchet_config_has_loopback_defaults_and_explicit_override():
 c=ExternalHatchetConfig.from_env({'HATCHET_CLIENT_TOKEN':'ey.fake'})
 assert c.host_port=='127.0.0.1:17070' and c.server_url=='http://127.0.0.1:18888' and c.tls_strategy=='none'
 c=ExternalHatchetConfig.from_env({'HATCHET_CLIENT_TOKEN':'ey.fake','HATCHET_CLIENT_HOST_PORT':'x:1','HATCHET_CLIENT_SERVER_URL':'http://x'})
 assert (c.host_port,c.server_url)==('x:1','http://x')

class Store:
 def __init__(self,value=None):self.value=value
 def available(self,b):return self.value is not None
 def load(self,b):return self.value
def test_external_hatchet_config_loads_secret_from_native_store_without_env_secret():
 c=ExternalHatchetConfig.from_native_store(Store('ey.native'),env={})
 assert c.token=='ey.native' and c.host_port=='127.0.0.1:17070'
 with pytest.raises(RuntimeError):ExternalHatchetConfig.from_native_store(Store(),env={})


def test_external_hatchet_tls_strategy_is_explicit_and_overrideable():
 import base64
 import json
 from ai_foundation.hatchet_bootstrap import build_client

 def encode(value):
  return base64.urlsafe_b64encode(
   json.dumps(value,separators=(',',':')).encode()
  ).decode().rstrip('=')

 token='.'.join((
  encode({'alg':'none','typ':'JWT'}),
  encode({
   'sub':'00000000-0000-0000-0000-000000000001',
   'server_url':'http://127.0.0.1:18888',
   'grpc_broadcast_address':'127.0.0.1:17070',
  }),
  encode({'synthetic':'test'}),
 ))

 c=ExternalHatchetConfig.from_env({
  'HATCHET_CLIENT_TOKEN':token,
  'HATCHET_CLIENT_TLS_STRATEGY':'tls',
 })
 assert c.tls_strategy=='tls'

 class FakeHatchet:
  def __init__(self,config):self.config=config

 local=build_client(
  ExternalHatchetConfig.from_env({'HATCHET_CLIENT_TOKEN':token}),
  FakeHatchet,
 )
 assert local.config.tls_config.strategy=='none'

 remote=build_client(c,FakeHatchet)
 assert remote.config.tls_config.strategy=='tls'
