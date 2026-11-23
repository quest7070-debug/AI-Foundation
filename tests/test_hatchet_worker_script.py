from pathlib import Path
def test_worker_launcher_reuses_shared_capability_composition_and_native_secret():
 s=Path('scripts/hatchet_worker.py').read_text()
 assert 'build_capability_composition' in s and 'build_inference_composition' in s and 'build_long_running_runtime' in s and 'MacOSNativeCredentialStore' in s
 assert 'CapabilityExecutor(' not in s and 'HATCHET_CLIENT_TOKEN' not in s
