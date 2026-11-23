"""Offline regressions for four independent legacy one-file hardening deltas."""
from pathlib import Path

import pytest

from ai_foundation.agent_tools import ReadCapability, WriteCapability
from ai_foundation.bounded_http import BoundedThreadingHTTPServer
from ai_foundation.quality import QualityContract
from ai_foundation.task_result import TaskResult


def test_task_receipt_rejects_typed_malformed_json_without_trusting_fields():
    for raw in (
        '{"output":1}',
        '{"output":"ok","verification":null}',
        '{"output":"ok","evidence":"string"}',
        '{"output":"ok","evidence":[3]}',
        '{"output":"ok","route_kind":7}',
        '{"output":"ok","route_binding":false}',
        '["not", "a", "receipt"]',
    ):
        assert TaskResult.decode(raw).output == raw
    good = TaskResult("ok", "VERIFIED", "LOCAL", ("receipt",), "local:9b")
    assert TaskResult.decode(good.encode()) == good


def test_property_getter_failure_is_missing_field_not_exception():
    class Failing:
        @property
        def approved(self):
            raise RuntimeError("synthetic accessor failure")
    result = QualityContract("safe", ("approved",)).evaluate(Failing())
    assert result.passed is False and result.missing_fields == ("approved",)


@pytest.mark.parametrize("capability", [ReadCapability, WriteCapability])
def test_empty_and_whitespace_paths_denied_before_resolution(tmp_path, capability):
    for root in ("", " ", " /tmp"):
        with pytest.raises(ValueError):
            capability(root).authorize_target("safe")
    valid = capability(str(tmp_path))
    for name in ("", " ", " file", "file "):
        with pytest.raises(ValueError):
            valid.authorize_target(name)
    assert valid.authorize_target("file") == str(tmp_path / "file")
    assert valid.authorize_target(Path("file")) == str(tmp_path / "file")


@pytest.mark.parametrize("queue_size", [0, -1, True, "16"])
def test_invalid_http_queue_size_rejected_without_socket(queue_size):
    class InvalidQueue(BoundedThreadingHTTPServer):
        request_queue_size = queue_size
    server = object.__new__(InvalidQueue)
    with pytest.raises(ValueError, match="request_queue_size"):
        server.server_bind()
