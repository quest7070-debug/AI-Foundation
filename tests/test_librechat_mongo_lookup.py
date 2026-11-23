import subprocess
from ai_foundation.librechat_mongo_lookup import LibreChatMongoQuery

def test_query_is_fixed_to_files_and_allowlisted_fields(monkeypatch):
 seen={}
 def run(argv,**kw):
  seen['argv']=argv
  return type('R',(),{'returncode':0,'stdout':'{"file_id":"f","user":"0123456789abcdef01234567","filepath":"/app/uploads/u/a.txt"}\n'})()
 monkeypatch.setattr(subprocess,'run',run)
 q=LibreChatMongoQuery()
 assert q({'file_id':'f','user':'0123456789abcdef01234567'})['filepath'].endswith('a.txt')
 joined=' '.join(seen['argv'])
 assert seen['argv'][0] == '/usr/local/bin/docker'
 assert 'ObjectId(owner)' in joined
 assert 'db.files.findOne' in joined and 'filepath:1' in joined and 'text:1' in joined
 assert q({'file_id':'f','user':'u','evil':'x'}) is None


def test_owner_and_file_id_are_required_before_mongo_process(monkeypatch):
 def forbidden(*args,**kwargs):
  raise AssertionError('ownerless or unbound Mongo query reached Docker')
 monkeypatch.setattr(subprocess,'run',forbidden)
 q=LibreChatMongoQuery()
 for candidate in (
  {'file_id':'victim-file'},
  {'user':'a'*24},
  {'tenantId':'tenant'},
  {'file_id':'victim-file','tenantId':'tenant'},
  {'file_id':'victim-file','user':'not-an-objectid'},
  {'file_id':'victim-file','user':'a'*24,'extra':'unsupported'},
 ):
  assert q(candidate) is None


def test_mongo_host_failure_returns_no_metadata(monkeypatch):
 def unavailable(*args, **kwargs):
  raise OSError("synthetic docker unavailable")
 monkeypatch.setattr(subprocess, 'run', unavailable)
 query={'file_id':'f','user':'0123456789abcdef01234567'}
 assert LibreChatMongoQuery()(query) is None

 def timed_out(*args, **kwargs):
  raise subprocess.TimeoutExpired(args[0], 5)
 monkeypatch.setattr(subprocess, 'run', timed_out)
 assert LibreChatMongoQuery()(query) is None


def test_readback_rejects_wrong_owner_file_or_tenant(monkeypatch):
 import json
 owner='0123456789abcdef01234567'
 lookup=LibreChatMongoQuery()
 def answer(doc):
  def run(*args,**kwargs):
   return type('R',(),{'returncode':0,'stdout':json.dumps(doc)+'\n'})()
  monkeypatch.setattr(subprocess,'run',run)
 def check(doc,query):
  answer(doc)
  assert lookup(query) is None

 check({'file_id':'other','user':owner},{'file_id':'f','user':owner})
 check({'file_id':'f','user':'a'*24},{'file_id':'f','user':owner})
 check({'file_id':'f','user':None},{'file_id':'f','user':owner})
 check({'file_id':'f'},{'file_id':'f','user':owner})
 check({'file_id':'f','user':owner,'tenantId':'foreign'},
       {'file_id':'f','user':owner,'tenantId':'allowed'})
 answer({'file_id':'f','user':owner.upper(),'tenantId':'allowed'})
 assert lookup({'file_id':'f','user':owner,'tenantId':'allowed'}) is not None
