from ai_foundation.question_ingress import resolve_ingress

def b(prompt='Choose'):
 return {'pending_id':'p','task_id':'t','session_id':'s','questions':[{'question_id':'q','prompt':prompt,'options':[]}]}

def test_ingress_deterministic_answer():
 r=resolve_ingress(b(),lambda _: {'question_id':'q','selected_options':['a']})
 assert r['route']=='DETERMINISTIC' and r['answer']['selected_options']==['a'] and r['question_digest']

def test_ingress_human_gate():
 r=resolve_ingress(b('Approve production deploy?'))
 assert r['route']=='HUMAN_GATE' and r['requires_human'] is True and 'answer' not in r

def test_ingress_secret_stays_out_of_model():
 r=resolve_ingress(b('Which API key?'))
 assert r['route']=='CREDENTIAL_BOUNDARY' and r['requires_human'] is True

def test_ingress_capability_route():
 r=resolve_ingress(b('What is the latest API spec?'))
 assert r['requires_capability']=='SEARCH'

def test_ingress_requires_correlated_identity():
 try: resolve_ingress({'pending_id':'p'})
 except ValueError: pass
 else: raise AssertionError('uncorrelated question accepted')


def test_malformed_local_peer_payload_never_reaches_authority_or_review():
 import pytest
 base=b('Approve production deploy?')
 class Reviewer:
  def review(self, bundle):
   raise AssertionError('untrusted bundle reached personal source')
 bad=[
  {**base,'pending_id':True},
  {**base,'task_id':12},
  {**base,'session_id':[]},
  {**base,'questions':None},
  {**base,'questions':{}},
  {**base,'questions':[]},
  {**base,'questions':[None]},
  {**base,'questions':[{'question_id':'q','prompt':42,'options':[]}]},
  {**base,'questions':[{'question_id':'q','prompt':'Prompt','options':None}]},
  {**base,'questions':[{'question_id':'q','prompt':'Prompt','options':[None]}]},
  {**base,'questions':[{'question_id':'q','prompt':'Prompt','options':[{'option_id':'a','label':False}]}]},
  {**base,'questions':[{'question_id':'q','prompt':'Prompt','options':[{'option_id':'a','label':'A'},{'option_id':'a','label':'B'}]}]},
  {**base,'questions':base['questions']+base['questions']},
  {**base,'questions':[{'question_id':'q','prompt':'x'*4097,'options':[]}]},
 ]
 for payload in bad:
  touched=[]
  with pytest.raises(ValueError):
   resolve_ingress(payload,lambda _:touched.append('canon'),
                   primary_review=Reviewer(),exception_requires_owner=True)
  assert touched==[], 'malformed question reached Canon authority'
