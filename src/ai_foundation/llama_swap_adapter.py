import json
import re
from pathlib import Path
from urllib import request
from urllib.parse import urlparse
from contextlib import nullcontext
from .local_compute_registry import LocalComputeCandidate

class LlamaSwapDiscovery:
    def __init__(self,base_url='http://127.0.0.1:9292',opener=None,timeout=2,max_bytes=262144,role_policy=None,manifest_path=None,characteristic_policy=None):
        u=urlparse(base_url)
        if u.scheme!='http' or u.hostname not in {'127.0.0.1','localhost','::1'}: raise ValueError('llama-swap discovery must be loopback')
        self.base=base_url.rstrip('/');self.open=opener or request.urlopen;self.timeout=timeout;self.max=max_bytes
        # Role policy is host-owned. Model aliases returned by the runtime cannot
        # grant themselves CODE/REVIEW authority.
        self.manifest_path=Path(manifest_path) if manifest_path else None
        self.role_policy=role_policy or {
            'local-general': ('CHAT',),
            'local-code-agent': ('CODE',),
            # Review is intentionally a CODE-capable compute role; authority and
            # repository scope still come from the host capability envelope.
            'local-code-review': ('CODE', 'CODE_REVIEW'),
            'local-vision': ('VISION',),
        }
        self.characteristic_policy=characteristic_policy or {
            'local-general': ('GENERAL PURPOSE',),
            'local-code-agent': ('CODE GENERATION',),
            'local-code-review': ('CODE REVIEW',),
            'local-vision': ('IMAGE ANALYSIS',),
        }
    def _manifest_models(self):
        if self.manifest_path is None:return {}
        try:text=self.manifest_path.read_text()
        except OSError:return {}
        out={}
        current=None
        for line in text.splitlines():
            m=re.match(r'^  ([^ #][^:]*):\s*$',line)
            if m:current=m.group(1).strip();continue
            if current and '--model' in line:
                m=re.search(r'--model\s+["\']?([^"\'\s]+)',line)
                if not m:continue
                raw=m.group(1);repo=re.search(r'models--(.+?)(?:/blobs/|$)',raw)
                out[current]=(repo.group(1).replace('--','/') if repo else Path(raw).name)
        return out
    def __call__(self):
        try:
            with self.open(self.base+'/v1/models',timeout=self.timeout) as r:
                b=r.read(self.max+1)
            if len(b)>self.max: raise ValueError('llama-swap response too large')
            rows=json.loads(b).get('data',[])
        except Exception as exc:
            return (LocalComputeCandidate('local:llama-swap',health='UNAVAILABLE',reason=type(exc).__name__,capabilities=()),)
        manifest_models=self._manifest_models()
        out=[]
        for row in rows:
            model=row.get('id')
            if not isinstance(model,str) or not model: continue
            status=row.get('status') or {}
            state=status.get('value') if isinstance(status,dict) else None
            # llama-swap may advertise configured aliases before their artifact can
            # actually load. Explicit runtime failure states must not stay routable.
            failed_state=isinstance(state,str) and state.lower() in {'failed','error','unavailable','disabled'}
            roles=() if failed_state else tuple(self.role_policy.get(model,()))
            capabilities=tuple(r for r in roles if r in {'CHAT','CODE','VISION'})
            # Unknown runtime aliases stay visible but are not routable until the
            # host explicitly assigns a role.
            out.append(LocalComputeCandidate('local:llama-swap:'+model,health='UNAVAILABLE' if failed_state else 'ONLINE',active=not failed_state,
                reason=('RUNTIME_'+state.upper() if failed_state else (None if roles else 'UNASSIGNED_ROLE')),capabilities=capabilities,
                model=manifest_models.get(model,model),roles=roles,slot=model,characteristics=tuple(self.characteristic_policy.get(model,()))))
        if not out:
            return (LocalComputeCandidate('local:llama-swap',health='UNAVAILABLE',reason='NO_MODEL',capabilities=()),)
        from .local_model_availability import verify_configured_artifacts
        return verify_configured_artifacts(out,self.manifest_path)

class LlamaSwapExecution:
    def __init__(self,base_url='http://127.0.0.1:9292',model='local-general',opener=None,timeout=120,max_bytes=2*1024*1024,host_lease=None):
        u=urlparse(base_url)
        if u.scheme!='http' or u.hostname not in {'127.0.0.1','localhost','::1'}: raise ValueError('llama-swap execution must be loopback')
        self.base=base_url.rstrip('/');self.model=model;self.open=opener or request.urlopen;self.timeout=timeout;self.max=max_bytes;self.host_lease=host_lease
    def chat_payload(self,payload,model=None):
        selected=model or self.model
        body=dict(payload); body["model"]=selected; body["stream"]=False
        req=request.Request(self.base+"/v1/chat/completions",data=json.dumps(body).encode(),headers={"Content-Type":"application/json"})
        with self.host_lease.hold() if self.host_lease is not None else nullcontext():
            with self.open(req,timeout=self.timeout) as r:b=r.read(self.max+1)
        if len(b)>self.max:raise ValueError("llama-swap response too large")
        return json.loads(b)

    def chat(self,prompt,model=None):
        selected=model or self.model
        body=json.dumps({'model':selected,'messages':[{'role':'system','content':f'You are running as the local model selected by AI Foundation. Runtime model alias: {selected}. Do not claim to be Gemini, OpenAI, Claude, or another provider/model unless the user is explicitly discussing them.'},{'role':'user','content':prompt}]}).encode()
        req=request.Request(self.base+'/v1/chat/completions',data=body,headers={'Content-Type':'application/json'})
        with self.host_lease.hold() if self.host_lease is not None else nullcontext():
            with self.open(req,timeout=self.timeout) as r:b=r.read(self.max+1)
        if len(b)>self.max:raise ValueError('llama-swap response too large')
        row=json.loads(b);return row['choices'][0]['message']['content']
