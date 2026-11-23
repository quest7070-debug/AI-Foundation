#!/usr/bin/env python3
"""Canonical-store durable human restart proof without manufacturing work rows."""
import json,os,subprocess,time,urllib.request,urllib.parse
from pathlib import Path
from ai_foundation.productization import load_config
from ai_foundation.task_intake import TaskIntake
from ai_foundation.orchestration import WorkStatus

class Waiting: status='WAITING_HUMAN'; result=None

def post(url,data):
 b=urllib.parse.urlencode(data).encode();req=urllib.request.Request(url,data=b)
 with urllib.request.urlopen(req,timeout=30) as r:return r.status,r.read().decode()
def main(config_path):
 c=load_config(config_path);root=Path(c.data_dir);intake=TaskIntake(root/c.work_db);receipt=None
 try:
  # Canonical producer path creates the intake/work row; no direct SQL or store-state manufacture.
  receipt=intake.submit('Return exactly HUMAN_RESTART_OK after using this required human context.')
  if intake.execute(receipt.job_id,lambda _:Waiting())!='WAITING_HUMAN':raise RuntimeError('did not enter waiting state')
  before=intake.store.load(receipt.job_id)[0]
  if before.status is not WorkStatus.WAITING_HUMAN:raise RuntimeError('waiting state not durable')
  uid=os.getuid();subprocess.run(['launchctl','kickstart','-k',f'gui/{uid}/dev.quest7070.ai-foundation.operator'],check=True)
  for _ in range(40):
   try:
    with urllib.request.urlopen('http://127.0.0.1:8766/api/human',timeout=1) as r:
     human=json.load(r)
    if any(x.get('job_id')==receipt.job_id and x.get('status')=='WAITING_HUMAN' for x in human.get('tasks',[])):break
   except Exception:pass
   time.sleep(.25)
  else:raise RuntimeError('restarted Operator did not read waiting work')
  html=urllib.request.urlopen('http://127.0.0.1:8766/',timeout=3).read().decode(); import re
  csrf=re.search(r'name=csrf value="([^"]+)"',html).group(1)
  status,body=post('http://127.0.0.1:8766/action/respond/'+receipt.job_id+'%3A0',{'csrf':csrf,'response':'HUMAN_RESTART_CONTEXT','return_to':'/api/human'})
  row=TaskIntake(root/c.work_db).store.load(receipt.job_id)[0]
  pending=TaskIntake(root/c.work_db).store.pending_human_input(receipt.job_id,0)
  if status!=200 or row.status is not WorkStatus.VERIFIED or pending is not None:raise RuntimeError('canonical resume did not verify/consume')
  if 'HUMAN_RESTART_OK' not in (row.result or ''):raise RuntimeError('resumed inference result mismatch')
  print(json.dumps({'status':'PASS','job_id':receipt.job_id,'restart_readback':'WAITING_HUMAN','response_http':status,'final':'VERIFIED','input_consumed':True},separators=(',',':')))
 finally:
  # Audit-owned work must never leak onto the human surface after any failure.
  if receipt is not None:
   try:intake.cancel(receipt.job_id)
   except KeyError:pass
  intake.purge_terminal()
if __name__=='__main__':
 import sys;main(sys.argv[1])
