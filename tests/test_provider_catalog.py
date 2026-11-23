from ai_foundation.provider_catalog import PROVIDERS,PROVIDER_NAMES,detect
from ai_foundation.http_transport import _ENDPOINTS

def test_catalog_is_single_source_for_bearer_transport():
 assert set(_ENDPOINTS)=={n for n,s in PROVIDERS.items() if s.endpoint}
 assert all(PROVIDERS[n].model or PROVIDERS[n].probe_style=='models' for n in _ENDPOINTS)

def test_catalog_names_are_unique_and_auto_detection_points_to_catalog():
 assert len(PROVIDER_NAMES)==len(set(PROVIDER_NAMES))
 for n,s in PROVIDERS.items():
  if s.key_pattern:
   sample={'GROQ':'gsk_'+'A'*24,'GEMINI':'AIza'+'A'*24,'OPENROUTER':'sk-or-v1-'+'A'*24,'NVIDIA':'nvapi-'+'A'*24}.get(n)
   if sample: assert detect(sample)==n
