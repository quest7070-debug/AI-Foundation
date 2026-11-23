"""OpenAI-compatible vision adapter; transport only, no model/domain semantics."""
import base64, json, mimetypes
from pathlib import Path
from urllib import request

class OpenAICompatibleVision:
    def __init__(self, base_url, model, *, opener=None, timeout=120, max_bytes=2*1024*1024):
        self.base=base_url.rstrip('/')
        self.model=model
        self.open=opener or request.urlopen
        self.timeout=timeout
        self.max=max_bytes
        if not self.base.startswith(('http://127.0.0.1:', 'http://localhost:')):
            raise ValueError('local vision endpoint must be loopback')

    def analyze(self, paths, task):
        content=[{'type':'text','text':task}]
        for raw in paths:
            p=Path(raw)
            mime=mimetypes.guess_type(p.name)[0] or 'application/octet-stream'
            encoded=base64.b64encode(p.read_bytes()).decode()
            content.append({'type':'image_url','image_url':{'url':'data:'+mime+';base64,'+encoded}})
        body=json.dumps({'model':self.model,'messages':[{'role':'user','content':content}]}).encode()
        req=request.Request(self.base+'/v1/chat/completions',data=body,headers={'Content-Type':'application/json'})
        with self.open(req,timeout=self.timeout) as response:
            data=response.read(self.max+1)
        if len(data)>self.max:
            raise ValueError('vision response too large')
        return json.loads(data)['choices'][0]['message']['content']
