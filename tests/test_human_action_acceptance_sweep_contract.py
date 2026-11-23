from pathlib import Path


def test_human_action_acceptance_sweep_uses_one_canonical_approval():
    source = Path("scripts/human_action_acceptance_sweep.py").read_text()

    assert "guard.preflight(plan, canon)" in source
    assert '"/notification/dismiss/"' in source
    assert '"/action/cancel/"' in source
    assert source.count("restart_operator()") >= 2
    assert "runtime_state()" in source

    # No manufactured persistence/projection and no external effect execution.
    assert "sqlite3" not in source
    assert "request_approval(" not in source
    assert "dismissals.dismiss(" not in source
    assert ".execute(plan" not in source
    assert "long-term-health" not in source


def test_dismiss_is_verified_before_deny():
    source = Path("scripts/human_action_acceptance_sweep.py").read_text()
    dismiss = source.index('"/notification/dismiss/"')
    deny = source.index('"/action/cancel/"')
    assert dismiss < deny
    assert "DISMISS mutated authoritative approval state" in source
