"""Provider-neutral Harness role ports for development decisions.

This is an inference delegation layer, not a task scheduler, provider selector,
model installer or approval authority. The trusted host binds each role to an
existing admitted Harness AgentPort; roles never choose credentials/models or
make tool calls. In particular there is no direct Ollama or legacy 4B route.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
import subprocess
import tempfile
from typing import Mapping

from .agent import AgentRequest, AgentResult


ROLES = frozenset({"triage", "decomposition", "implementation", "repair", "review"})
MAX_REPLY = 262144


def _strict_json(text: str):
    def pairs(items):
        record = {}
        for key, value in items:
            if key in record:
                raise ValueError("HARNESS_DUPLICATE_JSON_KEY")
            record[key] = value
        return record
    return json.loads(text, object_pairs_hook=pairs)


@dataclass(frozen=True)
class HostBoundHarnessAgent:
    """Single approved DSH invocation, independent of the model it routes to.

    The *host* supplies the already-reviewed argv, Seatbelt, HOME and environment.
    The module adds no shell, provider-specific credentials or implicit fallback.
    This accepts text/JSON; Python syntax validation remains in the existing
    HarnessProposalAgent used for CODE edits.
    """
    argv_prefix: tuple[str, ...]
    cwd: str
    env: dict
    timeout_s: int = 90

    def run(self, request: AgentRequest) -> AgentResult:
        if (not self.argv_prefix or not all(type(a) is str and a for a in self.argv_prefix)
                or type(self.timeout_s) is not int or not 1 <= self.timeout_s <= 3600
                or not isinstance(self.cwd, str) or not self.cwd
                or not isinstance(self.env, dict)):
            raise ValueError("UNBOUND_HARNESS_RUNTIME")
        if type(request.instruction) is not str or not request.instruction.strip():
            raise ValueError("EMPTY_HARNESS_ROLE_REQUEST")
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            call = subprocess.run([*self.argv_prefix, request.instruction],
                                  cwd=self.cwd, env=self.env,
                                  stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                  timeout=self.timeout_s, check=False)
            if out.tell() > MAX_REPLY or err.tell() > MAX_REPLY:
                raise ValueError("HARNESS_ROLE_REPLY_TOO_LARGE")
            if call.returncode:
                raise RuntimeError("HARNESS_ROLE_EXIT_NONZERO")
            out.seek(0)
            body = out.read().decode("utf-8")
        # DSH headless often JSON-encodes the public answer as a string.
        try:
            decoded = _strict_json(body)
        except json.JSONDecodeError:
            decoded = body
        # DSH may emit either the JSON-string-wrapped public answer or the
        # exact structured JSON object. Both stay text until the role-specific
        # schema validator checks the contents; no tool/permission inference.
        value = body if type(decoded) is dict else decoded
        if type(value) is not str or not value.strip() or len(value.encode()) > MAX_REPLY:
            raise ValueError("HARNESS_ROLE_PUBLIC_TEXT_REQUIRED")
        return AgentResult(value)


class HarnessRoleRuntime:
    """No model-selection branch here: each role gets a host-bound Harness port."""

    def __init__(self, bindings: Mapping[str, object]):
        if (not isinstance(bindings, Mapping)
                or any(role not in ROLES or not hasattr(port, "run")
                       for role, port in bindings.items())):
            raise ValueError("INVALID_HARNESS_ROLE_BINDINGS")
        self._bindings = dict(bindings)

    def agent(self, role: str):
        if role not in ROLES:
            raise ValueError("UNKNOWN_HARNESS_ROLE")
        try:
            return self._bindings[role]
        except KeyError as error:
            raise RuntimeError("HARNESS_ROLE_UNBOUND:" + role) from error

    def invoke(self, role: str, instruction: str) -> str:
        if type(instruction) is not str or not instruction.strip():
            raise ValueError("INVALID_HARNESS_ROLE_INPUT")
        answer = self.agent(role).run(AgentRequest(instruction)).output
        if type(answer) is not str or not answer.strip() or len(answer.encode()) > MAX_REPLY:
            raise ValueError("INVALID_HARNESS_ROLE_RESPONSE")
        return answer


@dataclass(frozen=True)
class HarnessReviewGate:
    """Independent LLM review can only veto a tested change, never authorize it."""
    roles: HarnessRoleRuntime

    def review(self, *, target: str, source: str, source_sha256: str,
               acceptance_target: str, feedback: str) -> bool:
        if (type(source) is not str or type(source_sha256) is not str
                or sha256(source.encode()).hexdigest() != source_sha256):
            raise ValueError("REVIEW_SOURCE_DIGEST_MISMATCH")
        request = {
            "role": "review", "purpose": "independent_code_review_only",
            "target": target, "source_sha256": source_sha256, "source": source,
            "acceptance_target": acceptance_target, "fixed_test_feedback": str(feedback)[-2000:],
            "response_schema": {
                "verdict": "PASS or BLOCK", "source_sha256": source_sha256,
                "reason_code": "uppercase underscore token"
            },
            "constraints": "No tools, no file edits, no permission to grant approval. BLOCK if uncertain.",
        }
        response = _strict_json(self.roles.invoke(
            "review", json.dumps(request, ensure_ascii=False, sort_keys=True)))
        if (type(response) is not dict or set(response) !=
                {"verdict", "source_sha256", "reason_code"}
                or response["source_sha256"] != source_sha256
                or response["verdict"] not in ("PASS", "BLOCK")
                or type(response["reason_code"]) is not str
                or not re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", response["reason_code"])):
            raise ValueError("HARNESS_REVIEW_INVALID")
        return response["verdict"] == "PASS"


def propose_decomposition(roles: HarnessRoleRuntime, *, issue_number: int,
                          base_sha: str, reviewed_scope: Mapping[str, str],
                          reviewed_instructions: Mapping[str, str] | None = None) -> dict:
    """Host-scoped, model-proposed subtasks; never an execution or approval grant.

    reviewed_scope maps independently allowed repository source paths to their
    fixed host-selected acceptance test paths. This function does not create
    Issues, change acceptance tests, start jobs, or assign provider/model names.
    The existing GitHub/Guard host must separately approve and materialize any
    work; the returned local step IDs are NOT canonical task IDs.
    """
    from pathlib import PurePosixPath

    def safe_path(path):
        return (type(path) is str and 0 < len(path) <= 512
                and not path.startswith(("/", "~")) and "\\" not in path
                and all(part not in ("", ".", "..") and part.casefold() != ".git"
                        for part in path.split("/"))
                and all(ord(char) >= 32 and ord(char) != 127 for char in path)
                and str(PurePosixPath(path)) == path)

    if type(issue_number) is not int or issue_number < 1:
        raise ValueError("DECOMPOSITION_ISSUE_INVALID")
    if type(base_sha) is not str or re.fullmatch(r"[a-f0-9]{40}", base_sha) is None:
        raise ValueError("DECOMPOSITION_BASE_INVALID")
    if (not isinstance(reviewed_scope, Mapping)
            or not 1 <= len(reviewed_scope) <= 8
            or any(not safe_path(target) or not safe_path(test)
                   or target == test or not test.startswith("tests/")
                   for target, test in reviewed_scope.items())):
        raise ValueError("DECOMPOSITION_HOST_SCOPE_INVALID")
    scope = dict(sorted(reviewed_scope.items()))
    if reviewed_instructions is not None:
        if (not isinstance(reviewed_instructions, Mapping)
                or set(reviewed_instructions) != set(scope)
                or any(type(v) is not str or not 1 <= len(v) <= 4000
                       for v in reviewed_instructions.values())):
            raise ValueError("DECOMPOSITION_HOST_INSTRUCTIONS_INVALID")
    # These are already approved host-owned task findings, not instructions
    # supplied by the model or unreviewed GitHub prose. Without them a
    # decomposition model sees only filenames and cannot infer real work.
    request = {
        "role": "decomposition", "issue_number": issue_number, "base_sha": base_sha,
        "host_fixed_instructions": dict(sorted((reviewed_instructions or {}).items())),
        "host_write_targets": list(scope),
        "host_fixed_acceptance": scope,
        "constraints": (
            "Return each permitted source exactly once. Each step has id s1..s8, "
            "one target and short purpose; dependencies reference only returned IDs. "
            "No new paths/tests/models/permissions/commands or executable actions. "
            "This output is a proposal for separate host review, never task authority."),
        "response_schema": {
            "steps": [{"id": "s1", "target": "exact allowed source",
                       "purpose": "short analysis of the bounded change",
                       "depends_on": []}]
        }
    }
    raw = roles.invoke("decomposition", json.dumps(
        request, ensure_ascii=False, sort_keys=True))
    reply = _strict_json(raw)
    if type(reply) is not dict or set(reply) != {"steps"}:
        raise ValueError("DECOMPOSITION_SCHEMA_INVALID")
    rows = reply["steps"]
    if type(rows) is not list or len(rows) != len(scope):
        raise ValueError("DECOMPOSITION_SCOPE_INCOMPLETE")
    seen_ids, seen_targets, steps = set(), set(), []
    for row in rows:
        if type(row) is not dict or set(row) != {
                "id", "target", "purpose", "depends_on"}:
            raise ValueError("DECOMPOSITION_STEP_INVALID")
        sid, target, purpose, deps = (
            row["id"], row["target"], row["purpose"], row["depends_on"])
        if (type(sid) is not str or not re.fullmatch(r"s[1-8]", sid)
                or sid in seen_ids or type(target) is not str or target not in scope
                or target in seen_targets or type(purpose) is not str
                or not 4 <= len(purpose.strip()) <= 240 or "\x00" in purpose
                or type(deps) is not list or len(deps) > 7
                or any(type(dep) is not str or not re.fullmatch(r"s[1-8]", dep)
                       for dep in deps) or len(set(deps)) != len(deps)
                or sid in deps):
            raise ValueError("DECOMPOSITION_STEP_INVALID")
        seen_ids.add(sid)
        seen_targets.add(target)
        steps.append({"id": sid, "target": target,
                      "acceptance_path": scope[target],
                      "purpose": purpose.strip(), "depends_on": list(deps)})
    if seen_targets != set(scope):
        raise ValueError("DECOMPOSITION_SCOPE_INCOMPLETE")
    graph = {row["id"]: set(row["depends_on"]) for row in steps}
    if any(not deps.issubset(graph) for deps in graph.values()):
        raise ValueError("DECOMPOSITION_UNKNOWN_DEPENDENCY")
    visiting, done = set(), set()

    def visit(node):
        if node in visiting:
            raise ValueError("DECOMPOSITION_DEPENDENCY_CYCLE")
        if node in done:
            return
        visiting.add(node)
        for dep in graph[node]:
            visit(dep)
        visiting.remove(node)
        done.add(node)

    for node in graph:
        visit(node)
    def reachable(node, other):
        return other in graph[node] or any(
            reachable(dep, other) for dep in graph[node])
    # If two reviewed target paths overlap, they MUST have a dependency edge
    # (direct or transitive). No implicit concurrent writer permission.
    for n, left in enumerate(steps):
        for right in steps[n + 1:]:
            a, b = left["target"], right["target"]
            if (a == b or a.startswith(b + "/") or b.startswith(a + "/")):
                if not (reachable(left["id"], right["id"])
                        or reachable(right["id"], left["id"])):
                    raise ValueError("DECOMPOSITION_UNSERIALIZED_WRITE_CONFLICT")
    result = {
        "schema": "foundation-harness-decomposition/v1",
        "status": "PROPOSAL_ONLY",
        "execution_authorized": False,
        "issue_number": issue_number, "base_sha": base_sha,
        "steps": steps,
    }
    result["proposal_sha256"] = sha256(json.dumps(
        result, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8")).hexdigest()
    return result



def verify_decomposition_proposal(proposal: dict, *, issue_number: int,
                                   base_sha: str, reviewed_scope: Mapping[str, str]) -> dict:
    """Independently revalidate a saved proposal against the current host scope.

    A SHA256 in model output is a content checksum, not an authorization or
    signature. Reuse the exact validator rather than trusting a caller-supplied
    'already validated' flag. No subprocess, network or LLM invocation.
    """
    if type(proposal) is not dict or type(proposal.get("steps")) is not list:
        raise ValueError("DECOMPOSITION_PROPOSAL_INVALID")
    class FrozenResponse:
        def invoke(self, role, instruction):
            if role != "decomposition":
                raise ValueError("UNKNOWN_DECOMPOSITION_ROLE")
            raw_steps = [
                {k: item[k] for k in ("id", "target", "purpose", "depends_on")}
                for item in proposal["steps"]
            ]
            return json.dumps({"steps": raw_steps}, ensure_ascii=False)

    expected = propose_decomposition(FrozenResponse(), issue_number=issue_number,
                                      base_sha=base_sha, reviewed_scope=reviewed_scope)
    if expected != proposal:
        raise ValueError("DECOMPOSITION_PROPOSAL_DRIFT")
    return expected
