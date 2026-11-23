from ai_foundation.human_renderer import render
from ai_foundation.human_view import from_snapshot
from ai_foundation.human_operations import HumanNotice
class S:
 def as_dict(self):return {'ready':True,'waiting_human':1,'effects':{'UNCERTAIN':1},'attention':[]}
def pages():
 v=from_snapshot(S(),notices=(HumanNotice(4,'approval','r','WAITING_HUMAN','判断が必要です','影響と検証を確認してください',True),))
 return render(v,'responsive',csrf='x'),render(v,'echo',csrf='x')
def test_surface_authority_and_information_do_dont():
 d,e=pages()
 assert 'AUTHORIZE' in d and 'AUTHORIZE' not in e
 assert 'SUBMIT TASK' not in d+e
 assert 'ADD API' in d and 'ADD API' not in e
 assert 'UPDATE ROUTES' in d and 'UPDATE ROUTES' not in e
 assert 'EXECUTION MANIFEST' not in d+e and '>AF<' not in d+e
 assert 'SYSTEM STATUS' in d and 'NOTIFICATIONS' in d and 'ui-section-title">SYSTEM</h2>' in e
def test_state_not_conveyed_only_by_color():
 for page in pages(): assert 'WAITING_HUMAN' in page and 'LV4 ACTION / WAITING_HUMAN' in page
