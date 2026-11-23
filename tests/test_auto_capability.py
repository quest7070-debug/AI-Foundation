from pydantic_ai.models.test import TestModel
from ai_foundation.auto_agent import AutoCapabilityAgent
from ai_foundation.capability_request import CapabilityRequest

class Exec:
 def __init__(self):self.calls=[]
 def execute(self,request,text,run_id):
  self.calls.append((request,text,run_id));return 'tool-result'

def test_auto_agent_uses_pydantic_tool_selection_not_custom_classifier():
 e=Exec(); a=AutoCapabilityAgent(TestModel(call_tools=['search']),e,CapabilityRequest('CHAT',owner_id='u'),search_available=True)
 assert a.run('current weather')
 assert [x[0].capability for x in e.calls]==['SEARCH']

def test_auto_agent_exposes_only_host_granted_tools():
 e=Exec(); a=AutoCapabilityAgent(TestModel(call_tools=[]),e,CapabilityRequest('CHAT',owner_id='u'),search_available=True)
 names={t.name for t in a.port.agent._function_toolset.tools.values()}
 assert names=={'search'}
 req=CapabilityRequest('CHAT',owner_id='u',repo_root='/repo',file_read_root='/files',data_operation='json_summary')
 b=AutoCapabilityAgent(TestModel(call_tools=[]),e,req,search_available=True)
 names={t.name for t in b.port.agent._function_toolset.tools.values()}
 assert names=={'search','data','code','files','list_files'}

def test_auto_agent_reuses_host_scope_and_cannot_mint_it():
 e=Exec(); req=CapabilityRequest('CHAT',owner_id='u',file_read_root='/trusted')
 a=AutoCapabilityAgent(TestModel(call_tools=['files']),e,req,search_available=False)
 a.run('read note.txt')
 assert e.calls[0][0].capability=='FILES' and e.calls[0][0].file_read_root=='/trusted'


def test_auto_agent_executes_multiple_model_tool_calls_sequentially():
 import threading,time
 class ParallelModel:
  pass
 from pydantic_ai.models.test import TestModel
 class SlowExec(Exec):
  def __init__(self): super().__init__(); self.active=0; self.max_active=0; self.lock=threading.Lock()
  def execute(self,request,text,run_id):
   with self.lock:self.active+=1;self.max_active=max(self.max_active,self.active)
   time.sleep(.02)
   with self.lock:self.active-=1
   self.calls.append((request,text,run_id))
   return 'tool-result'
 e=SlowExec(); a=AutoCapabilityAgent(TestModel(call_tools=['search','search']),e,CapabilityRequest('CHAT',owner_id='u'),search_available=True)
 assert a.run('compare two current facts')
 assert len(e.calls)==2
 assert e.max_active==1


def test_auto_code_change_reuses_host_repo_scope():
 import json
 e=Exec()
 req=CapabilityRequest('CHAT',owner_id='u',repo_root='/trusted/repo')
 a=AutoCapabilityAgent(TestModel(call_tools=[]),e,req,search_available=False)
 a.code('a.py','change','print(1)')
 call=e.calls[0]
 assert call[0].capability=='CODE'
 assert call[0].repo_root=='/trusted/repo'
 payload=json.loads(call[1])
 assert payload=={'operation':'change','target':'a.py','content':'print(1)'}
 assert 'repo_root' not in payload


def test_auto_agent_exposes_files_for_verified_attachment_without_root(tmp_path):
    from ai_foundation.capability_request import AttachmentGrant

    p=tmp_path/'note.txt'
    p.write_text('ATTACHMENT_AGENT_CONTENT')
    grant=AttachmentGrant('f1','u',str(p.resolve()))
    req=CapabilityRequest('CHAT',owner_id='u',attachments=(grant,),attachment_ids=('f1',))

    class AttachmentExec:
        def __init__(self):
            self.calls=[]
        def execute(self,request,text,run_id):
            self.calls.append((request,text,run_id))
            assert request.capability=='FILES'
            assert request.file_read_root==''
            assert request.attachments==(grant,)
            return open(request.attachments[0].path,encoding='utf-8').read()

    e=AttachmentExec()
    a=AutoCapabilityAgent(TestModel(call_tools=['files']),e,req)
    out=a.run('このファイルを読んで')

    assert 'ATTACHMENT_AGENT_CONTENT' in out
    assert len(e.calls)==1


