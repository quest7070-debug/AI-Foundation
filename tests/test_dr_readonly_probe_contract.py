from pathlib import Path

def test_dr_probe_is_disposable_and_does_not_copy_credentials():
    text=Path('scripts/dr_readonly_probe.py').read_text()
    assert "tempfile.mkdtemp(prefix='ai-foundation-dr-probe.')" in text
    assert 'restore(generation,restored,relocate_config=True)' in text
    assert "'credential_material_copied':False" in text
    assert 'shutil.rmtree(scratch,ignore_errors=True)' in text
