import json
from ai_foundation.local_endpoint_config import load_local_endpoints

def test_missing_local_endpoint_config_is_empty(tmp_path):assert load_local_endpoints(tmp_path/'missing.json')==()
def test_local_endpoint_config_builds_host_owned_policy(tmp_path):
 p=tmp_path/'x.json';p.write_text(json.dumps({'version':1,'endpoints':[{'name':'mainpc','base_url':'http://mainpc:8000','allowed_hosts':['mainpc'],'models':[{'runtime_model':'qwen','alias':'general','capabilities':['CHAT']}]}]}))
 rows=load_local_endpoints(p);assert rows[0][0]=='local:mainpc';assert rows[0][2].models=={'general':'qwen'}
