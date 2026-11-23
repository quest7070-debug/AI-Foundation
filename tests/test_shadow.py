import json,pytest
from ai_foundation.shadow import ShadowObservation,compare,append_evidence,read_evidence,gate,gate_matrix,h3_gate,h3_status,h3_report,REQUIRED_H3_PATHS,EvidenceClass

def obs(**kw):return ShadowObservation('local-inference','LOCAL','LOCAL / LOCAL','VERIFIED_COMPLETE','VERIFIED',**kw)
def test_shadow_comparison_is_deterministic_and_non_authoritative():
 assert compare(obs(output='x'),obs(output='x')).equivalent
 r=compare(obs(output='x'),obs(output='y'));assert not r.equivalent and r.differences==('output',)
def test_shadow_evidence_is_append_only_and_explicitly_non_authoritative(tmp_path):
 p=tmp_path/'shadow.jsonl';append_evidence(p,obs(output='x'),obs(output='x'));append_evidence(p,obs(output='x'),obs(output='y'))
 rows=read_evidence(p);assert len(rows)==2 and rows[0]['authority']=='shadow-only' and rows[0]['schema']==2 and rows[0]['evidence_class']=='DETERMINISTIC' and rows[0]['comparison']['equivalent'] is True and rows[1]['comparison']['differences']==['output']
def test_shadow_gate_requires_sample_floor_and_zero_mismatches(tmp_path):
 p=tmp_path/'shadow.jsonl'
 for _ in range(2):append_evidence(p,obs(output='x'),obs(output='x'))
 assert gate('local-inference',p,3).passed is False
 append_evidence(p,obs(output='x'),obs(output='x'));g=gate('local-inference',p,3);assert g.passed and g.samples==3 and g.mismatches==0
 append_evidence(p,obs(output='x'),obs(output='y'));g=gate('local-inference',p,3);assert not g.passed and g.mismatches==1
def test_shadow_gate_fails_closed_on_corrupt_or_wrong_authority_evidence(tmp_path):
 p=tmp_path/'shadow.jsonl';p.write_text('{bad\n')
 with pytest.raises(ValueError,match='corrupt'):gate('local-inference',p)
 p.write_text(json.dumps({'schema':2,'authority':'production','evidence_class':'LIVE'})+'\n')
 with pytest.raises(ValueError,match='unsupported'):gate('local-inference',p)


def test_matrix_gate_requires_every_user_flow_and_fails_closed(tmp_path):
 p=tmp_path/'shadow.jsonl'
 paths=('local-inference','human-input','cancellation','provider-failover')
 for path in paths:
  for _ in range(3):
   x=ShadowObservation(path,'LOCAL','LOCAL / LOCAL','VERIFIED_COMPLETE','VERIFIED','ok')
   append_evidence(p,x,x,EvidenceClass.LIVE)
 m=gate_matrix(paths,p,3); assert m.passed and not m.missing
 bad=ShadowObservation('cancellation','LOCAL','LOCAL / LOCAL','DENY','VERIFIED','ok')
 base=ShadowObservation('cancellation','LOCAL','LOCAL / LOCAL','VERIFIED_COMPLETE','VERIFIED','ok')
 append_evidence(p,bad,base)
 assert not gate_matrix(paths,p,3).passed
 assert gate_matrix(paths+('tool-effect',),p,3).missing==('tool-effect',)


def test_h3_gate_cannot_omit_required_path(tmp_path):
 p=tmp_path/'shadow.jsonl'
 for path in REQUIRED_H3_PATHS[:-1]:
  for _ in range(3):
   x=ShadowObservation(path,None,None,'VERIFIED_COMPLETE','VERIFIED','ok'); append_evidence(p,x,x,EvidenceClass.LIVE)
 g=h3_gate(p,3); assert not g.passed and g.missing==('provider-failover',)

def test_matrix_rejects_duplicate_path_names(tmp_path):
 with pytest.raises(ValueError,match='duplicate'): gate_matrix(('x','x'),tmp_path/'x',1)


def test_h3_status_exposes_each_missing_or_mismatched_flow(tmp_path):
 p=tmp_path/'s.jsonl'; x=ShadowObservation('local-inference','LOCAL','LOCAL / LOCAL','VERIFIED_COMPLETE','VERIFIED','ok')
 append_evidence(p,x,x,EvidenceClass.LIVE)
 status=h3_status(p,3); assert tuple(status)==REQUIRED_H3_PATHS
 assert status['local-inference']=={'passed':False,'samples':1,'mismatches':0,'required_samples':3}
 assert status['human-input']['samples']==0 and not status['human-input']['passed']


def test_h3_report_distinguishes_pass_mismatch_blocked_and_not_run(tmp_path):
 p=tmp_path/'e.jsonl'
 for _ in range(3):
  x=ShadowObservation('local-inference','LOCAL','LOCAL / LOCAL','VERIFIED_COMPLETE','VERIFIED','ok');append_evidence(p,x,x,EvidenceClass.LIVE)
 bad=ShadowObservation('human-input',None,None,'FAILED','FAILED','x')
 base=ShadowObservation('human-input',None,None,'VERIFIED_COMPLETE','VERIFIED','x')
 append_evidence(p,bad,base)
 rows={r.path:r for r in h3_report(p,{'cloud-inference':'valid credential not intentionally available'},3)}
 assert rows['local-inference'].state=='PASS'
 assert rows['human-input'].state=='MISMATCH'
 assert rows['cloud-inference'].state=='BLOCKED' and rows['cloud-inference'].samples==0
 assert rows['tool-effect'].state=='NOT_RUN'
 assert not any(r.state=='PASS' for r in rows.values() if r.samples==0)

def test_blocked_reason_never_creates_shadow_evidence(tmp_path):
 p=tmp_path/'none.jsonl';h3_report(p,{'cloud-inference':'no credential'})
 assert not p.exists()


def test_h3_rejects_evidence_below_required_reality_class(tmp_path):
 p=tmp_path/'e.jsonl'
 local=ShadowObservation('local-inference','LOCAL','LOCAL / LOCAL','VERIFIED_COMPLETE','VERIFIED','ok')
 tool=ShadowObservation('tool-effect',None,None,'VERIFIED_COMPLETE','VERIFIED','ok')
 for _ in range(3):
  append_evidence(p,local,local,EvidenceClass.DETERMINISTIC)
  append_evidence(p,tool,tool,EvidenceClass.DETERMINISTIC)
 assert h3_status(p,3)['local-inference']['samples']==0
 assert h3_status(p,3)['tool-effect']['samples']==0
 for _ in range(3): append_evidence(p,tool,tool,EvidenceClass.ISOLATED_REAL)
 assert h3_status(p,3)['tool-effect']['samples']==3

def test_live_evidence_satisfies_lower_reality_floor(tmp_path):
 p=tmp_path/'e.jsonl'; x=ShadowObservation('provider-failover',None,None,'VERIFIED_COMPLETE','VERIFIED','ok')
 for _ in range(3): append_evidence(p,x,x,EvidenceClass.LIVE)
 assert h3_status(p,3)['provider-failover']['passed']
