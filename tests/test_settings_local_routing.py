from ai_foundation.settings_service import SettingsService
from ai_foundation.local_compute_registry import LocalComputeRegistry,LocalComputeCandidate
class Probe:pass
class Secrets:pass
def test_local_is_ordinary_persisted_route_candidate(tmp_path):
 local=LocalComputeRegistry(lambda:(LocalComputeCandidate('local:x',health='ONLINE',capabilities=('CHAT','CODE')),))
 s=SettingsService(tmp_path,Probe(),Secrets(),local_compute=local)
 rows=s.optimize_all_routes(); by={r.function:r for r in rows}
 assert by['CHAT'].primary=='local:x' and by['CODE'].primary is None
 assert by['SEARCH'].primary is None and by['DATA'].primary is None
 assert s.route_label('local:x')=='Local'
 assert s.choose_route('CHAT')=='local:x'

def test_no_inert_routing_preferences_are_exposed(tmp_path):
 local=LocalComputeRegistry(lambda:(LocalComputeCandidate('local:x',health='ONLINE',capabilities=('CHAT','CODE')),))
 s=SettingsService(tmp_path,Probe(),Secrets(),local_compute=local);s.optimize_all_routes()
 for f in s.ROUTE_FUNCTIONS:
  assert s.routing.preferences(f)=={}


def test_task_route_follows_dynamic_local_inventory_replacement(tmp_path):
 state={'binding':'local:old'}
 local=LocalComputeRegistry(lambda:(LocalComputeCandidate(state['binding'],health='ONLINE',capabilities=('CODE',)),))
 s=SettingsService(tmp_path,Probe(),Secrets(),local_compute=local)
 assert s.optimize_routing('CODE').primary is None
 assert s.choose_route('CODE') is None
 state['binding']='local:new'
 assert s.optimize_routing('CODE').primary is None
 assert s.choose_route('CODE') is None
 assert 'local:old' not in (s.route('CODE').primary,)+s.route('CODE').standby


def test_local_route_label_uses_live_inventory_model_name(tmp_path):
 local=LocalComputeRegistry(lambda:(LocalComputeCandidate('local:x',health='ONLINE',capabilities=('CODE',),model='code-model'),))
 s=SettingsService(tmp_path,Probe(),Secrets(),local_compute=local)
 assert s.route_label('local:x')=='code-model'
