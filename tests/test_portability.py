from ai_foundation.productization import portability_report

def test_m1_macos_is_only_verified_host():
    r=portability_report('Darwin','arm64');assert r['tier']=='verified' and r['native_secret_store']=='macOS Keychain'
def test_linux_is_explicitly_unverified():
    r=portability_report('Linux','x86_64');assert r['tier']=='unsupported-unverified' and r['native_secret_store'] is None
def test_windows_is_explicitly_unverified():
    r=portability_report('Windows','AMD64');assert r['tier']=='unsupported-unverified' and r['native_secret_store'] is None
def test_other_macos_architecture_is_not_promoted_from_m1_evidence():
    assert portability_report('Darwin','x86_64')['tier']=='unsupported-unverified'
