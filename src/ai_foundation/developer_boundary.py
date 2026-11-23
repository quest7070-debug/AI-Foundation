from dataclasses import dataclass
from .protected_resources import ProtectedResources

@dataclass(frozen=True)
class DeveloperAuthority:
    """Developer can edit scoped project files, never local-model control plane."""
    protected: ProtectedResources
    def authorize_action(self,action):
        self.protected.validate_action(action)
        return True
    def authorize_write(self,target):
        self.protected.validate_write(target)
        return True
