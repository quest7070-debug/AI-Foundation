import json
import pytest
from ai_foundation.openai_vision_adapter import OpenAICompatibleVision

class Resp:
    def __init__(self,b): self.b=b
    def __enter__(self): return self
    def __exit__(self,*a): pass
    def read(self,n): return self.b

def test_adapter_sends_actual_image_bytes_and_task(tmp_path):
    p=tmp_path/'x.png'
    p.write_bytes(b'\x89PNG\r\n\x1a\nPIXELS')
    seen={}
    def op(req,timeout):
        seen['body']=json.loads(req.data)
        return Resp(b'{"choices":[{"message":{"content":"seen"}}]}')
    out=OpenAICompatibleVision('http://127.0.0.1:9292','vision-slot',opener=op).analyze((str(p),),'describe')
    content=seen['body']['messages'][0]['content']
    assert out=='seen'
    assert content[0]['text']=='describe'
    import base64
    encoded=content[1]['image_url']['url'].split(',',1)[1]
    assert base64.b64decode(encoded)==p.read_bytes()

def test_non_loopback_local_endpoint_rejected():
    with pytest.raises(ValueError):
        OpenAICompatibleVision('http://example.com','x')
