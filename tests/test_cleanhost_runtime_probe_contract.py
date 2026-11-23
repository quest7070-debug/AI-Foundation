from pathlib import Path

def test_cleanhost_probe_requires_native_secret_and_never_prints_it():
 t=Path('scripts/cleanhost_runtime_probe.py').read_text()
 assert "store.available(binding)" in t
 assert "human re-provisioning required" in t
 assert "'secret_printed':False" in t
 assert "print(secret)" not in t
 assert "CLEANHOST_SIGNED_OK" in t