def test_auto_compute_reuses_host_profile_and_exposes_no_connection_authority():
 import json
 e=Exec(); req=CapabilityRequest('CHAT',owner_id='u',compute_profile='compute-main')
 a=AutoCapabilityAgent(TestModel(call_tools=[]),e,req,search_available=False)
 names={t.name for t in a.port.agent._function_toolset.tools.values()}
 assert names=={'compute'}
 a.compute('print(1)',2)
 call=e.calls[0]
 assert call[0].capability=='COMPUTE' and call[0].compute_profile=='compute-main'
 assert json.loads(call[1])=={'tool':'execute_code','args':{'code':'print(1)','timeout':2}}
 assert 'compute_profile' not in json.loads(call[1])


def test_auto_agent_repository_and_file_area_tool_semantics_are_distinct(monkeypatch):
    import pydantic_ai
    from ai_foundation.auto_agent import AutoCapabilityAgent

    seen = {}
    real_agent = pydantic_ai.Agent

    def capture_agent(*args, **kwargs):
        seen["instructions"] = kwargs.get("instructions", "")
        return real_agent(*args, **kwargs)

    monkeypatch.setattr(pydantic_ai, "Agent", capture_agent)

    contract = AutoCapabilityAgent.TOOL_SELECTION_CONTRACT
    assert "Repository files, including repository documentation and configuration, belong to code inspect; do not use files for repository paths." in contract
    assert "Files is for the separately authorized general file area or verified attachments, not the repository." in contract

    e = Exec()
    req = CapabilityRequest(
        "CHAT",
        owner_id="u",
        repo_root="/trusted/repo",
        file_read_root="/trusted/files",
    )
    AutoCapabilityAgent(
        TestModel(call_tools=[]),
        e,
        req,
        search_available=False,
    )

    assert contract in seen["instructions"]


def test_auto_agent_structured_data_analysis_uses_bounded_data_semantics(monkeypatch):
    import pydantic_ai
    from ai_foundation.auto_agent import AutoCapabilityAgent

    seen = {}
    real_agent = pydantic_ai.Agent

    def capture_agent(*args, **kwargs):
        seen["instructions"] = kwargs.get("instructions", "")
        return real_agent(*args, **kwargs)

    monkeypatch.setattr(pydantic_ai, "Agent", capture_agent)

    contract = AutoCapabilityAgent.TOOL_SELECTION_CONTRACT
    normalized = contract.lower()

    assert "structured data" in normalized
    assert "data tool" in normalized
    assert "model" in normalized
    assert "compute" in normalized or "calculate" in normalized

    e = Exec()
    req = CapabilityRequest(
        "CHAT",
        owner_id="u",
        data_operation="json_summary",
    )
    AutoCapabilityAgent(
        TestModel(call_tools=[]),
        e,
        req,
        search_available=False,
    )

    assert contract in seen["instructions"]

def test_auto_agent_json_summary_exposes_structured_json_tool_and_serializes_before_execution():
    import json
    from pydantic import JsonValue

    e = Exec()
    req = CapabilityRequest(
        "CHAT",
        owner_id="u",
        data_operation="json_summary",
    )
    a = AutoCapabilityAgent(TestModel(call_tools=[]), e, req, search_available=False)

    tool = a.port.agent._function_toolset.tools["data"]
    schema = tool.function_schema.json_schema
    assert "value" in schema["properties"]
    assert schema["properties"]["value"].get("type") != "string"
    assert "payload" not in schema["properties"]

    a.data_json([10, 20, 30, 40])

    request, payload, run_id = e.calls[0]
    assert request.capability == "DATA"
    assert request.data_operation == "json_summary"
    assert json.loads(payload) == [10, 20, 30, 40]
    assert run_id == "auto-tool-1"


def test_auto_agent_data_preserves_csv_payload_for_csv_summary():
    from ai_foundation.auto_agent import AutoCapabilityAgent
    from ai_foundation.capability_request import CapabilityRequest

    class Executor:
        def __init__(self):
            self.calls = []

        def execute(self, request, text, run_id):
            self.calls.append((request, text, run_id))
            return "ok"

    executor = Executor()
    agent = object.__new__(AutoCapabilityAgent)
    agent.executor = executor
    agent.request = CapabilityRequest(
        "CHAT",
        owner_id="u",
        data_operation="csv_summary",
    )
    agent.run_id = "r"
    agent._seq = 0

    csv_payload = "a,b\n1,2\n3,4\n"
    assert agent.data(csv_payload) == "ok"

    request, payload, run_id = executor.calls[0]
    assert request.capability == "DATA"
    assert request.data_operation == "csv_summary"
    assert payload == csv_payload
    assert run_id == "auto-tool-1"

