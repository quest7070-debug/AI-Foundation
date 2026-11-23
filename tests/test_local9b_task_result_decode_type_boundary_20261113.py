"""Pinned local9B acceptance: a malformed TaskResult input cannot fabricate typed output.

A real TaskResult is exchanged as text. Legacy freeform TEXT is preserved,
but a nontext caller payload must never escape as output under str annotation.
This test is standalone; no model, owner data, network, or source edits.
"""
import pytest

from ai_foundation.task_result import TaskResult


@pytest.mark.parametrize("invalid", [42, True, {"output": "fabricated"}, [1, 2], b"binary"])
def test_decode_nontext_payload_is_inert(invalid):
    result = TaskResult.decode(invalid)
    assert type(result.output) is str
    assert result.output == ""
    assert result.verification == "VERIFIED"
    assert result.evidence == ()
    assert result.route_kind is None
    assert result.route_binding is None
    assert type(result.encode()) is str


def test_decode_preserves_original_legacy_text_and_valid_typed_roundtrip():
    legacy = "Legacy result, not JSON"
    assert TaskResult.decode(legacy).output == legacy
    expected = TaskResult("answer", "VERIFIED", "LOCAL", ("e1",), "local:9b")
    assert TaskResult.decode(expected.encode()) == expected
