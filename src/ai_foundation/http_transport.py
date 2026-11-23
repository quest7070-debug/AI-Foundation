import json
from urllib import request,error,parse
from .cloud_execution import CloudResponse

from .provider_catalog import PROVIDERS

_ENDPOINTS={name:s.endpoint for name,s in PROVIDERS.items() if s.endpoint}

class _SameHostRedirect(request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        old=parse.urlsplit(req.full_url); new=parse.urlsplit(newurl)
        if (old.scheme,old.hostname,old.port or (443 if old.scheme=='https' else 80)) != (new.scheme,new.hostname,new.port or (443 if new.scheme=='https' else 80)):
            raise error.HTTPError(newurl,code,'cross-origin redirect rejected',headers,fp)
        return super().redirect_request(req,fp,code,msg,headers,newurl)

class UrllibCloudTransport:
    """Minimal stdlib transport. Provider/model routing remains above this layer."""
    def __init__(self,endpoints=None,timeout=30,opener=None,max_response_bytes=1024*1024):
        self.endpoints={**_ENDPOINTS,**(endpoints or {})}; self.timeout=timeout; self.max_response_bytes=max_response_bytes; self.opener=opener or request.build_opener(_SameHostRedirect()).open
    def send(self,provider,secret,payload):
        provider=provider.upper(); url=self.endpoints.get(provider)
        if not url: raise ValueError(f'unsupported cloud provider: {provider}')
        if provider=='GEMINI':
            messages=payload.get('messages') or (); contents=[]; call_names={}
            system=[]
            for m in messages:
                role=m.get('role')
                if role=='system':
                    if m.get('content'): system.append(str(m['content']))
                    continue
                if role=='assistant':
                    parts=[]
                    if m.get('content'): parts.append({'text':str(m['content'])})
                    for call in m.get('tool_calls') or ():
                        fn=call.get('function') or {}; args=fn.get('arguments') or {}
                        if isinstance(args,str):
                            try: args=json.loads(args)
                            except json.JSONDecodeError: args={}
                        cid=call.get('id'); name=fn.get('name')
                        if cid and name: call_names[cid]=name
                        if name: parts.append({'functionCall':{'id':cid,'name':name,'args':args}})
                    if parts: contents.append({'role':'model','parts':parts})
                    continue
                if role=='tool':
                    cid=m.get('tool_call_id'); name=call_names.get(cid) or m.get('name')
                    if not name: raise ValueError('Gemini tool response missing function name')
                    contents.append({'role':'user','parts':[{'functionResponse':{'id':cid,'name':name,'response':{'output':str(m.get('content',''))}}}]})
                    continue
                if role=='user': contents.append({'role':'user','parts':[{'text':str(m.get('content',''))}]})
            gemini={'contents':contents}
            if system: gemini['systemInstruction']={'parts':[{'text':'\n'.join(system)}]}
            tools=[]
            for tool in payload.get('tools') or ():
                fn=tool.get('function') or {}
                if fn.get('name'): tools.append({'name':fn['name'],'description':fn.get('description',''),'parameters':fn.get('parameters') or {'type':'object'}})
            if tools: gemini['tools']=[{'functionDeclarations':tools}]
            body=json.dumps(gemini,separators=(',',':')).encode()
            headers={'x-goog-api-key':secret,'Content-Type':'application/json','Accept':'application/json','User-Agent':'AI-Foundation/1.0'}
        elif provider=='EXA':
            body=json.dumps(payload,separators=(',',':')).encode()
            headers={'x-api-key':secret,'Content-Type':'application/json','Accept':'application/json','User-Agent':'AI-Foundation/1.0'}
        else:
            body=json.dumps(payload,separators=(',',':')).encode()
            headers={'Authorization':f'Bearer {secret}','Content-Type':'application/json','Accept':'application/json','User-Agent':'AI-Foundation/1.0'}
        req=request.Request(url,data=body,method='POST',headers=headers)
        try:
            with self.opener(req,timeout=self.timeout) as resp:
                raw=resp.read(self.max_response_bytes+1)
                if len(raw)>self.max_response_bytes: raise ValueError('cloud response too large')
                text=raw.decode('utf-8','replace')
                if provider=='GEMINI' and resp.status<400:
                    data=json.loads(text); parts=((data.get('candidates') or [{}])[0].get('content') or {}).get('parts') or []
                    content=''.join(str(x.get('text','')) for x in parts if x.get('text'))
                    calls=[]
                    for x in parts:
                        fc=x.get('functionCall')
                        if fc: calls.append({'id':fc.get('id'),'type':'function','function':{'name':fc.get('name'),'arguments':json.dumps(fc.get('args') or {},separators=(',',':'))}})
                    text=json.dumps({'model':'gemini','choices':[{'message':{'role':'assistant','content':content or None,'tool_calls':calls}}]},separators=(',',':'))
                return CloudResponse(resp.status,dict(resp.headers.items()),text)
        except error.HTTPError as exc:
            raw=exc.read(self.max_response_bytes+1)
            if len(raw)>self.max_response_bytes: raise ValueError('cloud response too large')
            return CloudResponse(exc.code,dict(exc.headers.items()) if exc.headers else {},raw.decode('utf-8','replace'))
