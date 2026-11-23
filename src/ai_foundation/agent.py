from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class AgentRequest:
    instruction: str
    message_history: tuple = ()

@dataclass(frozen=True)
class AgentResult:
    output: str

class AgentPort(Protocol):
    def run(self, request: AgentRequest) -> AgentResult: ...

class PydanticAgentPort:
    """Replaceable adapter. The agent proposes/returns work; Guard retains authority."""
    def __init__(self, agent, *, model=None, usage_limits=None):
        self.agent = agent
        self.model = model
        self.usage_limits = usage_limits

    def run(self, request: AgentRequest) -> AgentResult:
        kwargs = {} if self.model is None else {"model": self.model}
        if self.usage_limits is not None: kwargs["usage_limits"] = self.usage_limits
        if request.message_history:
            kwargs["message_history"] = request.message_history
        result = self.agent.run_sync(request.instruction, **kwargs)
        if result.output is None:
            raise ValueError("AGENT_OUTPUT_UNAVAILABLE")
        return AgentResult(str(result.output))

def scoped_pydantic_agent(model, tools, *, system_prompt='Use only the tools and scope provided by the host.'):
    """Production Agent factory. Authority stays in host-bound CapabilityAgentTools/Guard."""
    from pydantic_ai import Agent
    agent=Agent(model,system_prompt=system_prompt)
    agent.tool_plain(tools.read)
    agent.tool_plain(tools.write)
    return PydanticAgentPort(agent)
