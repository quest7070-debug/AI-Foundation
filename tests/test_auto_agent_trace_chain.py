from pydantic_ai.models.test import TestModel

from ai_foundation.auto_agent import AutoCapabilityAgent
from ai_foundation.capability_request import CapabilityRequest
from ai_foundation.observability import InMemoryTraceSink, Tracer


class _Executor:
    def __init__(self, tracer):
        self.tracer = tracer
        self.calls = []

    def execute(self, request, payload, run_id):
        self.calls.append((request.capability, run_id))
        with self.tracer.span(
            "capability.execute",
            {"run_id": run_id, "capability": request.capability},
        ):
            return "observed-search-result"


class _Temporal:
    def search_context(self):
        return "Current date: test"


def test_auto_agent_correlates_chat_request_and_tool_execution_under_host_run():
    sink = InMemoryTraceSink()
    tracer = Tracer(sink)
    executor = _Executor(tracer)

    agent = AutoCapabilityAgent(
        TestModel(call_tools=["search"]),
        executor,
        CapabilityRequest(capability="CHAT"),
        search_available=True,
        run_id="host-chat-run",
        temporal_context_factory=lambda: _Temporal(),
    )

    assert agent.run("search for the current fact")
    assert executor.calls == [("SEARCH", "auto-tool-1")]

    tool = next(
        event for event in sink.events
        if event.name == "capability.execute"
    )

    assert tool.attributes == {
        "run_id": "auto-tool-1",
        "capability": "SEARCH",
        "correlation_id": "host-chat-run",
    }
