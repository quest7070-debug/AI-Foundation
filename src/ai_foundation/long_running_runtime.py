"""Single production composition root for external Hatchet long-running work."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from .hatchet_bootstrap import ExternalHatchetConfig,build_client
from .hatchet_submission import HatchetRunStore,HatchetSubmissionPort
from .long_running import LongRunningWorkService
from .long_running_authority import LongRunningAuthorityStore,DurableLongRunningExecutor
from .long_running_producer import LongRunningProducer
from .hatchet_worker import LongRunningWorkerHandler,build_worker

@dataclass(frozen=True)
class LongRunningRuntime:
 client:object
 producer:LongRunningProducer
 worker:object
 authority_store:LongRunningAuthorityStore
 run_store:HatchetRunStore

def build_long_running_runtime(root,capability_executor,secret_store,env=None):
 """Compose producer and worker from the same durable authority and external client."""
 root=Path(root);config=ExternalHatchetConfig.from_native_store(secret_store,env=env)
 client=build_client(config)
 authority=LongRunningAuthorityStore(root/'long-running-authority.sqlite')
 runs=HatchetRunStore(root/'hatchet-runs.sqlite')
 service=LongRunningWorkService(HatchetSubmissionPort(client,run_store=runs))
 producer=LongRunningProducer(authority,service)
 executor=DurableLongRunningExecutor(authority,capability_executor)
 worker=build_worker(client,LongRunningWorkerHandler(executor))
 return LongRunningRuntime(client,producer,worker,authority,runs)
