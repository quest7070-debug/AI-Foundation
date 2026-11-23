"""Pydantic-AI model adapter backed by Foundation's canonical dynamic CHAT router.

Pydantic AI owns the agent/tool loop. Foundation retains provider/model selection,
health/quota state and credentials. No semantic capability classifier exists here.
"""
from __future__ import annotations
import json,secrets,time
from .sensitive_input_scan import contains_sensitive_value
from pydantic_ai.messages import ModelRequest,ModelResponse,TextPart,ToolCallPart,UserPromptPart,SystemPromptPart,ToolReturnPart,RetryPromptPart
from pydantic_ai.models.function import FunctionModel

class AgentRouteUnavailable(RuntimeError):
    """Safe terminal failure metadata; never retains provider exception/content."""
    def __init__(self, phase, reason_code, attempts):
        self.phase = phase
        self.reason_code = reason_code
        self.attempts = attempts
        super().__init__("no eligible agent compute")


def _model_failure_code(exc):
    """Fixed diagnostic vocabulary only; no provider body or exception text."""
    from urllib.error import URLError
    if isinstance(exc, TimeoutError):
        return "MODEL_TIMEOUT"
    status = getattr(exc, "status", None)
    if type(status) is not int:
        status = getattr(exc, "code", None)
    if type(status) is int and 400 <= status < 500:
        return "MODEL_HTTP_4XX"
    if type(status) is int and 500 <= status < 600:
        return "MODEL_HTTP_5XX"
    if isinstance(exc, PermissionError):
        return "MODEL_POLICY_DENIED"
    if isinstance(exc, (KeyError, IndexError, TypeError, ValueError)):
        return "MODEL_RESPONSE_INVALID"
    if isinstance(exc, (OSError, URLError)):
        return "MODEL_TRANSPORT"
    return "MODEL_EXECUTION"


def _text(content):
    if isinstance(content,str): return content
    if isinstance(content,(list,tuple)): return "".join(str(getattr(x,"text",x)) for x in content)
    return str(content)

def _messages(messages,instructions=""):
    out=[]
    if instructions: out.append({"role":"system","content":instructions})
    for m in messages:
        if isinstance(m,ModelRequest):
            if m.instructions: out.append({"role":"system","content":m.instructions})
            for part in m.parts:
                if isinstance(part,SystemPromptPart): out.append({"role":"system","content":part.content})
                elif isinstance(part,UserPromptPart): out.append({"role":"user","content":_text(part.content)})
                elif isinstance(part,ToolReturnPart): out.append({"role":"tool","tool_call_id":part.tool_call_id,"content":_text(part.content)})
                elif isinstance(part,RetryPromptPart): out.append({"role":"user","content":_text(part.content)})
        elif isinstance(m,ModelResponse):
            texts=[]; calls=[]
            for part in m.parts:
                if isinstance(part,TextPart): texts.append(part.content)
                elif isinstance(part,ToolCallPart): calls.append({"id":part.tool_call_id,"type":"function","function":{"name":part.tool_name,"arguments":part.args_as_json_str()}})
            row={"role":"assistant","content":"\n\n".join(texts) or None}
            if calls: row["tool_calls"]=calls
            out.append(row)
    return out

def _choose_route(router,attempted,*,local_required=False):
    """Delegate model selection to the canonical CHAT router.

    Agent phase is observability only. A tool follow-up is still CHAT and must not
    acquire a second execution-selection policy inside the model adapter.
    """
    if local_required:
        return router.choose("CHAT",local_required=True,exclude=attempted)
    return router.choose("CHAT",exclude=attempted)

