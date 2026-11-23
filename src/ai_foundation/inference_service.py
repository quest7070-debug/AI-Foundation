from dataclasses import dataclass
from datetime import datetime,timezone
import time
from ai_foundation.core import CanonContract, Decision, TaskPlan
from ai_foundation.inference_port import CloudInferencePort, InferenceResultStore, LocalInferencePort
from ai_foundation.local_health import LocalFailureCooldown
from ai_foundation.host_compute_lease import HostComputeBusy, HostComputeLeaseError
from ai_foundation.model_work_roles import evaluate_model_work

@dataclass(frozen=True)
class InferenceOutcome:
    status: str
    route_kind: str | None
    result: str | None
    route_binding: str | None = None
    observed_at: datetime | None = None

class GuardedInferenceService:
    def __init__(self, guard, router, local_execution, cloud_factory=None, results=None, activity=None, attempts=None, local_health=None, tracer=None):
        self.guard = guard
        self.router = router
        self.local_execution = local_execution
        self.cloud_factory = cloud_factory
        self.results = results or InferenceResultStore()
        self.activity = activity
        self.attempts = attempts
        self.local_health = local_health or LocalFailureCooldown()
        self.tracer = tracer

    def run(self, plan: TaskPlan, canon: CanonContract, function='CHAT', prefer_local=False, *, role_contract=None):
        decision = self.guard.preflight(plan, canon)
        local_required = decision is Decision.LOCAL_ONLY
        if decision not in {Decision.ALLOW, Decision.LOCAL_ONLY}:
            return InferenceOutcome(decision.value, None, None)
        external_preferred=False
        if role_contract is not None:
            # The trusted host, not model output, supplies a bounded public-role contract.
            role=evaluate_model_work(role_contract,text=plan.text,privacy_text=plan.privacy_text)
            if not role.allowed:
                return InferenceOutcome('ROLE_POLICY_DENIED',None,None)
            # Guard LOCAL_ONLY always overrides an external-first preference.
            local_required=local_required or role.local_required
            external_preferred=role.external_preferred and not local_required

        # Public, host-reviewed requests use remote-local Strata first when
        # it explicitly advertises the requested capability. An explicit
        # same-host preference and Guard LOCAL_ONLY both take precedence.
        strata_first = external_preferred and not prefer_local and not local_required
        attempted=set(self.local_health.excluded())
        if strata_first:
            # Refresh live discovery for each new host-attested public task.
            # Earlier transport failures are not evidence the optional PC is
            # still asleep. In-request exclusion remains strict.
            attempted.discard('local:mainpc-strata:code-agent')
        while True:
            kwargs={'local_required':local_required,'prefer_local':prefer_local,'exclude':attempted}
            if external_preferred: kwargs['external_preferred']=True
            if strata_first: kwargs['strata_first']=True
            route=self.router.choose(function,**kwargs)
            if not route.binding:
                return InferenceOutcome('NO_ELIGIBLE_COMPUTE', None, None)
            # Never trust a router to downgrade Guard's LOCAL_ONLY decision.
            if (local_required and route.kind != 'LOCAL') or route.kind not in ('LOCAL', 'CLOUD'):
                return InferenceOutcome('NO_ELIGIBLE_COMPUTE', None, None)
            attempted.add(route.binding)
            if route.kind == 'LOCAL':
                execution = self.local_execution.for_binding(route.binding) if hasattr(self.local_execution,'for_binding') else self.local_execution
                port = LocalInferencePort(execution, self.results, model=getattr(route,'execution_slot',None) or getattr(route,'model',None))
            else:
                if self.cloud_factory is None:
                    return InferenceOutcome('NO_ELIGIBLE_COMPUTE', None, None)
                port = CloudInferencePort(self.cloud_factory(route.binding), route.binding, self.results, function.upper(), self.attempts)
            job_id=plan.run_id
            # Selected local model identity is already in the route. Never
            # rediscover all backends just to label an activity event.
            provider=(getattr(route,'model',None) or 'Local') if route.kind=='LOCAL' else (
                self.router.settings.route_label(route.binding) if getattr(self.router,'settings',None) else route.kind)
            if self.activity:self.activity.start(job_id,function.upper(),route.binding,route.kind,provider)
            started=time.perf_counter()
            try:
                # Inference has no external effect. A failed provider/model attempt may therefore
                # fall through to the next eligible saved route without violating effect idempotency.
                if self.tracer:
                    from ai_foundation.observability import safe_attributes
                    with self.tracer.span('inference.attempt',safe_attributes({'run_id':job_id,'capability':function.upper(),'route_binding':route.binding,'route_kind':route.kind,'provider':provider})):
                        port.execute(plan); result = port.observe(plan)
                else:
                    port.execute(plan); result = port.observe(plan)
                if result:
                    if route.kind == 'LOCAL': self.local_health.success(route.binding)
                    if hasattr(self.router,'record_runtime'): self.router.record_runtime(function.upper(),route.binding,True,(time.perf_counter()-started)*1000)
                    return InferenceOutcome('VERIFIED_COMPLETE', route.kind, result, route.binding, datetime.now(timezone.utc))
            except (HostComputeBusy, HostComputeLeaseError):
                # Compute contention is not a model failure. No cloud fallback,
                # health cooldown, or alternate model launch.
                if route.kind == 'LOCAL':
                    return InferenceOutcome('LOCAL_RESOURCE_DEFERRED', route.kind, None, route.binding)
                raise
            except Exception:
                if hasattr(self.router,'record_runtime'): self.router.record_runtime(function.upper(),route.binding,False,(time.perf_counter()-started)*1000)
                if route.kind == 'LOCAL' and not (
                        strata_first and route.binding == 'local:mainpc-strata:code-agent'):
                    self.local_health.fail(route.binding)
                if route.kind == 'CLOUD' and self.attempts is not None:
                    prior=self.attempts.get(plan.effect_id or plan.run_id)
                    if prior and prior.status in {'DISPATCHING', 'UNCERTAIN'}:
                        # A prior durable dispatch may have reached its
                        # provider. Neither another cloud binding nor local
                        # fallback may fabricate a second answer for this ID.
                        return InferenceOutcome('UNCERTAIN_RECONCILE_REQUIRED', route.kind, None, route.binding)
                pass
            finally:
                if self.activity:self.activity.finish(job_id)
