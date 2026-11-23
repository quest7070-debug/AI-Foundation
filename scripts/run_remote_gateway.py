#!/usr/bin/env python3
"""Launch the Foundation remote gateway with native secrets and renewable Tailscale TLS."""
from __future__ import annotations
import os,runpy,subprocess,sys,tempfile
from pathlib import Path
# Both direct "scripts/run_remote_gateway.py" and launchd's runpy entry must
# resolve one immutable installed repository package, not cwd or a PATH alias.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
 sys.path.insert(0, str(ROOT))
from ai_foundation.native_credentials import MacOSNativeCredentialStore
SESSION='remote:gateway:session-secret'
def _cert_valid(cert,hostname,min_seconds=7*24*3600):
 cert=Path(cert)
 if not cert.is_file():return False
 try:
  subprocess.run(['/usr/bin/openssl','x509','-in',str(cert),'-noout','-checkend',str(min_seconds)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  out=subprocess.run(['/usr/bin/openssl','x509','-in',str(cert),'-noout','-ext','subjectAltName'],check=True,capture_output=True,text=True).stdout.lower()
  return f'dns:{hostname.lower()}' in out
 except (OSError,subprocess.CalledProcessError):return False

def refresh_tls(cert,key,hostname,min_validity='720h'):
 cert,key=Path(cert),Path(key);cert.parent.mkdir(parents=True,exist_ok=True)
 if key.is_file() and _cert_valid(cert,hostname):return False
 with tempfile.TemporaryDirectory(dir=cert.parent) as td:
  tc=Path(td)/'server.crt';tk=Path(td)/'server.key'
  subprocess.run(['/usr/local/bin/tailscale','cert','--min-validity',min_validity,'--cert-file',str(tc),'--key-file',str(tk),hostname],check=True,stdout=subprocess.DEVNULL)
  os.chmod(tk,0o600);os.replace(tc,cert);os.replace(tk,key)
 return True
def _arg(name):
 try:return sys.argv[sys.argv.index(name)+1]
 except (ValueError,IndexError):raise SystemExit(f'missing {name}')
def main():
 store=MacOSNativeCredentialStore()
 if not store.available(SESSION):raise SystemExit('Foundation remote gateway session secret is not provisioned')
 hosts=[x.strip().lower().rstrip('.') for x in os.environ.get('FOUNDATION_REMOTE_ALLOWED_HOSTS','').split(',') if x.strip()]
 dns=next((x for x in hosts if x.endswith('.ts.net')),None)
 if not dns:raise SystemExit('Foundation Tailscale DNS host is not configured')
 refresh_tls(_arg('--cert'),_arg('--key'),dns)
 os.environ['FOUNDATION_REMOTE_SESSION_SECRET']=store.load(SESSION)
 try:runpy.run_path(str(__file__).replace('run_remote_gateway.py','remote_gateway.py'),run_name='__main__')
 finally:
  os.environ.pop('FOUNDATION_REMOTE_SESSION_SECRET',None)
if __name__=='__main__':main()
