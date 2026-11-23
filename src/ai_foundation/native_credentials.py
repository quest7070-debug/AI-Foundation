from dataclasses import dataclass
import platform
import subprocess
from typing import Protocol

class NativeCredentialStore(Protocol):
    def available(self, binding: str) -> bool: ...

@dataclass
class MacOSNativeCredentialStore:
    service: str = "ai-foundation"
    def _backend(self):
        from .macos_keychain import MacOSKeychain
        return MacOSKeychain(self.service)
    def available(self,binding):
        if platform.system() != "Darwin" or not binding:return False
        try:return self._backend().available(binding)
        except (OSError,RuntimeError):return False
    def save(self,binding,secret): return self._backend().save(binding,secret)
    def load(self,binding): return self._backend().load(binding)
    def delete(self,binding): return self._backend().delete(binding)

class NativeCredentialProvider:
    def __init__(self, stores=None):
        self.stores = stores or {"Darwin": MacOSNativeCredentialStore()}

    def available(self, binding: str) -> bool:
        store = self.stores.get(platform.system())
        return bool(store and store.available(binding))
