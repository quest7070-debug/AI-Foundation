from pathlib import Path
def test_operator_bootstrap_owns_push_dispatch_without_legacy_dependency():
 s=Path('scripts/operator_server.py').read_text()
 assert 'PushDispatch' in s and 'WebPushTransport' in s and "push.dispatch(app.human_payload())" in s
 assert 'HumanConsole' not in s and 'human-console' not in s and ':8790' not in s
 assert "daemon=True" in s and "except Exception:pass" in s
