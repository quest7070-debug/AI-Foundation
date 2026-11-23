from pathlib import Path
def test_live_series_is_bounded_and_does_not_loop_external_search():
 s=Path('scripts/live_latency_series.py').read_text()
 assert "range(10)" in s and "range(5)" in s and "foundation-data" in s
 assert "foundation-search" not in s and "external_provider_loop':False" in s
