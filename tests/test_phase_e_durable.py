import pytest
from ai_foundation.observability import JsonlTraceSink, Tracer, read_jsonl_trace
from ai_foundation.run_report import build_run_report

def test_jsonl_survives_reopen_and_builds_same_report(tmp_path):
    p=tmp_path/'trace.jsonl'
    with Tracer(JsonlTraceSink(p)).span('first',evidence_ids=('effect:e',)): pass
    with Tracer(JsonlTraceSink(p)).span('second',evidence_ids=('readback:e',)): pass
    events=read_jsonl_trace(p)
    assert len(events)==2
    # Independent top-level spans are intentionally separate traces.
    with pytest.raises(ValueError): build_run_report(events)
    assert build_run_report((events[0],)).evidence_ids==('effect:e',)

def test_corrupt_or_schema_drifted_trace_fails_closed(tmp_path):
    p=tmp_path/'bad.jsonl'; p.write_text('{broken\n',encoding='utf-8')
    with pytest.raises(ValueError,match='corrupt trace record'): read_jsonl_trace(p)
    p.write_text('{"trace_id":"x"}\n',encoding='utf-8')
    with pytest.raises(ValueError,match='invalid trace schema'): read_jsonl_trace(p)
