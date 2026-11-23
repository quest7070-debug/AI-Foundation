from pathlib import Path
def test_resource_envelope_is_bounded_and_quota_safe():
 s=Path('scripts/live_resource_envelope.py').read_text();assert "range(12)" in s and 'foundation-data' in s and 'foundation-search' not in s and "32768" in s
