from ai_foundation.coding import CodingSpecialist
class WriteCapability:
 def authorize_target(self,target): return target

class Tools:
 def __init__(self):
  self.writes=0
  self.write_capability=WriteCapability()
 def read(self,t): return 'old'
 def write(self,t,c): self.writes+=1; return 'VERIFIED_COMPLETE'
class FakeTests:
 def __init__(self): self.n=0
 def run_tests(self,t): self.n+=1; return 'pass'
def test_inspect_is_observational_and_does_not_run_tests():
 t=Tools(); q=FakeTests(); r=CodingSpecialist(t,q).inspect('x')
 assert r.observed=='old'
 assert r.test_result=='NOT_RUN: observational inspect'
 assert r.write_result is None
 assert t.writes==0 and q.n==0
def test_change_uses_effect_tool_and_retests():
 t=Tools(); q=FakeTests(); r=CodingSpecialist(t,q).apply_verified_change('x','new')
 assert t.writes==1 and q.n==2 and r.write_result=='VERIFIED_COMPLETE'


class FailingAfterWrite:
 def __init__(self): self.n=0
 def run_tests(self,t):
  self.n+=1
  if self.n==2: raise RuntimeError('post-test failed')
  return 'pre-pass'

def test_post_test_failure_keeps_verified_effect_distinct():
 t=Tools(); r=CodingSpecialist(t,FailingAfterWrite()).apply_verified_change('x','new')
 assert t.writes==1
 assert r.write_result=='VERIFIED_COMPLETE'
 assert 'after=FAILED: post-test failed' in r.test_result

class UncertainTools(Tools):
 def write(self,t,c):
  self.writes += 1
  return 'UNCERTAIN_RECONCILE_REQUIRED'

def test_nonverified_effect_does_not_run_post_change_tests():
 t=UncertainTools(); q=FakeTests()
 r=CodingSpecialist(t,q).apply_verified_change('x','new')
 assert t.writes==1
 assert q.n==1
 assert r.write_result=='UNCERTAIN_RECONCILE_REQUIRED'
 assert 'after=NOT_RUN: effect=UNCERTAIN_RECONCILE_REQUIRED' in r.test_result

def test_specialist_delegates_write_authority_to_bound_tool():
 class DeniedTools(Tools):
  def read(self,t): return 'old'
  def write(self,t,c): raise PermissionError('protected')
 q=FakeTests()
 try:
  CodingSpecialist(DeniedTools(),q).apply_verified_change('llama-swap.yaml','new')
 except PermissionError:
  pass
 else:
  raise AssertionError('bound write authority was bypassed')
 assert q.n==1


def test_protected_policy_uses_normalized_bound_target_before_write():
 class Protected:
  def __init__(self): self.seen=[]
  def validate_write(self,target):
   self.seen.append(target)
   if target.endswith('llama-swap.yaml'): raise PermissionError('protected')
 t=Tools(); p=Protected(); q=FakeTests()
 try:
  CodingSpecialist(t,q,p).apply_verified_change('llama-swap.yaml','new')
 except PermissionError:
  pass
 else:
  raise AssertionError('protected target was written')
 assert p.seen==['llama-swap.yaml']
 assert t.writes==0 and q.n==1
