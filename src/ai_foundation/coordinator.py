from dataclasses import dataclass

from .core import CanonContract, Decision, ExecutionPort, TaskPlan
from .guard import GuardCore


@dataclass
class ExecutionCoordinator:
    guard: GuardCore
    cloud: ExecutionPort
    local: ExecutionPort

    def run(self, plan: TaskPlan, canon: CanonContract, expected: str) -> str:
        decision = self.guard.preflight(plan, canon)
        if decision is Decision.LOCAL_ONLY:
            local_plan = TaskPlan(
                run_id=plan.run_id, action=plan.action, target=plan.target, text=plan.text,
                paid_cost=0, canon_revision=plan.canon_revision,
                target_precondition=plan.target_precondition, exclusive_target=plan.exclusive_target,
            )
            result = self.guard.execute(local_plan, canon, self.local, expected, local_only=True)
            return "LOCAL_VERIFIED_COMPLETE" if result == "VERIFIED_COMPLETE" else result
        return self.guard.execute(plan, canon, self.cloud, expected)
