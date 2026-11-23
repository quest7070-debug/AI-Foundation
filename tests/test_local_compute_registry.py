from ai_foundation.local_compute_registry import LocalComputeRegistry,LocalComputeCandidate
from ai_foundation.human_view import from_snapshot
from ai_foundation.human_renderer import render
class S:
 def as_dict(self):return {'ready':True,'waiting_human':0,'effects':{},'attention':[]}
def test_local_compute_is_semantic_candidate_not_model_ui():
 reg=LocalComputeRegistry(lambda:[{'binding':'local:general','health':'ONLINE','capabilities':('CHAT','CODE','DATA')}])
 rows=reg.candidates(); assert rows[0].provider=='LOCAL' and rows[0].binding=='local:general'
 page=render(from_snapshot(S(),local_compute=rows),'responsive')
 assert 'LOCAL COMPUTE' in page and 'ONLINE' in page and 'local:general' not in page


def test_local_compute_groups_dynamic_inventory_in_one_card():
 rows=(
  LocalComputeCandidate('local:llama-swap:a',health='ONLINE',capabilities=('CHAT',),model='model-a',roles=('CHAT',)),
  LocalComputeCandidate('local:llama-swap:b',health='ONLINE',capabilities=('CODE',),model='model-b',roles=('CODE','CODE_REVIEW')),
 )
 page=render(from_snapshot(S(),local_compute=rows),'responsive')
 assert page.count('>LOCAL COMPUTE</b>')==1
 assert '2 MODELS' in page and 'model-a' in page and 'model-b' in page
 assert 'CHAT' in page and 'CODE · CODE_REVIEW' in page

def test_local_compute_group_tracks_inventory_replacement_without_fixed_models():
 before=LocalComputeRegistry(lambda:(LocalComputeCandidate('local:llama-swap:old',health='ONLINE',capabilities=('CODE',),model='old-model',roles=('CODE',)),))
 after=LocalComputeRegistry(lambda:(LocalComputeCandidate('local:llama-swap:new',health='ONLINE',capabilities=('CODE',),model='new-model',roles=('CODE',)),))
 first=render(from_snapshot(S(),local_compute=before.candidates()),'responsive')
 second=render(from_snapshot(S(),local_compute=after.candidates()),'responsive')
 assert 'old-model' in first and 'new-model' not in first
 assert 'new-model' in second and 'old-model' not in second

def test_local_compute_card_projects_model_slot_characteristics_and_role():
 row=LocalComputeCandidate('local:x',health='ONLINE',capabilities=('CODE',),model='org/code-model',roles=('CODE',),slot='local-code-agent',characteristics=('CODE GENERATION',))
 page=render(from_snapshot(S(),local_compute=(row,)),'responsive')
 for value in ('code-model','CODE','ONLINE'):
  assert value in page
 assert 'org/code-model' not in page and 'code agent' not in page and 'CODE GENERATION' not in page

def test_composite_local_registry_unions_sources_without_duplicate_binding():
 from ai_foundation.local_compute_registry import CompositeLocalComputeRegistry
 a=LocalComputeRegistry(lambda:(LocalComputeCandidate('local:m1:a',health='ONLINE'),))
 b=LocalComputeRegistry(lambda:(LocalComputeCandidate('local:pc:b',health='ONLINE'),LocalComputeCandidate('local:m1:a',health='ONLINE')))
 assert [x.binding for x in CompositeLocalComputeRegistry(a,b).candidates()]==['local:m1:a','local:pc:b']
