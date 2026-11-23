import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.messages import ModelResponse,ToolCallPart,ToolReturnPart,TextPart
from ai_foundation.auto_agent import AutoCapabilityAgent
from ai_foundation.capability_request import CapabilityRequest
from ai_foundation.human_model_runtime import attach_context


class ProjectContext:
    owner_id='owner';local_required=False;scopes=('project',);search_available=False
    def read(self,owner,scope,offset=0):
        assert owner=='owner' and scope=='project'
        return json.dumps({'status':'AVAILABLE','scope':'project',
                           'records':[{'id':'evidence-1','content':'Project context.'}]})


def test_existing_agent_model_and_tools_gain_owner_context_without_replacement(tmp_path):
    model_calls=[]
    def model(messages,info):
        model_calls.append(tuple(t.name for t in info.function_tools))
        if any(isinstance(p,ToolReturnPart) for m in messages for p in m.parts):
            return ModelResponse(parts=[TextPart('Cited evidence-1.')])
        return ModelResponse(parts=[ToolCallPart('human_model_context',{'scope':'project'})])
    selected=FunctionModel(model);request=CapabilityRequest(owner_id='owner')
    agent=AutoCapabilityAgent(selected,SimpleNamespace(),request,search_available=True)
    original_port=agent.port
    attach_context(agent,ProjectContext(),request,selected,run_id='request-1',audit_path=tmp_path/'audit.jsonl')
    assert agent.port is original_port
    assert agent.run('Read the recorded project context.')=='Cited evidence-1.'
    assert all('search' in names and 'human_model_context' in names for names in model_calls)
    proof=json.loads((tmp_path/'audit.jsonl').read_text())
    assert proof['evidence_ids']==['evidence-1'] and proof['status']=='AVAILABLE'
    assert 'Project context.' not in (tmp_path/'audit.jsonl').read_text()


def test_context_cannot_be_attached_to_another_owner_or_cloud_private_model(tmp_path):
    model=FunctionModel(lambda *args:None)
    context=ProjectContext()
    with pytest.raises(PermissionError):
        attach_context(None,context,CapabilityRequest(owner_id='other'),model,
                       run_id='1',audit_path=tmp_path/'audit')
    context.local_required=True
    with pytest.raises(PermissionError):
        attach_context(None,context,CapabilityRequest(owner_id='owner'),model,
                       run_id='1',audit_path=tmp_path/'audit')


def test_an_unbound_owner_keeps_the_original_agent():
    sentinel=object()
    assert attach_context(sentinel,None,None,None,run_id='1',audit_path='unused') is sentinel


def test_wrapped_agent_keeps_output_and_progress_never_contains_prompt_or_locals(tmp_path,monkeypatch):
    from ai_foundation import auto_agent
    import ai_foundation.human_model_runtime as runtime
    original=auto_agent.AutoCapabilityAgent
    monkeypatch.setattr(auto_agent,'AutoCapabilityAgent',original)
    monkeypatch.setattr(runtime,'build_human_model_context',lambda *args,**kwargs:ProjectContext())
    factory=runtime.install_legacy_agent_factory(binding_path='unused',repository_root='unused',
        audit_path=tmp_path/'audit.jsonl')
    model=FunctionModel(lambda *args:ModelResponse(parts=[TextPart('Original output.')]))
    agent=factory(model,SimpleNamespace(guard=object()),CapabilityRequest(owner_id='owner'),run_id='safe-run')
    sensitive_input='secret-owner-input-must-never-enter-diagnostics'
    assert agent.run(sensitive_input)=='Original output.'
    progress=tmp_path/'agent-progress.jsonl'
    runtime._runtime_note(progress,'pending_after_60s','safe-run',capture=True)
    text=progress.read_text()
    events=[json.loads(line) for line in text.splitlines()]
    assert [event['event'] for event in events[:5]]==[
        'factory_enter','context_bound','factory_ready','run_enter','run_exit']
    assert sensitive_input not in text and 'Original output.' not in text
    frames=events[-1]['frames']
    assert frames and all(set(frame)=={'module','line','function'} for thread in frames for frame in thread)
    assert all('/' not in frame['module'] for thread in frames for frame in thread)
