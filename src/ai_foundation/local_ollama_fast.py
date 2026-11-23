"""Fast local-only proposal for one bounded code edit.

Runs *inside* the existing host-owned lease and dedicated Ollama process.
Only the model's text proposal bypasses DSH's startup/Headless buffering.
The original Foundation CodingSpecialist/Guard, fixed tests and Draft
publisher retain all write and effect authority. Any failure is visible,
never silently switched to cloud or another model.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from time import monotonic
from urllib import request

from .agent import AgentRequest, AgentResult
from .development_compact_edit import CompactEditRejected

LOCAL_URL = "http://127.0.0.1:11436/api/chat"
MODEL = "qwen3.5:9b"
OUTPUT_LIMIT = 384
TIMEOUT_SECONDS = 150
MAX_HTTP_RESPONSE = 64 * 1024
_OPENER = request.build_opener(request.ProxyHandler({}))


@dataclass
class DirectLocalOllamaTextAgent:
    """Owned, nonthinking JSON text producer; not an unguarded CODE writer.

    Created only after existing owner verifies the pinned model digest, binds
    isolated loopback port 11436 and holds HostComputeLease. No host permissions,
    paths, model choice or tool invocations can be supplied by model output.
    """
    last_metrics: dict = field(default_factory=dict, init=False)
    calls: int = field(default=0, init=False)

    def run(self, task: AgentRequest) -> AgentResult:
        if (type(task.instruction) is not str or
                not task.instruction or
                len(task.instruction.encode("utf-8")) > 48 * 1024):
            raise ValueError("INVALID_FAST_PROPOSAL_PROMPT")
        self.calls += 1
        payload = {
            "model": MODEL,
            "stream": False,
            "think": False,
            "format": "json",
            "keep_alive": "5m",
            "messages": [{"role": "user", "content": task.instruction}],
            "options": {
                "temperature": 0,
                "num_ctx": 32768,
                "num_predict": OUTPUT_LIMIT,
            },
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            LOCAL_URL, data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        started = monotonic()
        try:
            with _OPENER.open(req, timeout=TIMEOUT_SECONDS) as response:
                raw = response.read(MAX_HTTP_RESPONSE + 1)
        finally:
            # This records completion/exception time but never the prompt
            # or model content and does not imply success.
            self.last_metrics = {
                "transport_elapsed_seconds": round(monotonic() - started, 3),
                "completed": False,
                "localhost_only": True,
                "thinking_requested": False,
                "max_output_tokens": OUTPUT_LIMIT,
            }
        if len(raw) > MAX_HTTP_RESPONSE:
            raise ValueError("LOCAL_MODEL_RESPONSE_TOO_LARGE")
        result = json.loads(raw)
        if (type(result) is not dict or result.get("done") is not True
                or result.get("model") != MODEL
                or type(result.get("message")) is not dict):
            raise ValueError("LOCAL_MODEL_COMPLETION_NOT_VERIFIED")
        msg = result["message"]
        if msg.get("thinking") not in (None, ""):
            raise ValueError("LOCAL_MODEL_THINKING_NOT_DISABLED")
        # A capped, finished proposal is a model-content error, not an
        # unverified network effect. The existing one deep repair can handle
        # it after SyntaxError conversion; no second fast model call occurs.
        if result.get("done_reason") == "length":
            raise CompactEditRejected("FAST_MODEL_OUTPUT_BUDGET_EXHAUSTED")
        if type(msg.get("content")) is not str or not msg["content"]:
            raise CompactEditRejected("FAST_MODEL_NO_PUBLIC_CONTENT")
        if (result.get("done_reason") not in (None, "stop")
                or type(result.get("eval_count")) is not int
                or result["eval_count"] <= 0
                or type(result.get("eval_duration")) is not int
                or result["eval_duration"] <= 0):
            raise ValueError("LOCAL_MODEL_USAGE_NOT_VERIFIED")
        # Avoid inferring speed from wall time; Ollama returns decode-only time.
        self.last_metrics.update({
            "completed": True,
            "eval_count": result["eval_count"],
            "eval_duration_ns": result["eval_duration"],
            "eval_tokens_per_second": round(
                1_000_000_000 * result["eval_count"] /
                result["eval_duration"], 3),
            "prompt_eval_count": result.get("prompt_eval_count"),
            "load_duration_ns": result.get("load_duration"),
        })
        return AgentResult(msg["content"])
