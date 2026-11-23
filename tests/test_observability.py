import json
import pytest
from ai_foundation.observability import InMemoryTraceSink, JsonlTraceSink, Tracer

def test_nested_spans_share_trace_and_link_parent():
    sink=InMemoryTraceSink(); t=Tracer(sink)
    with t.span('job',{'job_id':'j1'}) as root:
        with t.span('step',evidence_ids=('ev1',)) as child: pass
    child_event,root_event=sink.events
    assert child_event.trace_id==root_event.trace_id==root['trace_id']
    assert child_event.parent_span_id==root_event.span_id
    assert child_event.evidence_ids==('ev1',)
    assert root_event.attributes=={'job_id':'j1'}

def test_error_span_records_error_and_reraises():
    sink=InMemoryTraceSink(); t=Tracer(sink)
    with pytest.raises(ValueError):
        with t.span('bad'): raise ValueError('sensitive detail must not be stored')
    assert sink.events[0].status=='ERROR'
    assert 'sensitive' not in repr(sink.events[0])

def test_jsonl_sink_roundtrip(tmp_path):
    p=tmp_path/'trace.jsonl'; t=Tracer(JsonlTraceSink(p))
    with t.span('x',{'safe':'yes'},('e1',)): pass
    row=json.loads(p.read_text())
    assert row['name']=='x' and row['attributes']['safe']=='yes' and row['evidence_ids']==['e1']

def test_jsonl_sink_rotation_is_bounded_and_records_remain_valid(tmp_path):
 from ai_foundation.observability import TraceEvent,read_jsonl_trace
 p=tmp_path/'trace.jsonl';sink=JsonlTraceSink(p,max_bytes=1024,backups=2)
 for i in range(80):sink.emit(TraceEvent(str(i),'s','','x',i,i+1,'OK',{'step':'x'},()))
 files=sorted(tmp_path.glob('trace.jsonl*'))
 assert [x.name for x in files]==['trace.jsonl','trace.jsonl.1','trace.jsonl.2']
 assert all(x.stat().st_size < 1300 for x in files)
 assert all(read_jsonl_trace(x) for x in files)

def test_jsonl_rotation_drops_oldest_generation(tmp_path):
 from ai_foundation.observability import TraceEvent,read_jsonl_trace
 p=tmp_path/'trace.jsonl';sink=JsonlTraceSink(p,max_bytes=1024,backups=1)
 for i in range(100):sink.emit(TraceEvent(str(i),'s','','x',i,i+1,'OK',{},()))
 assert len(list(tmp_path.glob('trace.jsonl*')))==2
 current=read_jsonl_trace(p);previous=read_jsonl_trace(str(p)+'.1')
 assert int(current[-1].trace_id)==99 and int(previous[-1].trace_id)<99

def test_safe_trace_metadata_allows_route_identity_but_not_payload_or_secret():
 from ai_foundation.observability import safe_attributes
 row=safe_attributes({'run_id':'r','capability':'SEARCH','route_binding':'llm:x','route_kind':'CLOUD','provider':'GROQ','secret':'NO','text':'NO'})
 assert row=={'run_id':'r','capability':'SEARCH','route_binding':'llm:x','route_kind':'CLOUD','provider':'GROQ'}
