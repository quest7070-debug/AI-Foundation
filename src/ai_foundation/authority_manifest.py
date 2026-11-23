"""Fail-closed marker distinguishing first bootstrap from loss of established authority."""
from pathlib import Path
import json,os
MARKER='authority-initialized.json'
def authority_files(config):
 return tuple(dict.fromkeys(getattr(config,n) for n in ('guard_db','work_db','provider_db','routing_db','reconciliation_db','inference_db')))
def verify(root,config):
 root=Path(root);p=root/MARKER
 if not p.exists():return {'established':False,'missing':()}
 try:d=json.loads(p.read_text());expected=tuple(d['files'])
 except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError) as exc:raise RuntimeError('authority marker unreadable') from exc
 canonical=authority_files(config)
 if expected!=canonical:raise RuntimeError('authority marker/config mismatch')
 missing=tuple(name for name in expected if not (root/name).is_file())
 if missing:raise RuntimeError('authoritative store missing: '+','.join(missing))
 return {'established':True,'missing':()}
def establish(root,config):
 root=Path(root);root.mkdir(parents=True,exist_ok=True);files=authority_files(config)
 missing=tuple(name for name in files if not (root/name).is_file())
 if missing:raise RuntimeError('cannot establish incomplete authority: '+','.join(missing))
 p=root/MARKER
 if p.exists():return verify(root,config)
 tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps({'version':1,'files':files},separators=(',',':'))+'\n');os.replace(tmp,p)
 return {'established':True,'missing':()}
