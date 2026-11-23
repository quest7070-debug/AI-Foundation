from pathlib import Path
def test_search_provider_sweep_is_bounded_reversible_and_traced():
 s=Path('scripts/search_provider_sweep.py').read_text()
 assert "controlled primary outage" in s
 assert "injected.blocked<1" in s
 assert "finally:\n  recovered=baseline.settings.refresh_provider(primary['binding'])" in s
 assert "e.name=='inference.attempt'" in s
 assert "recovered_run.route_binding!=primary['binding']" in s
