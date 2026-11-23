from ai_foundation.observability import InMemoryTraceSink, ObservedCall, Tracer, safe_attributes

def test_safe_attributes_default_deny_secret_and_free_text():
    attrs=safe_attributes({'run_id':'r1','status':'ok','password':'NOPE','api_key':'NOPE','text':'private payload','unknown':'x'})
    assert attrs=={'run_id':'r1','status':'ok'}
    assert 'NOPE' not in repr(attrs) and 'private payload' not in repr(attrs)

def test_observed_call_preserves_result_and_safe_metadata():
    sink=InMemoryTraceSink(); tracer=Tracer(sink); calls=[]
    def work(x): calls.append(x); return x+1
    observed=ObservedCall(tracer,'guard.execute',work,{'run_id':'r','secret':'NOPE','decision':'ALLOW'},('effect:e',))
    assert observed(4)==5 and calls==[4]
    event=sink.events[0]
    assert event.attributes=={'run_id':'r','decision':'ALLOW'} and event.evidence_ids==('effect:e',)
    assert 'NOPE' not in repr(event)

def test_message_count_is_safe_structural_metadata_but_message_content_is_not():
    row = safe_attributes(
        {
            "message_count": 3,
            "message_roles": "user,assistant,user",
            "text": "SECRET",
            "content": "SECRET",
        }
    )
    assert row == {"message_count": "3"}
