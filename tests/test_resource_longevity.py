import gc,os,socket,threading,time,tracemalloc
from http.server import BaseHTTPRequestHandler
from ai_foundation.bounded_http import BoundedThreadingHTTPServer
from ai_foundation.execution_activity import ExecutionActivityRegistry
from ai_foundation.local_health import LocalFailureCooldown
from ai_foundation.provider_recovery import ProviderRecoveryLoop

def fd_count():return len(os.listdir('/dev/fd'))

def test_bounded_http_rejects_overload_without_allocating_unbounded_threads():
 gate=threading.Event();entered=threading.Event();count=[0];lock=threading.Lock()
 class H(BaseHTTPRequestHandler):
  def do_GET(self):
   with lock:
    count[0]+=1
    if count[0]==2:entered.set()
   gate.wait(10);self.send_response(200);self.end_headers()
  def log_message(self,*a):pass
 class S(BoundedThreadingHTTPServer):max_concurrent_requests=2;request_queue_size=2
 s=S(('127.0.0.1',0),H);t=threading.Thread(target=s.serve_forever,daemon=True);t.start()
 clients=[]
 try:
  # Fill both real worker slots before testing overload; do not depend on
  # accept scheduling or allow the handlers to finish during the burst.
  for _ in range(2):
   c=socket.create_connection(s.server_address,timeout=2);clients.append(c)
   c.sendall(b'GET / HTTP/1.0\r\n\r\n')
  assert entered.wait(2) and count[0]==2 and s._request_slots._value==0
  workers=set(threading.enumerate())
  rejected=0
  for _ in range(10):
   try:
    c=socket.create_connection(s.server_address,timeout=.3);clients.append(c)
    c.sendall(b'GET / HTTP/1.0\r\n\r\n')
    # Overload is a transport-level rejection, not an HTTP response.
    assert c.recv(1)==b''
    rejected+=1
   except (ConnectionResetError,BrokenPipeError,TimeoutError):
    rejected+=1
  assert rejected==10 and count[0]==2 and s._request_slots._value==0
  assert not [worker for worker in threading.enumerate() if worker not in workers]
 finally:
  gate.set()
  for c in clients:c.close()
  s.shutdown();s.server_close();t.join(1)

def test_activity_and_cooldown_keyspaces_return_to_baseline_under_10000_cycles():
 a=ExecutionActivityRegistry();h=LocalFailureCooldown()
 for n in range(10_000):
  k=f'j{n}';a.start(k,'CHAT','b','LOCAL','p');a.finish(k);h.fail(k);h.success(k)
 assert a.current()==() and h.excluded()==frozenset() and len(h._until)==0

def test_sqlite_and_loop_object_repetition_does_not_leak_fds_or_threads(tmp_path):
 from ai_foundation.store import SQLiteGuardStore
 base_fd=fd_count();base_threads=threading.active_count();p=tmp_path/'g.db'
 for _ in range(500):
  s=SQLiteGuardStore(p);s.spent();s.load()
 gc.collect();assert fd_count()<=base_fd+2;assert threading.active_count()==base_threads

def test_provider_recovery_single_loop_stops_without_duplicate_worker():
 class S:
  def credentials(self):return ()
 s=S();loop=ProviderRecoveryLoop(s,interval=1);base=threading.active_count();t=loop.start();time.sleep(.03)
 assert t.is_alive() and threading.active_count()==base+1
 loop.stop();t.join(1);assert not t.is_alive() and threading.active_count()==base

def test_python_heap_plateaus_for_repeated_bounded_state_cycles():
 a=ExecutionActivityRegistry();tracemalloc.start()
 def cycle(start):
  for n in range(start,start+5000):
   k=str(n);a.start(k,'CHAT','b','LOCAL','p');a.finish(k)
  gc.collect();return tracemalloc.get_traced_memory()[0]
 first=cycle(0);second=cycle(5000);third=cycle(10000);tracemalloc.stop()
 # Current live Python allocations must plateau; peak allocator behavior is intentionally not asserted.
 assert third-first < 256*1024 and abs(third-second)<256*1024 and a.current()==()

def test_inference_result_handoff_is_consumed_not_an_unbounded_cache():
 from ai_foundation.inference_port import InferenceResultStore,LocalInferencePort
 from ai_foundation.core import TaskPlan
 class E:
  def chat(self,text,model=None):return text
 store=InferenceResultStore();port=LocalInferencePort(E(),store)
 for n in range(10_000):
  p=TaskPlan(str(n),'compute','llm',text='x',effect_id=f'e{n}');port.execute(p);assert port.observe(p)=='x'
 assert store._results=={}

def test_bounded_server_releases_slots_and_fds_across_repeated_connections():
 class H(BaseHTTPRequestHandler):
  def do_GET(self):self.send_response(204);self.end_headers()
  def log_message(self,*a):pass
 s=BoundedThreadingHTTPServer(('127.0.0.1',0),H);t=threading.Thread(target=s.serve_forever,daemon=True);t.start();base=fd_count()
 try:
  for _ in range(500):
   with socket.create_connection(s.server_address,timeout=1) as c:
    c.sendall(b'GET / HTTP/1.0\r\n\r\n');c.recv(1024)
  time.sleep(.1);gc.collect()
  assert fd_count()<=base+2 and s._request_slots._value==s.max_concurrent_requests
 finally:s.shutdown();s.server_close();t.join(1)

def test_loopback_http_client_recovers_after_peer_restart_on_same_port():
 from ai_foundation.llama_swap_adapter import LlamaSwapDiscovery
 import json
 class H(BaseHTTPRequestHandler):
  def do_GET(self):
   body=json.dumps({'data':[{'id':'local-general','status':{'value':'ready'}}]}).encode();self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
  def log_message(self,*a):pass
 s=BoundedThreadingHTTPServer(('127.0.0.1',0),H);port=s.server_port;t=threading.Thread(target=s.serve_forever,daemon=True);t.start();d=LlamaSwapDiscovery(f'http://127.0.0.1:{port}',timeout=.2)
 assert d()[0].health=='ONLINE';s.shutdown();s.server_close();t.join(1);assert d()[0].health=='UNAVAILABLE'
 s2=BoundedThreadingHTTPServer(('127.0.0.1',port),H);t2=threading.Thread(target=s2.serve_forever,daemon=True);t2.start()
 try:assert d()[0].health=='ONLINE'
 finally:s2.shutdown();s2.server_close();t2.join(1)
