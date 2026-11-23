"""Construct FILES execution strictly from a trusted CapabilityRequest."""
from pathlib import Path
from .capability_request import CapabilityRequest
from .file_execution import FileScope,ScopedFileExecution

class BoundFiles:
    def __init__(self,read_execution,write_execution=None):
        self._read=read_execution; self._write=write_execution
    def read(self,run_id,target): return self._read.read(run_id,target)
    def list_directory(self,run_id,target): return self._read.list_directory(run_id,target)
    def write(self,run_id,target,content):
        if self._write is None: raise PermissionError("file write capability disabled")
        return self._write.write(run_id,target,content)
    def produce_text_artifact(self,run_id,target,content):
        if self._write is None: raise PermissionError("file write capability disabled")
        from .artifact import produce_text_artifact
        return produce_text_artifact(self._write,run_id,target,content)

def build_files(request:CapabilityRequest,guard,port,*,reconciliation_registry=None,port_binding="",protected=None):
    if request.capability!="FILES": raise ValueError("FILES capability required")
    read_root=str(Path(request.file_read_root).resolve())
    read=ScopedFileExecution(guard,port,FileScope(read_root,read=True,write=False),
        reconciliation_registry=reconciliation_registry,port_binding=port_binding,protected=protected)
    write=None
    if request.file_write_root:
        write_root=str(Path(request.file_write_root).resolve())
        write=ScopedFileExecution(guard,port,FileScope(write_root,read=True,write=True),
            reconciliation_registry=reconciliation_registry,port_binding=port_binding,protected=protected)
    return BoundFiles(read,write)
