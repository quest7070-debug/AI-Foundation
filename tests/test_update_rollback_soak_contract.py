from pathlib import Path
def test_soak_is_disposable_multi_generation_and_no_runtime_mutation():
 s=Path('scripts/update_rollback_soak.py').read_text();assert 'TemporaryDirectory' in s and 'range(1,7)' in s and 'recover_interrupted_update' in s and "canonical_runtime_touched':False" in s and 'launchctl' not in s
