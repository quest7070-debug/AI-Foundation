import subprocess
from ai_foundation.native_credentials import MacOSNativeCredentialStore, NativeCredentialProvider

def test_keychain_adapter_fail_closed_off_darwin(monkeypatch):
    monkeypatch.setattr('ai_foundation.native_credentials.platform.system',lambda:'Linux')
    assert not MacOSNativeCredentialStore().available('x')

def test_empty_binding_denied_without_subprocess(monkeypatch):
    def bad(*a,**k): raise AssertionError('must not invoke backend')
    monkeypatch.setattr(subprocess,'run',bad)
    assert not MacOSNativeCredentialStore().available('')

def test_native_selector_unsupported_os_fails_closed(monkeypatch):
    monkeypatch.setattr('platform.system',lambda:'UnsupportedOS')
    assert not NativeCredentialProvider(stores={}).available('x')

def test_native_selector_is_replaceable(monkeypatch):
    class Store:
        def available(self,b): return b == 'allowed'
    monkeypatch.setattr('platform.system',lambda:'TestOS')
    p=NativeCredentialProvider(stores={'TestOS':Store()})
    assert p.available('allowed') and not p.available('other')
