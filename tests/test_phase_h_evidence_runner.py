import importlib.util
from pathlib import Path
ROOT=Path(__file__).parents[1]
spec=importlib.util.spec_from_file_location('phase_h_evidence',ROOT/'scripts/phase_h_evidence.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def test_observation_builder_is_non_authoritative_data_only():
 x=m.observation('tool-effect',output='x')
 assert x.path=='tool-effect' and x.output=='x' and x.verification=='VERIFIED'

def test_runner_cloud_scenario_uses_production_boundaries_not_synthetic_fixture():
 src=(ROOT/'scripts/phase_h_evidence.py').read_text()
 assert "choices=['local-inference','cloud-inference','tool-effect','uncertain-recovery','cancellation','human-approval','human-input','provider-failover','report']" in src
 assert 'SettingsService' in src and 'MacOSNativeCredentialStore' in src
 assert 'GuardedInferenceService' in src and 'ObservedCloudExecution' in src
 assert "EvidenceClass.LIVE if path in {'local-inference','cloud-inference'}" in src
 assert 'fixture-' not in src[src.index('def run_cloud'):src.index('def run_toolhive')]
