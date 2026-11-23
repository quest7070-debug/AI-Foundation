import json
from ai_foundation.capability_execution import CapabilityExecutor
from ai_foundation.capability_request import CapabilityRequest

class SearchInference:
 def run(self,plan,canon,function):
  assert function=='SEARCH'
  return type('Out',(),{
   'status':'VERIFIED_COMPLETE',
   'result':json.dumps({
    'answer':'grounded',
    'evidence':[{'source':'https://example.invalid/source','claim':'observed','excerpt':'e','confidence':'high'}],
    'uncertainty':'',
   }),
   'observed_at':None,
  })()

def test_search_execution_does_not_require_toolhive_ports_or_mcp_registry():
 executor=CapabilityExecutor(SearchInference(),guard=None)
 result=json.loads(executor.execute(CapabilityRequest('SEARCH',owner_id='u'),'current external fact','auto-tool-1'))
 assert result['answer']=='grounded'
 assert result['evidence'][0]['claim']=='observed'
 assert executor.file_port is None and executor.repo_port is None and executor.mcp_registry is None
