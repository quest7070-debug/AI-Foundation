import pytest
from ai_foundation.evaluation import EvalResult
from ai_foundation.observability import InMemoryTraceSink, Tracer
from ai_foundation.run_report import build_run_report

def test_report_links_trace_and_eval_evidence():
    sink=InMemoryTraceSink(); t=Tracer(sink)
    with t.span('root',evidence_ids=('effect:e',)):
        with t.span('verify',evidence_ids=('readback:e',)): pass
    report=build_run_report(sink.events,(EvalResult('verified',True,('contract:c',)),))
    assert report.passed and report.span_count==2 and report.error_spans==0
    assert report.evidence_ids==('readback:e','effect:e','contract:c')

def test_report_fails_on_error_or_failed_eval():
    sink=InMemoryTraceSink(); t=Tracer(sink)
    try:
        with t.span('bad'): raise RuntimeError('x')
    except RuntimeError: pass
    assert not build_run_report(sink.events).passed
    sink2=InMemoryTraceSink()
    with Tracer(sink2).span('ok'): pass
    assert not build_run_report(sink2.events,(EvalResult('gate',False,()),)).passed

def test_report_rejects_mixed_traces():
    a=InMemoryTraceSink(); b=InMemoryTraceSink()
    with Tracer(a).span('a'): pass
    with Tracer(b).span('b'): pass
    with pytest.raises(ValueError): build_run_report(a.events+b.events)