def foundation_agent_model(router,cloud_factory,local_execution,tracer=None,*,local_required=False):
    if type(local_required) is not bool: raise ValueError("host local-only policy required")
    def request(messages,info):
        attempted=set(); fallback_reason=""; last_failure="NO_ELIGIBLE_ROUTE"
        phase="tool_followup" if any(isinstance(part,ToolReturnPart) for m in messages if isinstance(m,ModelRequest) for part in m.parts) else "initial"
        tools=[{"type":"function","function":{"name":t.name,"description":t.description or "","parameters":t.parameters_json_schema}} for t in info.function_tools]
        instructions=getattr(info,"instructions","") or ""
        payload={"messages":_messages(messages,instructions)}
        # Tool-return content bypasses the ordinary TaskPlan Guard route.
        # Reuse its bounded structural detector before every provider send.
        payload_local_only = local_required or any(
            contains_sensitive_value(row["content"])
            for row in payload["messages"] if isinstance(row.get("content"), str)
        )
        # Pydantic AI owns semantic tool scheduling. A ToolReturnPart means this is
        # a provider-neutral follow-up turn, not necessarily final synthesis. Keep
        # exactly the tools Pydantic AI says are available so multi-step tool use
        # remains possible without Foundation interpreting the user's semantics.
        if tools: payload.update({"tools":tools,"tool_choice":"auto"})
        preferred=None
        while True:
            route=preferred or _choose_route(router,attempted,local_required=payload_local_only)
            preferred=None
            if not route.binding: raise AgentRouteUnavailable(phase, last_failure, len(attempted))
            if payload_local_only and route.kind != "LOCAL":
                raise PermissionError("sensitive agent payload local-only route required")
            attempted.add(route.binding)
            started=time.perf_counter(); attempt=len(attempted)
            meta=router.settings.registry.credential(route.binding) if getattr(router,"settings",None) and route.kind!="LOCAL" else None
            provider=(meta or {}).get("provider") or route.kind
            attrs={"capability":"CHAT","phase":phase,"attempt":attempt,"route_binding":route.binding,"route_kind":route.kind,"provider":provider,"timeout":"false","tool_count":str(len(tools)),"tool_names":",".join(sorted(str(t["function"]["name"]) for t in tools))}
            if fallback_reason: attrs["fallback_reason"]=fallback_reason
            try:
                from contextlib import nullcontext
                from .observability import safe_attributes
                trace_attrs=safe_attributes(attrs)
                scope=tracer.span("agent.model_call",trace_attrs) if tracer else nullcontext()
                with scope:
                    if route.kind=="LOCAL":
                        execution=local_execution.for_binding(route.binding) if hasattr(local_execution,"for_binding") else local_execution
                        if not hasattr(execution,"chat_payload"): raise RuntimeError("local tool calling unavailable")
                        data=execution.chat_payload(payload,model=route.execution_slot or route.model)
                    else:
                        raw=cloud_factory(route.binding).invoke_for_function(route.binding,payload,"CHAT"); data=json.loads(raw)
                msg=data["choices"][0]["message"]; parts=[]
                calls=msg.get("tool_calls") or ()
                # Pydantic AI owns structured agent/tool history. Foundation serializes
                # that history uniformly and must not reconstruct, summarize, or interpret
                # it when execution falls back between replaceable model providers.
                if tracer:
                    from .observability import safe_attributes
                    shape={"capability":"CHAT","phase":phase,"route_binding":route.binding,"provider":provider,"has_text":str(bool(msg.get("content"))).lower(),"tool_call_count":str(len(calls)),"finish_reason":str(data["choices"][0].get("finish_reason") or "")}
                    with tracer.span("agent.response_shape",safe_attributes(shape)): pass
                if msg.get("content"): parts.append(TextPart(msg["content"]))
                # Do not reinterpret provider output from Agent phase/history here.
                # Pydantic AI owns whether a tool call is valid for the tools it exposed.
                for call in calls:
                    if call.get("type")=="function":
                        fn=call["function"]; parts.append(ToolCallPart(fn["name"],fn.get("arguments","{}"),tool_call_id=call.get("id") or "call_"+secrets.token_hex(8)))
                if parts:
                    if hasattr(router,'record_runtime'):router.record_runtime('CHAT',route.binding,True,(time.perf_counter()-started)*1000)
                    if hasattr(router,'record_phase_runtime'):router.record_phase_runtime('CHAT',phase,route.binding,True,(time.perf_counter()-started)*1000)
                    return ModelResponse(parts=parts,model_name=str(data.get("model") or route.binding))
                raise ValueError("provider response missing content/tool call")
            except Exception as exc:
                if hasattr(router,'record_runtime'):router.record_runtime('CHAT',route.binding,False,(time.perf_counter()-started)*1000)
                if hasattr(router,'record_phase_runtime'):router.record_phase_runtime('CHAT',phase,route.binding,False,(time.perf_counter()-started)*1000)
                # Keep only a fixed failure category after an actual model attempt.
                # The next agent never receives a secret-bearing SDK exception.
                fallback_reason = _model_failure_code(exc)
                last_failure = fallback_reason
                # A synthetic one-token probe does not prove that a route can execute
                # this real request (its payload, tools and follow-up phase differ).
                # Let the canonical router choose the next eligible route from actual
                # runtime/health/quota evidence; never promote a route from a toy probe.
                continue
    model=FunctionModel(request,model_name="foundation-routed-chat")
    model.foundation_local_only=local_required
    return model

