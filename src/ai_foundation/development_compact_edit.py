"""Optional compact edits for the existing local-9B Guarded development loop.

The model emits one *exact* search/replace operation instead of reprinting the
entire Python file. The host reconstructs a complete replacement in memory;
the existing CodingSpecialist, Guard, fixed tests and Git Draft publisher keep
all authority. This is opt-in and does not change an installed worker.
"""
from __future__ import annotations

from dataclasses import dataclass
import ast
import hashlib
import json
import subprocess
import tempfile

from .agent import AgentRequest, AgentResult

MAX_INPUT_BYTES = 262144
# The local worker sends source inside a JSON prompt via one DSH argv element.
# Reserve room for the fixed test (up to 16 KiB), instructions and escaping.
MAX_WORKER_COMPACT_SOURCE_BYTES = 32768
MAX_EDIT_FRAGMENT_BYTES = 8192
MAX_REPLY_BYTES = 32768


class CompactEditRejected(ValueError):
    """Model output is ambiguous, invalid, or not an exact one-place edit."""


def _json_no_duplicates(pairs: list[tuple[str, object]]) -> dict:
    value = {}
    for key, item in pairs:
        if key in value:
            raise CompactEditRejected("DUPLICATE_JSON_KEY")
        value[key] = item
    return value


def compose_exact_python_edit(source: str, raw_response: str) -> str:
    """Deterministic, all-or-nothing conversion; never writes any file.

    No fuzzy matching, line-number guessing, tool execution, model-supplied
    destination, file path, shell command, or partial-file persistence.
    """
    if (type(source) is not str or not source.strip()
            or len(source.encode("utf-8")) > MAX_INPUT_BYTES):
        raise CompactEditRejected("INVALID_CURRENT_SOURCE")
    if (type(raw_response) is not str or
            len(raw_response.encode("utf-8")) > MAX_REPLY_BYTES):
        raise CompactEditRejected("INVALID_MODEL_REPLY_SIZE")
    try:
        patch = json.loads(raw_response, object_pairs_hook=_json_no_duplicates)
    except json.JSONDecodeError as error:
        raise CompactEditRejected("MODEL_REPLY_NOT_STRICT_JSON") from error
    if type(patch) is not dict or set(patch) != {"search", "replace"}:
        raise CompactEditRejected("INVALID_COMPACT_EDIT_SCHEMA")
    old, new = patch["search"], patch["replace"]
    if type(old) is not str or not old or type(new) is not str:
        raise CompactEditRejected("INVALID_EDIT_FRAGMENT_TYPES")
    if (len(old.encode("utf-8")) > MAX_EDIT_FRAGMENT_BYTES or
            len(new.encode("utf-8")) > MAX_EDIT_FRAGMENT_BYTES):
        raise CompactEditRejected("EDIT_FRAGMENT_TOO_LARGE")
    if old == new:
        raise CompactEditRejected("NO_CHANGE")
    if source.count(old) != 1:
        raise CompactEditRejected("SEARCH_NOT_UNIQUE_OR_NOT_PRESENT")
    candidate = source.replace(old, new, 1)
    if len(candidate.encode("utf-8")) > MAX_INPUT_BYTES:
        raise CompactEditRejected("RECONSTRUCTED_SOURCE_TOO_LARGE")
    # SyntaxError is intentionally retained: the existing bounded development
    # loop can send it to the model as normal repair feedback before any write.
    ast.parse(candidate)
    # ast.parse alone accepts module-level 'return', 'break' and 'yield'.
    # Reject these before any Guard write or fixed acceptance run, so the
    # existing one-repair path can handle the proposal as a SyntaxError.
    compile(candidate, "<compact-proposal>", "exec")
    return candidate


def compact_first_eligible(task: dict, source_path) -> bool:
    """Bounded fixed-Python recipe only; no model/provider/authority selection.

    This is a speed optimization for an already admitted code/test contract.
    An oversized or unavailable source continues through full-file generation.
    The existing Guard, fixed tests, review, lease and Draft delivery remain
    mandatory regardless of the answer.
    """
    from pathlib import Path
    if type(task) is not dict or task.get("recipe") != "python-fixed-test":
        return False
    path = Path(source_path)
    try:
        if path.is_symlink() or not path.is_file():
            return False
        size = path.stat().st_size
    except OSError:
        return False
    return 0 < size <= MAX_WORKER_COMPACT_SOURCE_BYTES


