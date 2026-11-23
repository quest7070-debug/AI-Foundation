"""Owner-session HumanModel ask launcher: bounded input, fail-closed entry.

The live question path needs the owner M1 session, the installed binding
and the pinned local 9B, so it is exercised by the owner E2E flow, not
here. These tests pin the launcher's own guards: question bounds and the
refusal shape when the entry conditions are not met.
"""
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = (Path(__file__).resolve().parents[1]
          / "scripts" / "m1_owner_humanmodel_ask.py")


def load_module():
    spec = importlib.util.spec_from_file_location("m1_owner_humanmodel_ask", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_validate_question_accepts_bounded_text():
    module = load_module()
    assert module.validate_question(" 進め方の原則は？ ") == "進め方の原則は？"


@pytest.mark.parametrize("raw", ["", "   ", "x" * 2049, None, 42])
def test_validate_question_rejects_unbounded(raw):
    module = load_module()
    with pytest.raises(ValueError):
        module.validate_question(raw)


def test_main_refuses_wrong_argument_count(capsys):
    module = load_module()
    code = module.main(["ask"])
    out = json.loads(capsys.readouterr().out)
    assert code == 2
    assert out["status"] == "BLOCKED"
