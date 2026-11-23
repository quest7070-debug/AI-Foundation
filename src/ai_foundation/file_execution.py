from dataclasses import dataclass
from pathlib import Path
from .agent_tools import CapabilityAgentTools,GuardedToolGateway,ReadCapability,WriteCapability
from .core import CanonContract,TaskPlan
from .protected_resources import ProtectedResources

@dataclass(frozen=True)
class FileScope:
    root: str
    read: bool = True
    write: bool = False
    def normalized_root(self):
        return str(Path(self.root).resolve())

class ScopedFileExecution:
    """Trusted host-owned FILES boundary. Scope is never inferred from model text."""
    def __init__(self,guard,port,scope:FileScope,*,canon_revision='files-v1',reconciliation_registry=None,port_binding='',protected=None):
        root=scope.normalized_root()
        self.protected=protected or ProtectedResources()
        self.protected.validate_scope(root,scope.write)
        self.scope=scope
        self.tools=CapabilityAgentTools(
            GuardedToolGateway(guard,CanonContract('foundation-files',canon_revision),port,reconciliation_registry,port_binding),
            '',canon_revision,ReadCapability(root),WriteCapability(root))
    def for_run(self,run_id):
        t=self.tools
        return CapabilityAgentTools(t.gateway,run_id,t.canon_revision,t.read_capability,t.write_capability)
    def read(self,run_id,target):
        if not self.scope.read: raise PermissionError('file read capability disabled')
        return self.for_run(run_id).read(target)
    def list_directory(self,run_id,target):
        if not self.scope.read: raise PermissionError('file read capability disabled')
        tools=self.for_run(run_id)
        safe=tools.read_capability.authorize_target(target)
        return tools.gateway.port.observe(TaskPlan(run_id,'list_directory',safe,canon_revision=tools.canon_revision))
    def write(self,run_id,target,content,*,effect_id=''):
        if not self.scope.write: raise PermissionError('file write capability disabled')
        # Scope authorization belongs to the bound WriteCapability. Protected-resource
        # policy receives the same normalized target before the Guarded write.
        tools=self.for_run(run_id)
        safe=tools.write_capability.authorize_target(target)
        self.protected.validate_write(safe)
        if effect_id:
            return tools.gateway.write(run_id=run_id,target=safe,content=content,
                canon_revision=tools.canon_revision,effect_id=effect_id)
        return tools.write(target,content)
