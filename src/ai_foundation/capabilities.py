from dataclasses import dataclass
from enum import Enum
from typing import Protocol, Any

class CapabilityKind(str, Enum):
    READ='READ'
    COMPUTE='COMPUTE'
    EFFECT='EFFECT'

@dataclass(frozen=True)
class CapabilitySpec:
    name: str
    kind: CapabilityKind

class ComputePort(Protocol):
    def compute(self, operation: str, payload: str) -> Any: ...

@dataclass
class BoundComputeCapability:
    """Pure/local computation: no external observation or side effect."""
    port: ComputePort
    allowed_operations: frozenset[str]

    def run(self, operation: str, payload: str):
        if operation not in self.allowed_operations:
            raise PermissionError('compute operation outside bound capability')
        return self.port.compute(operation,payload)

@dataclass
class FixedComputeTool:
    """Model chooses payload only; operation authority is host-bound."""
    capability: BoundComputeCapability
    operation: str
    def run(self, payload: str):
        return self.capability.run(self.operation,payload)
