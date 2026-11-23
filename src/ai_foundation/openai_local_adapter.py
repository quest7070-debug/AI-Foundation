"""Host-owned OpenAI-compatible local-compute endpoint adapter.

This is transport/discovery only. Endpoint configuration grants no model role or
capability; those remain explicit host policy.
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from urllib import request
from urllib.error import HTTPError
from urllib.parse import urlparse
from .local_compute_registry import LocalComputeCandidate


def _validated_base_url(base_url: str, allowed_hosts: tuple[str, ...]) -> str:
    u=urlparse(base_url)
    if u.scheme!='http' or not u.hostname or u.username or u.password or u.query or u.fragment:
        raise ValueError('local endpoint must be an explicit http authority')
    allowed={x.strip().lower() for x in allowed_hosts if x.strip()}
    if u.hostname.lower() not in allowed:
        raise ValueError('local endpoint host is not host-authorized')
    return base_url.rstrip('/')

def _authorization_header(api_key):
    if api_key is None:return {}
    return {'Authorization':f'Bearer {api_key}'}

@dataclass(frozen=True)
class OpenAILocalModelPolicy:
    runtime_model: str
    alias: str
    capabilities: tuple[str,...]=('CHAT',)
    roles: tuple[str,...]=('CHAT',)
    characteristics: tuple[str,...]=()

class OpenAILocalDiscovery:
    def __init__(self,base_url,*,binding_prefix,allowed_hosts,models,opener=None,timeout=2,max_bytes=262144,api_key=None):
        self.base=_validated_base_url(base_url,tuple(allowed_hosts)); self.prefix=binding_prefix.rstrip(':')
        self.models=tuple(models); self.open=opener or request.build_opener(request.ProxyHandler({})).open; self.timeout=timeout; self.max=max_bytes
        self.api_key=api_key
    def __call__(self):
        try:
            req=request.Request(self.base+'/v1/models',headers=_authorization_header(self.api_key))
            with self.open(req,timeout=self.timeout) as r:b=r.read(self.max+1)
            if len(b)>self.max:raise ValueError('local endpoint response too large')
            ids={x.get('id') for x in json.loads(b).get('data',[]) if isinstance(x,dict)}
        except Exception as exc:
            reason = ('HTTP_' + str(exc.code) if isinstance(exc, HTTPError)
                      and exc.code in (401, 403, 429, 500, 502, 503, 504)
                      else type(exc).__name__)
            return (LocalComputeCandidate(self.prefix,health='UNAVAILABLE',reason=reason,capabilities=()),)
        out=[]
        for p in self.models:
            if p.runtime_model not in ids:continue
            out.append(LocalComputeCandidate(f'{self.prefix}:{p.alias}',health='ONLINE',active=True,capabilities=tuple(p.capabilities),model=p.runtime_model,roles=tuple(p.roles),slot=p.alias,characteristics=tuple(p.characteristics),same_host=False))
        return tuple(out) or (LocalComputeCandidate(self.prefix,health='UNAVAILABLE',reason='NO_AUTHORIZED_MODEL',capabilities=()),)

class OpenAILocalExecution:
    def __init__(self,base_url,*,allowed_hosts,alias_to_model,opener=None,timeout=120,max_bytes=2*1024*1024,api_key=None,request_defaults=None):
        self.base=_validated_base_url(base_url,tuple(allowed_hosts)); self.models=dict(alias_to_model)
        self.open=opener or request.build_opener(request.ProxyHandler({})).open; self.timeout=timeout; self.max=max_bytes
        self.api_key=api_key; self.request_defaults=dict(request_defaults or {})
    def _model(self,model):
        if model not in self.models:raise ValueError('local model alias is not host-authorized')
        return self.models[model]
    def _apply_defaults(self,body):
        for k,v in self.request_defaults.items():
            if v is None:continue
            body.setdefault(k,v)
        return body
    def chat_payload(self,payload,model=None):
        selected=self._model(model); body=self._apply_defaults(dict(payload)); body['model']=selected; body['stream']=False
        headers={'Content-Type':'application/json',**_authorization_header(self.api_key)}
        req=request.Request(self.base+'/v1/chat/completions',data=json.dumps(body).encode(),headers=headers)
        with self.open(req,timeout=self.timeout) as r:b=r.read(self.max+1)
        if len(b)>self.max:raise ValueError('local endpoint response too large')
        return json.loads(b)
    def chat(self,prompt,model=None):
        alias=model; selected=self._model(alias)
        body=self._apply_defaults({'model':selected,'stream':False,'messages':[{'role':'system','content':f'You are a host-selected local model. Runtime alias: {alias}. Do not claim a different provider or model identity.'},{'role':'user','content':prompt}]})
        row=self.chat_payload(body,model=alias); return row['choices'][0]['message']['content']

class LocalExecutionDispatcher:
    """Mechanical binding-prefix dispatch after ComputeRouter has already selected authority."""
    def __init__(self,default,by_prefix=()):self.default=default;self.by_prefix=tuple(by_prefix)
    def for_binding(self,binding):
        if not isinstance(binding,str):
            return self.default
        for prefix,execution in self.by_prefix:
            if binding==prefix or binding.startswith(prefix+':'):return execution
        return self.default

