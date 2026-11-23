import json,stat
from ai_foundation.webpush_transport import SubscriptionStore,WebPushConfig,WebPushTransport,PushDependencyUnavailable
import pytest
def test_subscription_store_is_atomic_private_and_validates(tmp_path):
 p=tmp_path/'subs.json';s=SubscriptionStore(p)
 with pytest.raises(ValueError):s.put({'endpoint':'http://bad','keys':{}})
 s.put({'endpoint':'https://push.example/x','keys':{'p256dh':'p','auth':'a'}})
 assert list(s.load())==['https://push.example/x'];assert stat.S_IMODE(p.stat().st_mode)==0o600
def test_delivery_removes_only_expired_and_does_not_persist_payload(tmp_path,monkeypatch):
 p=tmp_path/'subs.json';s=SubscriptionStore(p)
 for x in ('gone','ok','temporary'):s.put({'endpoint':f'https://push.example/{x}','keys':{'p256dh':'p','auth':'a'}})
 t=WebPushTransport(WebPushConfig('private','public','mailto:x@example.invalid',p))
 class Resp:status_code=410
 class Gone(Exception):response=Resp()
 def send(sub,payload):
  if sub['endpoint'].endswith('/gone'):raise Gone()
  if sub['endpoint'].endswith('/temporary'):raise RuntimeError('network secret detail')
 monkeypatch.setattr(t,'send',send);r=t.deliver({'title':'safe','body':'safe'})
 assert r=={'sent':1,'expired':1,'subscriptions':3}
 assert set(s.load())=={'https://push.example/ok','https://push.example/temporary'}
 assert 'safe' not in p.read_text()

def test_missing_delivery_dependency_is_not_reported_as_zero_success(tmp_path,monkeypatch):
 p=tmp_path/'subs.json';s=SubscriptionStore(p);s.put({'endpoint':'https://push.example/x','keys':{'p256dh':'p','auth':'a'}})
 t=WebPushTransport(WebPushConfig('private','public','mailto:x@example.invalid',p))
 monkeypatch.setattr(t,'send',lambda *_:(_ for _ in ()).throw(PushDependencyUnavailable('missing')))
 with pytest.raises(PushDependencyUnavailable):t.deliver({'title':'x'})

def test_corrupt_store_fails_closed(tmp_path):
 from ai_foundation.webpush_transport import SubscriptionStoreCorrupt
 p=tmp_path/'subs.json';p.write_text('{broken')
 try:SubscriptionStore(p).load()
 except SubscriptionStoreCorrupt:pass
 else:assert False,'corruption must not become empty subscriptions'

def test_store_file_is_0600_and_roundtrip(tmp_path):
 p=tmp_path/'subs.json';s=SubscriptionStore(p);s.put({'endpoint':'https://push.example/a','keys':{'p256dh':'p','auth':'a'}})
 assert (p.stat().st_mode & 0o777)==0o600 and len(s.load())==1
