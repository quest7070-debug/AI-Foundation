from pathlib import Path
def test_sweep_is_disposable_and_never_restarts_production():
 s=Path('scripts/local_inventory_lifecycle_sweep.py').read_text()
 assert "PORT=19292" in s and "TemporaryDirectory" in s
 assert "local-compute/llama-swap.yaml" in s
 assert "launchctl" not in s and "127.0.0.1:9292" not in s
 assert "removed alias executed" in s and "e.code==404" in s

def test_lifecycle_sweep_covers_inflight_inventory_mutation():
 s=Path('scripts/local_inventory_lifecycle_sweep.py').read_text();assert 'threading.Thread' in s and 'inflight_inventory_mutation' in s and 't.join(90)' in s
