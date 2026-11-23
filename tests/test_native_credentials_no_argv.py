import inspect
from ai_foundation.native_credentials import MacOSNativeCredentialStore
def test_secret_is_not_passed_to_security_cli_argv():
 src=inspect.getsource(MacOSNativeCredentialStore); assert 'subprocess' not in src and 'security' not in src and 'secret]' not in src
