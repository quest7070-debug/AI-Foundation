import json
from pathlib import Path

def test_hatchet_reconstruction_images_are_immutable():
 d=json.loads(Path('ops/runtime/external-owner-images.json').read_text())
 assert d['schema_version']==1
 for name in ('ai-foundation-hatchet-lite','ai-foundation-hatchet-pg'):
  row=d['images'][name]
  assert '@sha256:' in row['reference']
  assert row['image_id'].startswith('sha256:') and len(row['image_id'])==71

def test_runtime_drift_checks_hatchet_image_ids():
 t=Path('scripts/runtime_drift_audit.py').read_text()
 assert 'immutable image mismatch' in t
 assert 'external-owner-images.json' in t
