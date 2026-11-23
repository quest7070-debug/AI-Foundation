from dataclasses import dataclass

@dataclass
class HatchetInferenceTask:
    """Hatchet task adapter; durable attempt state prevents blind cloud redelivery."""
    inference: object
    canon: object
    function: str = 'CHAT'
    def __call__(self,plan):
        return self.inference.run(plan,self.canon,self.function)

def task_defaults():
    """Inference itself is not retried by Hatchet; Foundation owns uncertainty/reconciliation."""
    try:
        from hatchet_sdk.runnables.types import TaskDefaults
        return TaskDefaults(retries=0)
    except ImportError:
        return None
