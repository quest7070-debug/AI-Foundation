from pathlib import Path

def test_script_never_requests_or_prints_secret_value():
 s=Path('scripts/check_live_provider.py').read_text()
 assert '.load(' not in s and 'find-generic-password' not in s
 assert 'credential_present' in s and 'store.available(binding)' in s
