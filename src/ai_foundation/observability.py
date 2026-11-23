import contextlib
import contextvars
import json
import time
import uuid
import os
import threading
from dataclasses import asdict, dataclass, field
from typing import Protocol

_current_trace = contextvars.ContextVar('ai_foundation_trace', default='')
_current_span = contextvars.ContextVar('ai_foundation_span', default='')
_current_run_id = contextvars.ContextVar('ai_foundation_run_id', default='')

@dataclass(frozen=True)
class TraceEvent:
    trace_id: str
    span_id: str
    parent_span_id: str
    name: str
    started_ns: int
    ended_ns: int
    status: str
    attributes: dict = field(default_factory=dict)
    evidence_ids: tuple[str, ...] = ()

class TraceSink(Protocol):
    def emit(self, event: TraceEvent) -> None: ...

class InMemoryTraceSink:
    def __init__(self): self.events=[]
    def emit(self,event): self.events.append(event)

class JsonlTraceSink:
    """Bounded JSONL trace sink; rotation occurs before an append crosses the size cap."""
    def __init__(self,path,max_bytes=8*1024*1024,backups=3):
        self.path=str(path); self.max_bytes=max(1024,int(max_bytes)); self.backups=max(1,int(backups)); self._lock=threading.Lock()
    def _rotate(self,incoming):
        try:size=os.path.getsize(self.path)
        except FileNotFoundError:return
        if size+incoming <= self.max_bytes:return
        oldest=f'{self.path}.{self.backups}'
        try:os.remove(oldest)
        except FileNotFoundError:pass
        for i in range(self.backups-1,0,-1):
            src=f'{self.path}.{i}'
            if os.path.exists(src):os.replace(src,f'{self.path}.{i+1}')
        os.replace(self.path,f'{self.path}.1')
    def emit(self,event):
        line=json.dumps(asdict(event),ensure_ascii=False,separators=(',',':'))+'\n'
        encoded=line.encode('utf-8')
        with self._lock:
            self._rotate(len(encoded))
            with open(self.path,'a',encoding='utf-8') as f:f.write(line)

@contextlib.contextmanager
def trace_run(run_id):
    """Bind a host-generated run id to observability only; it never conveys authority."""
    token=_current_run_id.set(str(run_id or ''))
    try:
        yield
    finally:
        _current_run_id.reset(token)

class Tracer:
    def __init__(self,sink): self.sink=sink
    @contextlib.contextmanager
    def span(self,name,attributes=None,evidence_ids=()):
        parent=_current_span.get()
        trace_id=_current_trace.get() if parent else uuid.uuid4().hex
        span_id=uuid.uuid4().hex[:16]
        tt=_current_trace.set(trace_id); st=_current_span.set(span_id)
        start=time.time_ns(); status='OK'
        try:
            yield {'trace_id':trace_id,'span_id':span_id}
        except Exception as exc:
            status='ERROR'
            if isinstance(exc,TimeoutError) and attributes is not None and 'timeout' in attributes: attributes['timeout']='true'
            raise
        finally:
            attrs=dict(attributes or {})
            run_id=_current_run_id.get()
            if run_id: attrs['correlation_id']=run_id
            event=TraceEvent(trace_id,span_id,parent,name,start,time.time_ns(),status,attrs,tuple(evidence_ids))
            _current_span.reset(st); _current_trace.reset(tt)
            self.sink.emit(event)

SAFE_ATTRIBUTE_KEYS = frozenset({'run_id','job_id','effect_id','step','action','target_kind','decision','status','specialist','capability','policy_revision','canon_revision','route_binding','route_kind','provider','phase','attempt','timeout','fallback_reason','has_text','tool_call_count','tool_count','tool_names','message_count','finish_reason','correlation_id'})

def safe_attributes(values):
    """Default-deny trace metadata: only explicit non-secret operational keys survive."""
    return {k:str(v) for k,v in values.items() if k in SAFE_ATTRIBUTE_KEYS and v is not None}

class ObservedCall:
    """Small composition wrapper; keeps instrumentation outside business semantics."""
    def __init__(self,tracer,name,call,attributes=None,evidence_ids=()):
        self.tracer=tracer; self.name=name; self.call=call
        self.attributes=safe_attributes(attributes or {}); self.evidence_ids=tuple(evidence_ids)
    def __call__(self,*args,**kwargs):
        with self.tracer.span(self.name,self.attributes,self.evidence_ids):
            return self.call(*args,**kwargs)

def read_jsonl_trace(path):
    """Read durable trace records; reject partial/corrupt records instead of guessing."""
    events=[]
    with open(path,encoding='utf-8') as f:
        for line_no,line in enumerate(f,1):
            if not line.strip(): continue
            try: row=json.loads(line)
            except json.JSONDecodeError as exc: raise ValueError(f'corrupt trace record at line {line_no}') from exc
            required={'trace_id','span_id','parent_span_id','name','started_ns','ended_ns','status','attributes','evidence_ids'}
            if set(row) != required: raise ValueError(f'invalid trace schema at line {line_no}')
            events.append(TraceEvent(row['trace_id'],row['span_id'],row['parent_span_id'],row['name'],row['started_ns'],row['ended_ns'],row['status'],row['attributes'],tuple(row['evidence_ids'])))
    return tuple(events)
