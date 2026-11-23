"""Generic owner-scoped image observation boundary. Model output has no authority."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class VisionObservation:
    text:str
    backend:str=''
    authoritative:bool=False

class VisionExecutionPort:
    def __init__(self,backend,handoff=None,*,max_bytes=25*1024*1024):
        self.backend=backend; self.handoff=handoff; self.max_bytes=max_bytes
    def observe(self,request,task:str)->VisionObservation:
        if request.capability!='VISION': raise ValueError('VISION capability required')
        if not request.attachments: raise ValueError('VISION requires resolved attachment grants')
        paths=[]; leased=[]
        try:
            for grant in request.attachments:
                raw_path=Path(grant.path)
                if raw_path.is_symlink(): raise ValueError('invalid image attachment')
                p=raw_path.resolve()
                if not p.is_file(): raise ValueError('invalid image attachment')
                if p.stat().st_size<=0 or p.stat().st_size>self.max_bytes: raise ValueError('image attachment size rejected')
                head=p.read_bytes()[:16]
                image_ok=(head.startswith(b'\xff\xd8\xff') or head.startswith(b'\x89PNG\r\n\x1a\n') or head.startswith((b'GIF87a',b'GIF89a')) or (head.startswith(b'RIFF') and head[8:12]==b'WEBP') or head.startswith(b'BM'))
                if not image_ok: raise ValueError('unsupported image attachment')
                if self.handoff is not None and self.handoff.acquire(grant): leased.append(grant)
                paths.append(str(p))
            raw=self.backend.analyze(tuple(paths),task)
            if not isinstance(raw,str) or not raw.strip(): raise RuntimeError('vision backend returned no observation')
            return VisionObservation(raw,getattr(self.backend,'name',type(self.backend).__name__),False)
        finally:
            if self.handoff is not None:
                for grant in reversed(leased): self.handoff.release(grant)
