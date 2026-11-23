from dataclasses import dataclass
from .core import TaskPlan
from .cloud_execution import ProviderHTTPError

class InferenceResultStore:
    def __init__(self):self._results={}
    def put(self,effect_id,value):self._results[effect_id]=value
    def get(self,effect_id):return self._results.get(effect_id)
    def take(self,effect_id):return self._results.pop(effect_id,None)

@dataclass
class LocalInferencePort:
    execution: object
    results: InferenceResultStore
    model: str|None = None
    def execute(self,plan:TaskPlan):
        # A TypeError raised *inside* the chat adapter may follow a real
        # inference dispatch. Do not catch it as an unsupported keyword and
        # accidentally send the same request twice.
        chat = self.execution.chat
        if self.model is None:
            value = chat(plan.text)
        else:
            from inspect import Parameter, signature
            try:
                parameters = signature(chat).parameters
            except (TypeError, ValueError):
                # Uninspectable callables still receive one attempt only.
                model_supported = True
            else:
                explicit = parameters.get("model")
                model_supported = (
                    explicit is not None and explicit.kind in (
                        Parameter.POSITIONAL_OR_KEYWORD, Parameter.KEYWORD_ONLY)
                    or any(p.kind is Parameter.VAR_KEYWORD
                           for p in parameters.values()))
            value = (chat(plan.text, model=self.model)
                     if model_supported else chat(plan.text))
        self.results.put(plan.effect_id or plan.run_id,value)
    def observe(self,plan:TaskPlan):return self.results.take(plan.effect_id or plan.run_id) or ''

@dataclass
class CloudInferencePort:
    execution: object
    binding: str
    results: InferenceResultStore
    function: str = 'CHAT'
    attempts: object = None
    def execute(self,plan:TaskPlan):
        request_id=plan.effect_id or plan.run_id
        if self.attempts is not None:
            prior=self.attempts.get_or_begin(request_id,self.binding)
            if prior.status=='VERIFIED':
                self.results.put(request_id,prior.result or ''); return
            if prior.status in {'DISPATCHING','UNCERTAIN'}:
                # Existing DISPATCHING means this process is a redelivery/restart and the
                # previous cloud request may already have reached the provider. Never resend.
                raise RuntimeError('inference completion uncertain; reconciliation required')
        payload={'messages':[{'role':'user','content':plan.text}]}
        if self.function.upper()=='SEARCH' and plan.privacy_text is not None: payload['search_query']=plan.privacy_text
        try:
            if hasattr(self.execution,'invoke_for_function'):
                raw=self.execution.invoke_for_function(self.binding,payload,self.function)
                raw=self.execution.extract_text(raw)
            else:
                raw=self.execution.invoke(self.binding,payload)
        except Exception as exc:
            if self.attempts is not None:
                # A provider HTTP response proves this dispatch completed with a definitive
                # failure. It is safe to select another binding. Transport loss remains
                # ambiguous because the provider may have accepted/charged the request.
                if isinstance(exc,ProviderHTTPError): self.attempts.failed(request_id)
                else: self.attempts.uncertain(request_id)
            raise
        if self.attempts is not None:self.attempts.complete(request_id,raw)
        self.results.put(request_id,raw)
    def observe(self,plan:TaskPlan):return self.results.take(plan.effect_id or plan.run_id) or ''
