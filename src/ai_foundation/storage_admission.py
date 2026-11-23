"""Host-owned admission gate for writes that must not begin near disk exhaustion."""
from pathlib import Path
import shutil
from dataclasses import dataclass

DEFAULT_MIN_FREE_BYTES=2*1024**3

@dataclass(frozen=True)
class StorageStatus:
    free_bytes:int|None; min_free_bytes:int; writable:bool; detail:str

class StorageCapacityError(OSError): pass

class StorageAdmission:
    def __init__(self,root,*,min_free_bytes=DEFAULT_MIN_FREE_BYTES,disk_usage=shutil.disk_usage):
        self.root=Path(root);self.min_free_bytes=min_free_bytes;self.disk_usage=disk_usage
    def status(self):
        target=self.root if self.root.exists() else self.root.parent
        try:
            free=self.disk_usage(target).free
            return StorageStatus(free,self.min_free_bytes,free>=self.min_free_bytes,f'{free} bytes free; {self.min_free_bytes} bytes required')
        except OSError:
            return StorageStatus(None,self.min_free_bytes,False,'storage capacity unreadable')
    def require(self,operation='write'):
        status=self.status()
        if not status.writable:
            reason='storage capacity unreadable' if status.free_bytes is None else 'low free space'
            raise StorageCapacityError(f'{operation} blocked: {reason}')
        return status.free_bytes
