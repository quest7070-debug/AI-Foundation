#!/usr/bin/env python3
"""Bounded representative live latency/readback series; no external-provider loop."""
import json,time,urllib.request,statistics

def req(method,url,body=None,headers=None):
 data=None if body is None else json.dumps(body,separators=(',',':')).encode();r=urllib.request.Request(url,data=data,method=method,headers=headers or {'Content-Type':'application/json'})
 t=time.perf_counter()
 with urllib.request.urlopen(r,timeout=30) as x: raw=x.read();status=x.status
 return round((time.perf_counter()-t)*1000,3),status,json.loads(raw)
def main():
 base='http://127.0.0.1:8766'; samples=[]
 for _ in range(10):
  ms,status,p=req('GET',base+'/api/human');assert status==200 and len(p.get('services',[]))==5;samples.append(ms)
 # DATA is canonical local bounded execution: representative capability latency without provider quota.
 body={'model':'foundation-data','messages':[{'role':'user','content':json.dumps([1,2,3,4])}]}
 data=[]
 for _ in range(5):
  ms,status,p=req('POST',base+'/v1/chat/completions',body,{'Content-Type':'application/json','X-Foundation-CSRF':urllib.request.urlopen(base+'/').read().decode().split('name=csrf value="',1)[1].split('"',1)[0]});assert status==200;data.append(ms)
 print(json.dumps({'status':'PASS','operator_ms':{'n':len(samples),'median':round(statistics.median(samples),3),'max':max(samples)},'data_ms':{'n':len(data),'median':round(statistics.median(data),3),'max':max(data)},'external_provider_loop':False},separators=(',',':')))
if __name__=='__main__':main()