def test_auto_agent_passes_structured_conversation_history_to_port():
    from pydantic_ai.messages import ModelRequest, ModelResponse, UserPromptPart, TextPart

    e = Exec()
    a = AutoCapabilityAgent(
        TestModel(call_tools=[]),
        e,
        CapabilityRequest('CHAT', owner_id='u'),
        search_available=False,
    )

    seen = []
    real_run = a.port.run

    def capture(request):
        seen.append(request)
        return real_run(request)

    a.port.run = capture

    history = (
        ModelRequest(parts=[UserPromptPart('remember KITE-7391')]),
        ModelResponse(parts=[TextPart('understood')]),
    )

    a.run('what was the code?', message_history=history)

    assert len(seen) == 1
    assert seen[0].message_history == history
    assert '[User request]\nwhat was the code?' in seen[0].instruction
    assert 'remember KITE-7391' not in seen[0].instruction


def test_auto_agent_exposes_vision_only_from_host_authorized_attachment(tmp_path):
    from ai_foundation.capability_request import AttachmentGrant

    p = tmp_path / "image.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    grant = AttachmentGrant("vision-1", "u", str(p.resolve()))

    e = Exec()
    req = CapabilityRequest(
        "CHAT",
        owner_id="u",
        attachments=(grant,),
        attachment_ids=("vision-1",),
    )

    a = AutoCapabilityAgent(
        TestModel(call_tools=[]),
        e,
        req,
        search_available=False,
    )

    names = set(a.port.agent._function_toolset.tools)
    assert "vision" in names

    a.vision("describe the image")

    request, payload, run_id = e.calls[-1]
    assert request.capability == "VISION"
    assert request.owner_id == "u"
    assert request.attachments == (grant,)
    assert request.attachment_ids == ("vision-1",)
    assert payload == "describe the image"
    assert run_id == "auto-tool-1"


def test_auto_agent_does_not_expose_vision_without_attachment_authority():
    e = Exec()

    a = AutoCapabilityAgent(
        TestModel(call_tools=[]),
        e,
        CapabilityRequest("CHAT", owner_id="u"),
        search_available=False,
    )

    names = set(a.port.agent._function_toolset.tools)
    assert "vision" not in names


def test_auto_agent_can_semantically_select_vision_for_authorized_attachment(tmp_path):
    from ai_foundation.capability_request import AttachmentGrant

    p = tmp_path / "image.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    grant = AttachmentGrant("vision-1", "u", str(p.resolve()))

    e = Exec()
    req = CapabilityRequest(
        "CHAT",
        owner_id="u",
        attachments=(grant,),
        attachment_ids=("vision-1",),
    )

    a = AutoCapabilityAgent(
        TestModel(call_tools=["vision"]),
        e,
        req,
        search_available=False,
    )

    assert a.run("この画像を見て説明して")

    assert len(e.calls) == 1
    request, _, _ = e.calls[0]
    assert request.capability == "VISION"
    assert request.owner_id == "u"
    assert request.attachments == (grant,)
    assert request.attachment_ids == ("vision-1",)