@dataclass(frozen=True)
class OwnerBoundHarnessTextAgent:
    """Same owner-supplied sandbox argv, cwd and env as HarnessProposalAgent.

    Raw public text is returned, not interpreted as Python before the compact
    adapter can decode it. No model launch/weights/service changes happen here
    until the existing trusted host explicitly invokes run().
    """
    argv_prefix: tuple[str, ...]
    cwd: str
    env: dict[str, str]
    timeout_s: int = 3600

    def run(self, request: AgentRequest) -> AgentResult:
        if (not self.argv_prefix or type(self.cwd) is not str or not self.cwd
                or type(self.env) is not dict
                or type(self.timeout_s) is not int
                or not 1 <= self.timeout_s <= 3600):
            raise ValueError("INVALID_HOST_HARNESS_BINDING")
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            cp = subprocess.run(
                [*self.argv_prefix, request.instruction],
                cwd=self.cwd, env=self.env, stdin=subprocess.DEVNULL,
                stdout=stdout, stderr=stderr, timeout=self.timeout_s,
                check=False,
            )
            if stdout.tell() > MAX_REPLY_BYTES or stderr.tell() > MAX_REPLY_BYTES:
                raise CompactEditRejected("HARNESS_REPLY_TOO_LARGE")
            if cp.returncode:
                # DSH stderr can include private source, prompts or credentials.
                # Preserve exit identity without sending raw model/CLI bytes
                # into durable worker failures or public issue diagnostics.
                raise RuntimeError("HARNESS_EXIT_" + str(cp.returncode))
            stdout.seek(0)
            public = stdout.read().decode("utf-8")
        # DSH Headless can wrap the public reply in one JSON *string*.
        try:
            outer = json.loads(public, object_pairs_hook=_json_no_duplicates)
        except json.JSONDecodeError:
            outer = public
        if isinstance(outer, str):
            public = outer
        elif type(outer) is not dict:
            raise CompactEditRejected("HARNESS_PUBLIC_TEXT_NOT_STRING_OR_OBJECT")
        # For a dictionary, return the original JSON for strict patch validation.
        return AgentResult(public)


@dataclass(frozen=True)
class CompactEditProposalAgent:
    """Opt-in adapter for CodingSpecialist.develop(agent=...).

    raw_agent is already bound to the trusted Harness sandbox/local-only
    provider. It never sees a model-specified file, base branch, or test command.
    """
    raw_agent: object

    def run(self, request: AgentRequest) -> AgentResult:
        try:
            packet = json.loads(
                request.instruction, object_pairs_hook=_json_no_duplicates)
        except (json.JSONDecodeError, TypeError) as error:
            raise CompactEditRejected("INVALID_HOST_REQUEST") from error
        if (type(packet) is not dict
                or type(packet.get("current_source")) is not str
                or type(packet.get("instruction")) is not str
                or type(packet.get("test_feedback")) is not str):
            raise CompactEditRejected("INVALID_HOST_PROMPT_FIELDS")
        current = packet["current_source"]
        if len(current.encode("utf-8")) > MAX_INPUT_BYTES:
            raise CompactEditRejected("INVALID_CURRENT_SOURCE")
        instruction = json.dumps({
            "task": packet["instruction"],
            "current_source": current,
            "test_feedback": packet["test_feedback"],
            "source_sha256": hashlib.sha256(current.encode("utf-8")).hexdigest(),
            "response_format": (
                "Return ONLY a JSON object with exactly two string keys: "
                "'search' (one exact, UNIQUE, nonempty substring of "
                "current_source) and 'replace' (its replacement, possibly "
                "empty). No Markdown, path, command, other fields, or full "
                "source file. Make the smallest single contiguous edit that "
                "satisfies the host-selected fixed test. All other source "
                "characters must be left unchanged."
            ),
        }, ensure_ascii=False)
        raw = self.raw_agent.run(AgentRequest(instruction))
        if type(raw.output) is not str:
            raise CompactEditRejected("MODEL_DID_NOT_RETURN_TEXT")
        return AgentResult(compose_exact_python_edit(current, raw.output))


@dataclass
class OneFastThenDeepAgent:
    """Attempt one compact fast proposal; use the original full-source path
    only if the fixed tests or syntax require the existing single repair.

    This does not create another inference/repair loop. The existing
    CodingSpecialist.develop(max_repairs=1) owns all writes and decisions.
    Runtime/transport failures always propagate; malformed compact text is
    treated as a syntax failure, permitting the one existing repair attempt.
    """
    fast: object
    deep: object
    calls: int = 0

    def run(self, request: AgentRequest) -> AgentResult:
        self.calls += 1
        if self.calls == 1:
            try:
                return self.fast.run(request)
            except CompactEditRejected as error:
                # The existing development loop already handles SyntaxError
                # as proposal feedback without writing to the filesystem.
                raise SyntaxError("COMPACT_FAST_OUTPUT_REJECTED: " + str(error)) from error
        return self.deep.run(request)
