from pathlib import Path
def test_production_sweep_uses_canonical_intake_and_http_response_only():
 s=Path('scripts/durable_human_restart_sweep.py').read_text()
 assert "intake.submit(" in s and "intake.execute(" in s
 assert "launchctl','kickstart','-k'" in s
 assert "/action/respond/" in s and "finally:" in s and "intake.cancel(" in s and "purge_terminal()" in s
 assert "sqlite3" not in s and ".store.set(" not in s and "submit_human_input(" not in s
