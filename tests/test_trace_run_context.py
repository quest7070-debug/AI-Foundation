from ai_foundation.observability import InMemoryTraceSink,Tracer,trace_run

def test_trace_run_adds_existing_host_run_id_without_overriding_explicit_span_value():
 sink=InMemoryTraceSink(); tracer=Tracer(sink)
 with trace_run('chat-canonical'):
  with tracer.span('agent.model_call',{'capability':'CHAT'}): pass
  with tracer.span('capability.execute',{'run_id':'tool-owned','capability':'SEARCH'}): pass
 assert sink.events[0].attributes=={'capability':'CHAT','correlation_id':'chat-canonical'}
 assert sink.events[1].attributes=={'run_id':'tool-owned','capability':'SEARCH','correlation_id':'chat-canonical'}

def test_trace_run_is_context_scoped_and_does_not_leak_between_requests():
 sink=InMemoryTraceSink(); tracer=Tracer(sink)
 with trace_run('chat-one'):
  with tracer.span('inside'): pass
 with tracer.span('outside'): pass
 with trace_run('chat-two'):
  with tracer.span('inside-two'): pass
 assert sink.events[0].attributes['correlation_id']=='chat-one'
 assert 'correlation_id' not in sink.events[1].attributes
 assert sink.events[2].attributes['correlation_id']=='chat-two'
