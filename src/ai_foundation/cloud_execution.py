from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class CloudResponse:
    status:int; headers:dict; body:str

class ProviderHTTPError(RuntimeError):
    def __init__(self,status:int,code=None):
        self.status=status; self.code=code
        super().__init__(f'provider request failed: HTTP {status}')

class CloudTransport(Protocol):
    def send(self,provider:str,secret:str,payload:dict)->CloudResponse: ...

class ObservedCloudExecution:
    """Cloud execution boundary: native secret -> transport -> authoritative provider observation."""
    def __init__(self,registry,secret_store,observer,transport,admission=None):
        self.registry=registry; self.secret_store=secret_store; self.observer=observer; self.transport=transport
        self.admission=admission
    def invoke(self,binding,payload):
        return self._invoke(binding,payload,pre_checked=False)
    def _invoke(self,binding,payload,pre_checked):
        meta=self.registry.credential(binding)
        if not meta: raise KeyError(binding)
        # Enforce exact manual no-charge admission before Keychain access or network.
        if self.admission is not None and not pre_checked: self.admission.require(meta,payload)
        secret=self.secret_store.load(binding)
        self.registry.observe(binding,active=True)
        try:
            response=self.transport.send(meta['provider'],secret,payload)
            self.observer.observe(binding,meta['provider'],response.status,response.headers)
            if response.status>=400:
                # Keep only provider error taxonomy for diagnostics. Never retain
                # the message/body because it may echo prompts or tool output.
                code=None
                try:
                    import json
                    err=(json.loads(response.body).get("error") or {})
                    if isinstance(err,dict): code=err.get("code") or err.get("type")
                except Exception: pass
                raise ProviderHTTPError(response.status,code)
            return response.body
        except Exception as exc:
            # Transport failures have no HTTP response to classify; preserve quota evidence.
            if not isinstance(exc,ProviderHTTPError):
                self.registry.observe(binding,health='DOWN',reason='transport failure')
            raise
        finally:
            self.observer.finish(binding)

    def invoke_for_function(self,binding,payload,function):
        meta=self.registry.credential(binding)
        if not meta: raise KeyError(binding)
        payload=dict(payload)
        search_query=payload.pop('search_query',None)
        if meta.get('protocol') in {'tavily-search','exa-search'}:
            if function.upper()!='SEARCH': raise RuntimeError('provider capability unavailable')
            messages=payload.get('messages') or ()
            query=search_query or next((str(m.get('content','')) for m in reversed(messages) if m.get('role')=='user'), '')
            if not query.strip(): raise ValueError('search query required')
            search_payload={'query':query}
            if meta.get('protocol')=='tavily-search':search_payload.update({'max_results':5,'include_answer':False})
            else:search_payload.update({'numResults':5,'contents':{'text':True}})
            return self.invoke(binding,search_payload)
        payload['model']=meta.get('model')
        if not payload['model']: raise RuntimeError('provider model unavailable')
        function=function.upper()
        # Admission judges the caller-supplied payload. The native tools
        # injected below are this boundary's own verified function paths,
        # never caller input, so they are checked before injection and the
        # send proceeds on that pre-checked payload.
        if self.admission is not None: self.admission.require(meta,payload)
        if meta['provider']=='GROQ' and function=='SEARCH':
            payload.update({'tools':[{'type':'browser_search'}],'tool_choice':'required'})
        elif meta['provider']=='GROQ' and function=='DATA':
            payload.update({'tools':[{'type':'code_interpreter'}],'tool_choice':'required'})
        return self._invoke(binding,payload,pre_checked=self.admission is not None)

    @staticmethod
    def extract_text(body):
        import json
        data=json.loads(body)
        if isinstance(data.get('results'),list):
            # SEARCH evidence crosses into the Agent context. Bound each excerpt
            # at this canonical boundary so one retrieved page cannot exhaust a
            # downstream model's token/rate budget.
            evidence=[{'source':str(x.get('url','')),'claim':str(x.get('title') or x.get('content',''))[:500],'excerpt':str(x.get('content') or x.get('text') or x.get('summary') or '')[:1200],'confidence':x.get('score'),'observed_at':None,'published_at':x.get('published_date') or x.get('publishedDate')} for x in data['results'][:5] if isinstance(x,dict) and x.get('url')]
            return json.dumps({'answer':'Search evidence retrieved.','evidence':evidence,'uncertainty':'Synthesis required from retrieved evidence.'},ensure_ascii=False)
        choices=data.get('choices') or ()
        if choices:
            text=(choices[0].get('message') or {}).get('content')
            if isinstance(text,str) and text.strip(): return text
        candidates=data.get('candidates') or ()
        if candidates:
            parts=((candidates[0].get('content') or {}).get('parts') or ())
            text=''.join(str(x.get('text','')) for x in parts if isinstance(x,dict))
            if text.strip(): return text
        content=((data.get('message') or {}).get('content') or ())
        if isinstance(content,list):
            text=''.join(str(x.get('text','')) for x in content if isinstance(x,dict) and x.get('type')=='text')
            if text.strip(): return text
        raise RuntimeError('provider response missing content')
