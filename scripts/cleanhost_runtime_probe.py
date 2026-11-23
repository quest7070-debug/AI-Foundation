#!/usr/bin/env python3
"""Probe an already isolated reconstructed Operator/Gateway without printing secrets."""
import argparse,json,time,urllib.request
from ai_foundation.native_credentials import MacOSNativeCredentialStore
from ai_foundation.librechat_signing_contract import sign_serialized_body

def post(url,body,headers):
 r=urllib.request.urlopen(urllib.request.Request(url,data=body,headers=headers,method='POST'),timeout=130)
 return r.status,json.loads(r.read())

def main():
 p=argparse.ArgumentParser();p.add_argument('--operator',default='http://127.0.0.1:18766');p.add_argument('--gateway',default='http://127.0.0.1:18767');a=p.parse_args()
 models=json.loads(urllib.request.urlopen(a.gateway+'/v1/models',timeout=5).read())
 ids={x['id'] for x in models['data']}; required={'foundation-auto','foundation-search','foundation-code','foundation-data','foundation-files','foundation-vision'}
 if not required <= ids: raise SystemExit('reconstructed model surface incomplete')
 body=json.dumps({'model':'foundation-auto','messages':[{'role':'user','content':'Reply with exactly CLEANHOST_SIGNED_OK'}]},separators=(',',':')).encode()
 store=MacOSNativeCredentialStore(); binding='foundation:attachment-handoff'
 if not store.available(binding): raise SystemExit('native credential binding unavailable; human re-provisioning required')
 secret=store.load(binding); owner='dr-cleanhost-probe';ts=int(time.time());sig=sign_serialized_body(secret,owner,body,timestamp=ts)
 h={'Content-Type':'application/json','X-Foundation-Owner':owner,'X-Foundation-Attachments':'[]','X-Foundation-Capability':'CHAT','X-Foundation-Attachment-Timestamp':str(ts),'X-Foundation-Attachment-Signature':sig}
 status,data=post(a.gateway+'/v1/chat/completions',body,h); content=data['choices'][0]['message']['content']
 if status!=200 or content!='CLEANHOST_SIGNED_OK':raise SystemExit('signed reconstructed CHAT failed')
 print(json.dumps({'status':'PASS','model_surface':len(required),'native_secret_available':True,'signed_gateway_chat':True,'secret_printed':False},sort_keys=True))
if __name__=='__main__':main()
