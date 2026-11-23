from dataclasses import dataclass
from .observability import safe_attributes

@dataclass
class ObservedGuard:
    guard: object
    tracer: object
    def get_effect(self,effect_id):
        return self.guard.get_effect(effect_id)
    def execute(self,plan,canon,port,expected,**kwargs):
        attrs=safe_attributes({'run_id':plan.run_id,'effect_id':plan.effect_id or plan.run_id,'action':plan.action,'canon_revision':plan.canon_revision,'policy_revision':plan.policy_revision})
        evidence=(f'effect:{plan.effect_id or plan.run_id}',)
        with self.tracer.span('guard.execute',attrs,evidence):
            return self.guard.execute(plan,canon,port,expected,**kwargs)

@dataclass
class ObservedDurableWorkRunner:
    runner: object
    tracer: object
    def execute(self,job_id,steps):
        with self.tracer.span('work.execute',safe_attributes({'job_id':job_id})):
            wrapped=[]
            for name,fn in steps:
                def call(fn=fn,name=name):
                    with self.tracer.span('work.step',safe_attributes({'job_id':job_id,'step':name})):
                        return fn()
                wrapped.append((name,call))
            return self.runner.execute(job_id,wrapped)
    def reconcile_running(self,job_id,position,reconcile):
        with self.tracer.span('work.reconcile',safe_attributes({'job_id':job_id,'step':position})):
            return self.runner.reconcile_running(job_id,position,reconcile)

@dataclass
class ObservedSpecialist:
    specialist: object
    tracer: object
    specialist_name: str
    def call(self,method,*args,**kwargs):
        attrs=safe_attributes({'specialist':self.specialist_name,'action':method})
        with self.tracer.span('specialist.call',attrs):
            return getattr(self.specialist,method)(*args,**kwargs)
