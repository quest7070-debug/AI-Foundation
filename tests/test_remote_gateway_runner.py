from pathlib import Path
def test_runner_uses_native_secret_boundary_and_no_literal_secret():
 s=Path('scripts/run_remote_gateway.py').read_text()
 assert 'MacOSNativeCredentialStore' in s and '.load(SESSION)' in s and 'AUTH' not in s
 assert 'AUTH_TOKEN=' not in s and 'SESSION_SECRET=' not in s
def test_gateway_default_does_not_collide_with_known_8791_listener():
 s=Path('scripts/remote_gateway.py').read_text();assert "default=8793" in s

def test_runner_refreshes_tls_atomically_without_secret_arguments(tmp_path,monkeypatch):
 import scripts.run_remote_gateway as r
 calls=[]
 def fake(cmd,**kw):
  calls.append(cmd);Path(cmd[cmd.index('--cert-file')+1]).write_text('cert');Path(cmd[cmd.index('--key-file')+1]).write_text('key')
 monkeypatch.setattr(r.subprocess,'run',fake)
 c=tmp_path/'tls'/'server.crt';k=tmp_path/'tls'/'server.key';r.refresh_tls(c,k,'host.ts.net')
 assert c.read_text()=='cert' and k.read_text()=='key' and (k.stat().st_mode&0o777)==0o600
 assert '--min-validity' in calls[0] and '720h' in calls[0]
 assert all('AUTH_TOKEN' not in x and 'SESSION_SECRET' not in x for x in calls[0])

def test_valid_existing_cert_skips_tailscale_ca(monkeypatch,tmp_path):
 import scripts.run_remote_gateway as r;c=tmp_path/'server.crt';k=tmp_path/'server.key';c.write_text('cert');k.write_text('key')
 monkeypatch.setattr(r,'_cert_valid',lambda *a,**kw:True)
 monkeypatch.setattr(r.subprocess,'run',lambda *a,**kw:(_ for _ in ()).throw(AssertionError('CA must not be called')))
 assert r.refresh_tls(c,k,'host.ts.net') is False

def test_invalid_existing_cert_requires_successful_renewal(monkeypatch,tmp_path):
 import scripts.run_remote_gateway as r;c=tmp_path/'server.crt';k=tmp_path/'server.key';c.write_text('old');k.write_text('old')
 monkeypatch.setattr(r,'_cert_valid',lambda *a,**kw:False)
 def fail(*a,**kw):raise r.subprocess.CalledProcessError(1,a[0])
 monkeypatch.setattr(r.subprocess,'run',fail)
 import pytest
 with pytest.raises(r.subprocess.CalledProcessError):r.refresh_tls(c,k,'host.ts.net')
 assert c.read_text()=='old' and k.read_text()=='old'
