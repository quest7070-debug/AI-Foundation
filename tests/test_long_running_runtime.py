from ai_foundation import long_running_runtime as m
class Secrets:
 def available(self,b):return True
 def load(self,b):return 'ey.native'
class Client:pass
class Worker:
 def start(self):pass

def test_runtime_composes_one_client_two_durable_stores_and_worker(tmp_path,monkeypatch):
 client=Client();seen={}
 monkeypatch.setattr(m,'build_client',lambda c:client)
 monkeypatch.setattr(m,'build_worker',lambda h,handler:(seen.update(handler=handler) or Worker()))
 rt=m.build_long_running_runtime(tmp_path,object(),Secrets(),env={})
 assert rt.client is client and rt.producer.work_service.port.client is client
 assert rt.authority_store.path==tmp_path/'long-running-authority.sqlite'
 assert rt.run_store.path==tmp_path/'hatchet-runs.sqlite'
 assert seen['handler'].executor.authority_store is rt.authority_store
