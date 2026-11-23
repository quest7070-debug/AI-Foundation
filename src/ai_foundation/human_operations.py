from dataclasses import dataclass
import re
from .orchestration import WorkStatus
LEVEL={'FAILED':3,'UNCERTAIN':5,'WAITING_HUMAN':4,'RECOVERING':3,'RUNNING':2,'VERIFIED':1,'PLANNED':1}
@dataclass(frozen=True)
class HumanTask:
 job_id:str; text:str; created_at:int; status:str; result:str; verification:str=''; route_kind:str|None=None; evidence:tuple[str,...]=(); route_binding:str|None=None
@dataclass(frozen=True)
class HumanNotice:
 level:int; kind:str; subject:str; status:str; summary_ja:str; detail_ja:str; actionable:bool=False; input_required:bool=False; updated_at:float=0; approval_ref:str=''; automatic_answer:str=''; answer_reference:dict|None=None
 def __post_init__(self):
  if self.level not in (1,2,3,4,5): raise ValueError('notification level must be 1..5')

def tasks(intake,limit=20):
 out=[]; recent=intake.recent(limit); by_job=intake.store.load_many(r.job_id for r in recent)
 for r in recent:
  rows=by_job.get(r.job_id,())
  if not rows: continue
  current=rows[-1]
  status=current.status.value
  # TASKS shows unresolved current work, not a historical completed step.
  # The legacy TaskResult decoder defaults to VERIFIED for plain strings;
  # neither that default nor an earlier step receipt verifies this job.
  if status not in {'RUNNING','WAITING_HUMAN','FAILED'}: continue
  from .task_result import TaskResult
  parsed=TaskResult.decode(current.result) if current.result else TaskResult('','UNVERIFIED')
  out.append(HumanTask(r.job_id,r.text,r.created_at,status,parsed.output,'UNVERIFIED',parsed.route_kind,parsed.evidence,parsed.route_binding))
 return tuple(out)
def notices(snapshot):
 out=[]
 for x in snapshot.as_dict().get('attention',[]):
  st=x.get('status','FAILED'); lv=LEVEL.get(st,3); subject=str(x.get('id') if st=='UNCERTAIN' and x.get('id') else (x.get('run_id') or x.get('id')))
  guard_wait=st=='WAITING_HUMAN' and x.get('kind')=='approval'
  ref=x.get('approval_ref','')
  approval=guard_wait and bool(x.get('run_id')) and type(ref) is str and re.fullmatch('[a-f0-9]{64}',ref) is not None
  code_wait=st=='WAITING_HUMAN' and x.get('kind')=='work' and x.get('step')=='development-request'
  input_required=st=='WAITING_HUMAN' and x.get('kind')=='work' and not code_wait and not x.get('run_id')
  if guard_wait:
   action=x.get('action','')
   action=action if action in {'purchase','delete','send_email','production_deploy','development_scope'} else '権限判断'
   summary='人の承認が必要な処理があります。'
   if action=='development_scope':
    target=x.get('target')
    if x.get('run_id')!='development-scope-ordinary-v1' or type(target) is not str or re.fullmatch('ordinary-code-scope:[a-f0-9]{64}',target) is None:
     approval=False
     detail='通常CODEの範囲を照合できません。Foundation側で再確認が必要です。'
    else:
     summary='通常CODEの継続実行範囲を許可しますか。'
     detail=('公開可能な通常コードと固定テストのみ。Strata優先、利用不可時はM1 9B。'
             '既存の定期ワーカーが独立した固定テストから不具合を検出し、範囲内で自発的に開発します。'
             '独立検証済みDraftの配布は既存の権限内のみ。'
             '権限・秘密・本番・ストレージその他の保護対象、有料実行、main統合、本番反映は対象外。'
             'AUTHORIZEでこの範囲を許可、DENYで拒否。範囲識別子: '+target[-64:])
   else:
    action_ja={'purchase':'購入','delete':'削除','send_email':'メール送信','production_deploy':'本番への反映'}.get(action,'権限が必要な処理')
    detail=action_ja+'にはオーナーの承認が必要です。承認はこの1件だけに効きます。AUTHORIZEボタンで承認、DENYボタンで拒否します。'
    target=x.get('target')
    if action=='production_deploy' and type(target) is str and re.fullmatch('release-scope:[a-f0-9]{64}',target):
     summary='本番への反映の承認が必要です。'
     detail='承認すると、検証済みの新しい版が本番に反映されます。対象はこの1件だけです。拒否すると、本番は今のまま変わりません。AUTHORIZEボタンで承認、DENYボタンで拒否します。対象ID: '+target[-8:]
   if not approval: detail+=' 現行の承認を照合できないため操作不可。'
  elif code_wait:
   lv=3
   summary='CODE依頼の技術審査・実行範囲の照合待ち。'
   detail='Foundationが変更対象・固定テスト・経路を照合します。権限が不足する場合はGuardの承認通知で判断します。これは追加情報の入力要求ではありません。'
  elif input_required: summary='処理を続けるため人の入力が必要です。'; detail='これは権限承認ではありません。必要な情報・コメントを受け取るまで対象の仕事は停止します。'
  elif st=='UNCERTAIN': summary='外部作用の結果を確定できません。'; detail='再実行せず、外部状態を読み戻して結果を照合する必要があります。'
  elif st=='FAILED': summary='処理が失敗しました。'; detail='失敗した処理は自動的に成功扱いされません。詳細と復旧状態を確認してください。'
  else: summary='処理状態が更新されました。'; detail='Foundation が観測した現在の状態です。'
  out.append(HumanNotice(lv,x.get('kind','system'),subject,st,summary,detail,approval,input_required,float(x.get('updated_at') or 0),x.get('approval_ref','') if x.get('kind')=='approval' else ''))
 return tuple(sorted(out,key=lambda n:(-n.level,-n.updated_at,n.subject)))

