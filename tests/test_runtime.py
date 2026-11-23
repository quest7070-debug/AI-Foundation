from ai_foundation.runtime import HatchetRuntime


def test_external_runtime_is_fail_closed_until_configured():
    result = HatchetRuntime(embedded=False).health()
    assert result == {"ok": False, "mode": "external", "reason": "not_configured"}


def test_guarded_runtime_waits_for_live_effect_then_reconciles():
    from ai_foundation.runtime import GuardedRuntimeCall
    results = iter(["EFFECT_IN_PROGRESS", "EFFECT_IN_PROGRESS", "VERIFIED_COMPLETE"])
    assert GuardedRuntimeCall(retry_interval=0.001, wait_timeout=0.1).run(lambda: next(results)) == "VERIFIED_COMPLETE"


def test_guarded_runtime_busy_timeout_is_not_an_exception():
    from ai_foundation.runtime import GuardedRuntimeCall
    assert GuardedRuntimeCall(retry_interval=0.001, wait_timeout=0.003).run(lambda: "EFFECT_IN_PROGRESS") == "EFFECT_IN_PROGRESS"

def test_runtime_defers_live_target_lease_then_retries():
    from ai_foundation.runtime import GuardedRuntimeCall
    results = iter(["TARGET_IN_PROGRESS", "TARGET_IN_PROGRESS", "VERIFIED_COMPLETE"])
    assert GuardedRuntimeCall(retry_interval=0.001, wait_timeout=0.1).run(lambda: next(results)) == "VERIFIED_COMPLETE"

def test_runtime_returns_target_in_progress_after_timeout():
    from ai_foundation.runtime import GuardedRuntimeCall
    assert GuardedRuntimeCall(retry_interval=0.001, wait_timeout=0.003).run(lambda: "TARGET_IN_PROGRESS") == "TARGET_IN_PROGRESS"


def test_hatchet_health_failure_does_not_expose_exception_text(monkeypatch):
 import builtins
 real=builtins.__import__
 def blocked(name,*a,**k):
  if name=='hatchet_sdk': raise RuntimeError('secret-token-in-error')
  return real(name,*a,**k)
 monkeypatch.setattr(builtins,'__import__',blocked)
 result=HatchetRuntime().health()
 assert result=={'ok':False,'mode':'embedded','reason':'RuntimeError'}
 assert 'secret-token' not in str(result)

def test_external_runtime_uses_explicit_client_factory_without_embedded_fallback():
 class C:
  def get_engine_version(self): return 'v1'
 assert HatchetRuntime(embedded=False,client_factory=lambda:C()).health()=={'ok':True,'mode':'external','version':'v1'}

def test_external_runtime_fails_closed_and_redacts_client_errors():
 def bad(): raise RuntimeError('secret endpoint/token')
 assert HatchetRuntime(embedded=False,client_factory=bad).health()=={'ok':False,'mode':'external','reason':'RuntimeError'}
