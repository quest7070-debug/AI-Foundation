"""Host-owned OpenCode CLI proposal route for the existing Foundation Harness.

The OpenCode Console Free provider is a CLI *agent*, not a generic HTTP chat
transport. This module does not install/launch OpenCode, resolve credentials,
open sockets, or select a paid model. The trusted Operator must inject its
already isolated, model-filtered, no-auto-charge host execution port.

Use CloudInferencePort's existing durable attempt ledger and Guard-managed
model-work admission, then the existing local final review and Draft writer.
If any prerequisite is absent, default Harness routing never registers this
backend, and local 9B remains available.
"""
from __future__ import annotations

import re

from .next_service_preflight import (OpenCodeReviewEvidence, opencode_readiness,
                                     reviewable_free_model)

OPENCODE_MODEL = "opencode/hy4-flash-free"
OPENCODE_ID = "OPENCODE"
OPENCODE_ENDPOINT_ID = "https://opencode.ai/inference"
_MAX_PROMPT_CHARS = 4096
_MAX_SOURCE_BYTES = 262144


class OpenCodeHarnessCLIExecution:
    """A CloudInferencePort-compatible, host-owned CLI execution boundary.

    The port must execute a pinned CLI inside the host's verified sandbox with
    model-level upstream request filtering. No untrusted model, fallback, tool,
    session, shell, project directory, or credential path is accepted here.
    """

    def __init__(self, *, host_port, binding, reviewed_model):
        if (type(binding) is not str or not re.fullmatch(
                r"llm:[A-Za-z0-9_:-]{2,160}", binding)
                or not reviewable_free_model(reviewed_model)
                or getattr(host_port, "pinned_model", OPENCODE_MODEL) != reviewed_model
                or not callable(getattr(host_port, "run_bounded_public_code", None))):
            raise ValueError("OPENCODE_TRUSTED_HOST_PORT_REQUIRED")
        self._port = host_port
        self._binding = binding
        self._model = reviewed_model

    def invoke_for_function(self, binding, payload, function):
        if binding != self._binding or function != "CODE":
            raise PermissionError("OPENCODE_ROUTE_NOT_BOUND")
        if type(payload) is not dict or set(payload) != {"messages"}:
            raise PermissionError("OPENCODE_PAYLOAD_NOT_PUBLIC_CODE")
        messages = payload["messages"]
        if (type(messages) is not list or len(messages) != 1
                or type(messages[0]) is not dict
                or set(messages[0]) != {"role", "content"}
                or messages[0]["role"] != "user"
                or type(messages[0]["content"]) is not str
                or not 0 < len(messages[0]["content"]) <= _MAX_PROMPT_CHARS):
            raise PermissionError("OPENCODE_PAYLOAD_NOT_PUBLIC_CODE")
        prompt = messages[0]["content"]
        # This is exactly one call. On a missing or ambiguous reply, the
        # existing durable cloud-attempt ledger records UNCERTAIN (no retry).
        source = self._port.run_bounded_public_code(
            model=self._model, prompt=prompt)
        if (type(source) is not str
                or not 0 < len(source.encode("utf-8")) <= _MAX_SOURCE_BYTES):
            raise RuntimeError("OPENCODE_HOST_REPLY_UNUSABLE")
        return source

    @staticmethod
    def extract_text(response):
        # CloudInferencePort needs a source string. The trusted host then
        # independently compiles it and locally reviews before any Guard write.
        if type(response) is not str:
            raise RuntimeError("OPENCODE_HOST_REPLY_UNUSABLE")
        return response


def reviewed_opencode_execution_factory(*, port, review):
    """Host composition only: no account, no billing receipt => no backend."""
    if (not isinstance(review, OpenCodeReviewEvidence)
            or not reviewable_free_model(review.model)
            or getattr(port, "pinned_model", OPENCODE_MODEL) != review.model
            or opencode_readiness(review)["stage"] != "PREPARED_FOR_HOST_REVIEW"
            or not callable(getattr(port, "run_bounded_public_code", None))):
        return None
    # Returned factory is not a payment authorization: HarnessServiceRegistry
    # separately checks the manually selected exact provider/account binding.
    return lambda binding: OpenCodeHarnessCLIExecution(
        host_port=port, binding=binding, reviewed_model=review.model)
