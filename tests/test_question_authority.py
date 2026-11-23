import json
from ai_foundation.question_authority import CanonQuestionAuthority
from ai_foundation.question_bridge import question_identity

def bundle(prompt='Pick',options=None):
 return {'pending_id':'p','task_id':'t','session_id':'s','questions':[{'question_id':'q','prompt':prompt,'options':options or [{'option_id':'a','label':'A'},{'option_id':'b','label':'B'}]}]}

def write(p,b,answers=None):
 p.write_text(json.dumps({'schema_version':1,'decisions':[{'task_id':'t','question_digest':question_identity(b).digest,'answers':answers or [{'question_id':'q','selected_options':['a']}],'authority_source':'docs/CANON.md','authority_revision':'abc123'}]}))

def test_exact_authority_resolves(tmp_path):
 b=bundle();p=tmp_path/'q.json';write(p,b)
 assert CanonQuestionAuthority(p).resolve(b)==[{'question_id':'q','selected_options':['a']}]

def test_changed_question_fails_closed(tmp_path):
 b=bundle();p=tmp_path/'q.json';write(p,b)
 assert CanonQuestionAuthority(p).resolve(bundle('Different')) is None

def test_unknown_option_fails_closed(tmp_path):
 b=bundle();p=tmp_path/'q.json';write(p,b,[{'question_id':'q','selected_options':['x']}])
 assert CanonQuestionAuthority(p).resolve(b) is None

def test_custom_text_never_auto_answers(tmp_path):
 b=bundle();p=tmp_path/'q.json';write(p,b,[{'question_id':'q','selected_options':[],'custom_text':'guess'}])
 assert CanonQuestionAuthority(p).resolve(b) is None

def test_duplicate_authority_fails_closed(tmp_path):
 b=bundle();p=tmp_path/'q.json';row={'task_id':'t','question_digest':question_identity(b).digest,'answers':[{'question_id':'q','selected_options':['a']}],'authority_source':'x','authority_revision':'1'}
 p.write_text(json.dumps({'schema_version':1,'decisions':[row,row]}))
 assert CanonQuestionAuthority(p).resolve(b) is None

def test_repo_authority_revision_must_still_match(tmp_path):
 import subprocess
 repo=tmp_path/'repo';repo.mkdir();subprocess.run(['git','init','-q'],cwd=repo,check=True)
 (repo/'docs').mkdir();canon=repo/'docs/CANON.md';canon.write_text('A')
 rev=subprocess.check_output(['git','hash-object',str(canon)],cwd=repo,text=True).strip()
 b=bundle();store=tmp_path/'q.json';store.write_text(json.dumps({'schema_version':1,'decisions':[{'task_id':'t','question_digest':question_identity(b).digest,'answers':[{'question_id':'q','selected_options':['a']}],'authority_source':'docs/CANON.md','authority_revision':rev}]}))
 a=CanonQuestionAuthority(store,repo);assert a.resolve(b) is not None
 canon.write_text('B');assert a.resolve(b) is None

def test_promote_requires_current_repo_canon_and_is_exact(tmp_path):
 import subprocess
 repo=tmp_path/'repo';repo.mkdir();subprocess.run(['git','init','-q'],cwd=repo,check=True)
 (repo/'docs').mkdir();canon=repo/'docs/CANON.md';canon.write_text('A')
 rev=subprocess.check_output(['git','hash-object',str(canon)],cwd=repo,text=True).strip()
 b=bundle();answers=[{'question_id':'q','selected_options':['a']}]
 a=CanonQuestionAuthority(tmp_path/'q.json',repo);digest=a.promote(b,answers,authority_source='docs/CANON.md',authority_revision=rev)
 assert digest==question_identity(b).digest and a.resolve(b)==answers
 try:a.promote(b,answers,authority_source='docs/CANON.md',authority_revision=rev)
 except ValueError:pass
 else:raise AssertionError('duplicate promotion accepted')

def test_non_docs_authority_cannot_promote(tmp_path):
 import subprocess
 repo=tmp_path/'repo';repo.mkdir();subprocess.run(['git','init','-q'],cwd=repo,check=True)
 f=repo/'README.md';f.write_text('A');rev=subprocess.check_output(['git','hash-object',str(f)],cwd=repo,text=True).strip()
 a=CanonQuestionAuthority(tmp_path/'q.json',repo)
 try:a.promote(bundle(),[{'question_id':'q','selected_options':['a']}],authority_source='README.md',authority_revision=rev)
 except ValueError:pass
 else:raise AssertionError('non-Canon promotion accepted')
