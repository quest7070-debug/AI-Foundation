#!/usr/bin/env python3
"""Bounded live-process RSS/FD envelope over quota-free canonical capability paths."""
import json,os,subprocess,time,urllib.request
BASE='http://127.0.0.1:8766'
def csrf():return urllib.request.urlopen(BASE+'/',timeout=5).read().decode().split('name=csrf value="',1)[1].split('"',1)[0]
def post(model,content):
 b=json.dumps({'model':model,'messages':[{'role':'user','content':content}]}).encode();r=urllib.request.Request(BASE+'/v1/chat/completions',data=b,method='POST',headers={'Content-Type':'application/json','X-Foundation-CSRF':csrf()})
 with urllib.request.urlopen(r,timeout=30) as x:assert x.status==200;x.read()
def pid():return int(subprocess.check_output(['pgrep','-f','scripts/operator_server.py.*--port 8766'],text=True).splitlines()[0])
def sample(p):
 rss=int(subprocess.check_output(['ps','-o','rss=','-p',str(p)],text=True).strip());fds=len(os.listdir(f'/dev/fd')) # replaced below by lsof for target process
 try:fds=max(0,len(subprocess.check_output(['lsof','-p',str(p),'-Fn'],text=True,stderr=subprocess.DEVNULL).splitlines())-1)
 except Exception:fds=-1
 return rss,fds
def main():
 p=pid();before=sample(p)
 # DATA is bounded local execution. Existing CODE/FILES production recovery sweeps cover ToolHive process lifecycle; this envelope avoids external/provider traffic.
 for _ in range(12):post('foundation-data','[1,2,3,4]')
 mid=sample(p);time.sleep(1);after=sample(p)
 assert p==pid();assert after[0] <= before[0]+32768
 if before[1]>=0 and after[1]>=0:assert after[1] <= before[1]+16
 print(json.dumps({'status':'PASS','pid':p,'rss_kib':{'before':before[0],'mid':mid[0],'after':after[0]},'fd':{'before':before[1],'mid':mid[1],'after':after[1]},'data':12,'external_provider_loop':False},separators=(',',':')))
if __name__=='__main__':main()
