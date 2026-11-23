from dataclasses import dataclass, field
import itertools
from .core import CanonContract, ExecutionPort, TaskPlan
from .guard import GuardCore

def _nonblank_scoped_path(value, label):
    from pathlib import Path
    if not isinstance(value, (str, Path)):
        raise ValueError(label + " must be a nonblank path")
    text = str(value)
    if not text or text.strip() != text:
        raise ValueError(label + " must be a nonblank path")
    return Path(value)


@dataclass
class GuardedToolGateway:
    guard: GuardCore
    canon: CanonContract
    port: ExecutionPort
    reconciliation_registry: object = None
    port_binding: str = ""

    def write(self, *, run_id: str, target: str, content: str, canon_revision: str, paid_cost: int = 0, effect_id: str = "") -> str:
        plan=TaskPlan(run_id,'write',target,text=content,paid_cost=paid_cost,canon_revision=canon_revision,exclusive_target=True,effect_id=effect_id)
        eid=effect_id or run_id
        if self.reconciliation_registry is not None:
            if not self.port_binding: raise RuntimeError('reconciliation port binding required')
            self.reconciliation_registry.register(eid,plan,self.port_binding)
        return self.guard.execute(plan,self.canon,self.port,content)

@dataclass
class BoundGuardedWriteTool:
    """Authority-bearing fields are bound by trusted host code, never supplied by the model."""
    gateway: GuardedToolGateway
    run_id: str
    canon_revision: str
    paid_cost: int = 0

    def __call__(self, target: str, content: str) -> str:
        return self.gateway.write(
            run_id=self.run_id, target=target, content=content,
            canon_revision=self.canon_revision, paid_cost=self.paid_cost,
        )

@dataclass
class BoundAgentTools:
    """Agent-facing tools with authority fields bound outside model arguments."""
    gateway: GuardedToolGateway
    run_id: str
    canon_revision: str

    def write(self, target: str, content: str) -> str:
        return self.gateway.write(
            run_id=self.run_id, target=target, content=content,
            canon_revision=self.canon_revision,
        )

@dataclass(frozen=True)
class WriteCapability:
    """Trusted host-bound scope for one agent write capability."""
    target_root: str

    def authorize_target(self, target: str) -> str:
        root=_nonblank_scoped_path(self.target_root,'target_root').resolve()
        raw=_nonblank_scoped_path(target,'target')
        candidate=(raw if raw.is_absolute() else root/raw).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as e:
            raise PermissionError("agent target outside bound capability") from e
        return str(candidate)

@dataclass
class ScopedAgentTools:
    gateway: GuardedToolGateway
    run_id: str
    canon_revision: str
    write_capability: WriteCapability

    def write(self, target: str, content: str) -> str:
        safe_target=self.write_capability.authorize_target(target)
        return self.gateway.write(
            run_id=self.run_id, target=safe_target, content=content,
            canon_revision=self.canon_revision,
        )

@dataclass(frozen=True)
class ReadCapability:
    target_root: str

    def authorize_target(self, target: str) -> str:
        root=_nonblank_scoped_path(self.target_root,'target_root').resolve()
        raw=_nonblank_scoped_path(target,'target')
        candidate=(raw if raw.is_absolute() else root/raw).resolve()
        try: candidate.relative_to(root)
        except ValueError as e: raise PermissionError("agent read target outside bound capability") from e
        return str(candidate)

@dataclass
class CapabilityAgentTools:
    """Read is observational; writes remain durable Guard effects."""
    gateway: GuardedToolGateway
    run_id: str
    canon_revision: str
    read_capability: ReadCapability
    write_capability: WriteCapability
    _effect_seq: object = field(default_factory=lambda: itertools.count(1), init=False, repr=False)

    def read(self, target: str) -> str:
        safe=self.read_capability.authorize_target(target)
        plan=TaskPlan(self.run_id,'read',safe,canon_revision=self.canon_revision)
        return self.gateway.port.observe(plan)

    def write(self, target: str, content: str) -> str:
        safe=self.write_capability.authorize_target(target)
        return self.gateway.write(run_id=self.run_id,target=safe,content=content,canon_revision=self.canon_revision,effect_id=f"{self.run_id}:effect:{next(self._effect_seq)}")
