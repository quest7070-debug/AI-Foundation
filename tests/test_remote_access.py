from ai_foundation.remote_access import RemoteAccess,RemoteAccessConfig
import pytest

def access():
 return RemoteAccess(RemoteAccessConfig('S'*48,frozenset({'foundation.example','m1.local'})))

def test_remote_access_fails_closed_and_allows_only_explicit_or_loopback_hosts():
 a=access()
 assert a.host_allowed('foundation.example:8790') and a.host_allowed('127.0.0.1:8790')
 assert not a.host_allowed('10.0.0.20:8790') and not a.host_allowed('evil.example')
 assert not a.host_allowed('foundation.example.evil:8790')

def test_same_origin_policy_rejects_cross_and_same_site_and_host_mismatch():
 a=access()
 assert a.origin_allowed('https://foundation.example:8790','foundation.example:8790','same-origin')
 assert not a.origin_allowed('https://evil.example','foundation.example:8790','cross-site')
 assert not a.origin_allowed('https://sub.foundation.example:8790','foundation.example:8790','same-site')

def test_session_is_signed_expiring_and_replay_does_not_extend_it():
 a=access(); s=a.issue_session(now=1000)
 assert a.session_valid(s,now=1001)
 assert not a.session_valid(s+'x',now=1001)
 assert not a.session_valid(s,now=1000+31*24*3600)
 assert not a.session_valid(a.issue_session(now=2000),now=1900)

def test_token_compare_and_secret_configuration_guards():
 with pytest.raises(ValueError):RemoteAccessConfig('short',frozenset({'x'}))
 with pytest.raises(ValueError):RemoteAccessConfig('S'*48,frozenset())


def test_secure_session_policy_rejects_http_origin_even_when_host_matches():
 a=access(); assert not a.origin_allowed('http://foundation.example','foundation.example','same-origin')

def test_allowed_host_config_accepts_canonical_dns_trailing_dot_normalization(monkeypatch):
 from scripts.remote_gateway import build_access
 monkeypatch.setenv('FOUNDATION_REMOTE_SESSION_SECRET','S'*48)
 monkeypatch.setenv('FOUNDATION_REMOTE_ALLOWED_HOSTS','Example.Test.,100.64.0.1')
 a=build_access();assert a.host_allowed('example.test:8793') and a.host_allowed('100.64.0.1:8793')

def test_secure_remote_accepts_same_site_only_when_origin_is_exactly_same_origin():
 a=RemoteAccess(RemoteAccessConfig('S'*48,frozenset({'remote.test'}),True))
 assert a.origin_allowed('https://remote.test','remote.test','same-site')
 assert not a.origin_allowed('https://other.remote.test','remote.test','same-site')
 assert not a.origin_allowed('https://remote.test','remote.test','cross-site')