def test_auto_agent_files_then_data_keeps_authority_scoped_to_tools_and_objective(tmp_path, monkeypatch):
    import ast
    import json
    from pathlib import Path
    from pydantic_ai import models
    from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
    from pydantic_ai.models.function import FunctionModel
    from ai_foundation.capability_execution import CapabilityExecutor

    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)
    values = [3, 7, 11]
    source = tmp_path / "values.json"
    source.write_text(json.dumps(values), encoding="utf-8")
    calls = []
    history = []

    class FilePort:
        def observe(self, plan):
            assert plan.target == str(source.resolve())
            return Path(plan.target).read_text(encoding="utf-8")

    class RecordingExecutor(CapabilityExecutor):
        def execute(self, request, text, run_id):
            calls.append((request, text, run_id))
            return super().execute(request, text, run_id)

    def choose_tool(messages, info):
        assert {
            tool.name: set(tool.parameters_json_schema["properties"])
            for tool in info.function_tools
        } == {"files": {"target"}, "list_files": {"target"}, "data": {"value"}}
        returned = [
            part
            for message in messages if isinstance(message, ModelRequest)
            for part in message.parts if isinstance(part, ToolReturnPart)
        ]
        if not returned:
            return ModelResponse(parts=[ToolCallPart("files", {"target": source.name})])
        if len(returned) == 1:
            assert returned[0].tool_name == "files"
            return ModelResponse(parts=[
                ToolCallPart("data", {"value": json.loads(returned[0].content)})
            ])
        assert [part.tool_name for part in returned] == ["files", "data"]
        response = ModelResponse(parts=[TextPart(returned[-1].content)])
        history[:] = [*messages, response]
        return response

    executor = RecordingExecutor(inference=None, guard=None, file_port=FilePort())
    agent = AutoCapabilityAgent(
        FunctionModel(choose_tool),
        executor,
        CapabilityRequest(
            "CHAT",
            owner_id="u",
            file_read_root=str(tmp_path),
            data_operation="json_summary",
        ),
        search_available=False,
    )

    output = agent.run("Summarize the numbers in values.json.")

    assert ast.literal_eval(output) == {
        "type": "array", "count": 3, "numeric_count": 3,
        "min": 3.0, "max": 11.0, "mean": 7.0,
    }
    assert calls == [
        (
            CapabilityRequest("FILES", owner_id="u", file_read_root=str(tmp_path)),
            "values.json",
            "auto-tool-1",
        ),
        (
            CapabilityRequest("DATA", owner_id="u", data_operation="json_summary"),
            json.dumps(values),
            "auto-tool-2",
        ),
    ]

    # Prior tool history and a shared executor cannot supply the next objective's grants.
    previous_calls = calls.copy()
    scope_free_model = TestModel(call_tools="all")
    scope_free_agent = AutoCapabilityAgent(
        scope_free_model,
        executor,
        CapabilityRequest("CHAT", owner_id="u"),
        search_available=False,
    )

    assert scope_free_agent.run(
        "Read values.json again and summarize its current numbers.",
        message_history=history,
    )
    assert scope_free_model.last_model_request_parameters.function_tools == []
    assert calls == previous_calls



def test_host_numeric_array_contract_requests_one_model_retry_before_data():
    import json
    import pytest
    from pydantic_ai import ModelRetry
    e = Exec()
    req = CapabilityRequest(
        "CHAT", owner_id="public-test", data_operation="json_summary",
        data_value_contract="numeric_array",
    )
    a = AutoCapabilityAgent(TestModel(call_tools=[]), e, req)
    with pytest.raises(ModelRetry, match="numeric JSON array"):
        a.data_json({"numbers": [3, 7, 11]})
    with pytest.raises(ModelRetry, match="numeric JSON array"):
        a.data_json("3,7,11")
    with pytest.raises(ModelRetry, match="numeric JSON array"):
        a.data_json([3, True, 11])
    assert e.calls == []
    assert a.data_json([3, 7, 11]) == "tool-result"
    assert len(e.calls) == 1
    assert json.loads(e.calls[0][1]) == [3, 7, 11]
    assert e.calls[0][0].data_value_contract == "numeric_array"


def test_host_numeric_array_contract_is_not_model_mintable():
    import pytest
    for kwargs in [
        {"data_operation": "csv_summary", "data_value_contract": "numeric_array"},
        {"data_backend": "mcp", "data_value_contract": "numeric_array"},
        {"data_value_contract": "numeric_array"},
        {"data_operation": "json_summary", "data_value_contract": "untrusted"},
    ]:
        with pytest.raises(ValueError):
            CapabilityRequest("CHAT", **kwargs)
    # The default generic JSON summarizer keeps its existing object support.
    req = CapabilityRequest("CHAT", data_operation="json_summary")
    assert req.data_value_contract == "any"



def test_host_array_tool_schema_is_concrete_for_local_llms():
    from pydantic_ai.messages import ModelResponse, TextPart
    from pydantic_ai.models.function import FunctionModel
    from pydantic_ai import ModelRetry
    import pytest
    observed = []
    def inspect_schema(messages, info):
        tools = [t for t in info.function_tools if t.name == "data"]
        assert len(tools) == 1
        schema = tools[0].parameters_json_schema
        observed.append(schema)
        assert schema["properties"]["value"]["type"] == "array"
        assert schema["properties"]["value"]["items"]["type"] == "number"
        return ModelResponse(parts=[TextPart("schema-verified")])
    e = Exec()
    req = CapabilityRequest("CHAT", owner_id="public-test",
                             data_operation="json_summary",
                             data_value_contract="numeric_array")
    a = AutoCapabilityAgent(FunctionModel(inspect_schema), e, req)
    assert "schema-verified" in a.run("Inspect the fixed tool shape")
    assert len(observed) == 1
    with pytest.raises(ModelRetry):
        a.data_numeric_array({"numbers": [3, 7, 11]})
    assert not e.calls
    assert a.data_numeric_array([3.0, 7.0, 11.0]) == "tool-result"
    assert e.calls[0][0].data_value_contract == "numeric_array"
