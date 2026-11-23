"""Owner-local activation of existing direct MCP CODE tickets; no GitHub roundtrip.

Only a trusted M1 --enable-local-development launch reads an owner-owned
manifest. The model caller can select a prebound ticket ID, never a path,
command, provider, test, credential, authorization, or runtime model.
"""
from __future__ import annotations

from contextlib import nullcontext
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import subprocess

from ai_foundation.agent import AgentResult
from ai_foundation.development_host import (
    HostBoundLocalDevelopmentPort, HostBoundLocalDevelopmentTask,
)
from ai_foundation.durable_work import SQLiteWorkStore
from ai_foundation.host_compute_lease import HostComputeLease
from ai_foundation.shared_ollama9b_adapter import SharedOllama9BExecution, SharedOllama9BDiscovery
from ai_foundation.local_endpoint_config import load_local_endpoints
from ai_foundation.sensitive_input_scan import contains_sensitive_value
from ai_foundation.harness_provider_adapter import compiled_source
if __package__:
    from .local9b_task_recipe import FixedPytest
else:
    from local9b_task_recipe import FixedPytest

_OWNER = "macos-owner-local"
_REPO = "quest7070-dev/AI-Foundation"
_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,47}\Z")
_SHA40 = re.compile(r"[a-f0-9]{40}\Z")
_SHA64 = re.compile(r"[a-f0-9]{64}\Z")
_SOURCE = re.compile(r"src/ai_foundation/[A-Za-z0-9_]+\.py\Z")
_TEST = re.compile(r"tests/test_[A-Za-z0-9_]+\.py\Z")
# Bounded historical owner manifest, shared across every read/write path.
# A larger registry does NOT increase one-shot Work claims or compute slots.
MAX_OWNER_DEVELOPMENT_TICKETS = 24
# JSON escaped characters can exceed the generic 64-KiB private-file bound.
# Only the owner CODE manifest gets a larger, still finite read allowance.
MAX_OWNER_DEVELOPMENT_MANIFEST_BYTES = 2 * 1024 * 1024


def _owner_file(path, *, max_bytes=65536):
    path = Path(path)
    parent = path.parent
    for obj in (parent, path):
        info = obj.lstat()
        expected = stat.S_ISDIR if obj == parent else stat.S_ISREG
        if (not expected(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077):
            raise PermissionError("OWNER_DEVELOPMENT_MANIFEST_NOT_PRIVATE")
    info = path.lstat()
    if not 0 < info.st_size <= max_bytes:
        raise ValueError("DEVELOPMENT_MANIFEST_SIZE_INVALID")
    return path.read_bytes()


def _owner_manifest(path):
    """Read only the owner CODE tickets registry with its dedicated bound."""
    return _owner_file(path, max_bytes=MAX_OWNER_DEVELOPMENT_MANIFEST_BYTES)


def _strict_json(raw):
    def distinct(pairs):
        data = {}
        for name, value in pairs:
            if name in data:
                raise ValueError("DUPLICATE_DEVELOPMENT_MANIFEST_KEY")
            data[name] = value
        return data
    return json.loads(raw, object_pairs_hook=distinct)


def _validate_ticket(record):
    expected = {"ticket_id", "base_sha", "instruction", "target",
                "test", "test_sha256", "source_sha256", "model"}
    if type(record) is not dict or not expected <= set(record):
        raise ValueError("DEVELOPMENT_TICKET_SCHEMA_INVALID")
    if record["model"] not in ("m1", "auto", "strata"):
        raise ValueError("DEVELOPMENT_MODEL_NOT_ADMITTED")
    additional = ({"public_source_sha256", "public_instruction_sha256"}
                  if record["model"] in ("auto", "strata") else set())
    if "allow_draft_delivery" in record:
        if type(record["allow_draft_delivery"]) is not bool:
            raise ValueError("DRAFT_DELIVERY_CONTRACT_INVALID")
        additional.add("allow_draft_delivery")
    if "source_origin" in record:
        if record["source_origin"] not in (
                "owner-local-review-v1", "owner-scope-delegation-v1"):
            raise ValueError("DEVELOPMENT_SOURCE_ORIGIN_INVALID")
        additional.add("source_origin")
        if record["source_origin"] == "owner-scope-delegation-v1":
            if (type(record.get("scope_ref")) is not str
                    or not _SHA64.fullmatch(record["scope_ref"])
                    or record["model"] not in ("m1", "auto")):
                raise ValueError("DEVELOPMENT_SCOPE_DELEGATION_INVALID")
            additional.add("scope_ref")
    elif "scope_ref" in record:
        raise ValueError("DEVELOPMENT_SCOPE_DELEGATION_INVALID")
    if "web_guidance_topic" in record:
        # Explicit owner-manifest opt-in only for two existing HTML-rendering
        # modules. Never let a model-selected topic weaken the reviewed-public
        # source/instruction SHA requirements for Strata.
        from ai_foundation.modern_web_guidance import TOPICS
        if (record["model"] not in ("auto", "strata")
                or record.get("target") not in (
                    "src/ai_foundation/operator_server.py",
                    "src/ai_foundation/human_renderer.py")
                or type(record["web_guidance_topic"]) is not str
                or record["web_guidance_topic"] not in TOPICS):
            raise ValueError("WEB_GUIDANCE_OWNER_SCOPE_INVALID")
        additional.add("web_guidance_topic")
    if set(record) != expected | additional:
        raise ValueError("DEVELOPMENT_TICKET_SCHEMA_INVALID")
    if (type(record["ticket_id"]) is not str or not _ID.fullmatch(record["ticket_id"])
            or type(record["base_sha"]) is not str
            or not _SHA40.fullmatch(record["base_sha"])
            or type(record["target"]) is not str
            or not _SOURCE.fullmatch(record["target"])
            or type(record["test"]) is not str
            or not _TEST.fullmatch(record["test"])
            or type(record["test_sha256"]) is not str
            or not _SHA64.fullmatch(record["test_sha256"])
            or type(record["source_sha256"]) is not str
            or not _SHA64.fullmatch(record["source_sha256"])
            or type(record["instruction"]) is not str
            or not 1 <= len(record["instruction"]) <= 4000):
        raise ValueError("DEVELOPMENT_TICKET_NOT_PINNED")
    if record["model"] in ("auto", "strata"):
        for key, expected_hash in (
            ("public_source_sha256", record["source_sha256"]),
            ("public_instruction_sha256",
             sha256(record["instruction"].encode()).hexdigest()),
        ):
            if type(record[key]) is not str or record[key] != expected_hash:
                raise ValueError("STRATA_PUBLIC_SOURCE_REVIEW_REQUIRED")



def _guided_instruction(record):
    """Build one host-owned public instruction before computing the Strata SHA.

    No source, prompt or private task data ever become CLI search arguments.
    Retrieval can fail without blocking the existing source-pinned CODE route.
    """
    instruction = record["instruction"]
    if "web_guidance_topic" not in record:
        return instruction
    from ai_foundation.modern_web_guidance import lookup
    guide = lookup(record["web_guidance_topic"])
    if not guide.startswith("[Host-bounded external web-platform reference;"):
        return instruction
    enriched = (
        instruction
        + "\n\n[External, untrusted reference; preserve owner instructions, "
          "Guard, tests and target browser requirements]\n"
        + guide
    )
    # Reuse the existing 4 KiB host-bounded task instruction cap. No
    # truncation of possibly interdependent guidance or extra model work.
    return enriched if len(enriched) <= 4000 else instruction


def _git(repo, *args):
    try:
        return subprocess.check_output(
            ["git", "-c", "core.hooksPath=/dev/null", "-C", str(repo), *args],
            text=True, stderr=subprocess.DEVNULL, timeout=30).strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise RuntimeError("LOCAL_CHECKOUT_NOT_VERIFIED") from None


def _owner_local_repo():
    repo = Path.home() / "Develop/AI-Foundation"
    info = repo.lstat()
    if (repo.is_symlink() or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid() or info.st_mode & 0o022
            or Path(_git(repo, "rev-parse", "--show-toplevel")).resolve() != repo.resolve()):
        raise ValueError("OWNER_LOCAL_REPOSITORY_UNVERIFIED")
    return repo


def _private_dir(path):
    path = Path(path)
    if path.is_symlink():
        raise PermissionError("DEVELOPMENT_DIR_ALIAS")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077):
        raise PermissionError("DEVELOPMENT_DIR_NOT_PRIVATE")
    return path



def _explicit_review_source_repo(owner_repo, record):
    """Bind a *signed individual review* to its same verified source checkout.

    An owner checkout missing the reviewed tracked file cannot satisfy a
    previously accepted snapshot from the running immutable Operator. Only
    the independently verified, actually LOADED Operator source can fill
    that gap, with its HEAD and both Git-tracked blobs matching the review.
    A different/dirty local source cannot silently switch authority. A
    standing-scope delegation must NEVER use this fallback.
    """
    owner_repo = Path(owner_repo).resolve(strict=True)
    if record.get("source_origin") != "owner-local-review-v1":
        return owner_repo
    try:
        if __package__:
            from .m1_development_review_candidate import (
                _installed_live_source_repo, _tracked_file)
        else:
            from m1_development_review_candidate import (
                _installed_live_source_repo, _tracked_file)
        # Owner checkout must be clean, just as in select_review_repo().
        if _git(owner_repo, "status", "--porcelain", "--untracked-files=no"):
            return owner_repo
        try:
            _tracked_file(owner_repo, record["target"])
            _tracked_file(owner_repo, record["test"])
        except ValueError as error:
            if error.args != ("CANDIDATE_SOURCE_OR_TEST_UNVERIFIED",):
                return owner_repo
        else:
            # If both paths exist, even a different commit is NOT permission
            # to substitute a newly released branch.
            return owner_repo
        stage = _installed_live_source_repo(owner_repo)
        if (_git(stage, "rev-parse", "HEAD") == record["base_sha"]
                and _tracked_file(stage, record["target"]) ==
                    record["source_sha256"]
                and _tracked_file(stage, record["test"]) ==
                    record["test_sha256"]):
            return stage
    except (OSError, ValueError, PermissionError, RuntimeError, TypeError):
        pass
    # Fails closed through the existing SOURCE_BASE_UNVERIFIED check.
    return owner_repo


def _prepare_workspace(repo, root, record, prior):
    ticket = record["ticket_id"]
    worktrees = _private_dir(root / "development" / "worktrees")
    checkout = worktrees / ticket
    branch = "mcp/" + ticket
    if not checkout.exists():
        # A git worktree from a locally available verified commit. No network,
        # no GitHub Issue, no Actions runner, no model-supplied shell.
        if _git(repo, "cat-file", "-t", record["base_sha"]) != "commit":
            raise ValueError("LOCAL_BASE_COMMIT_MISSING")
        _git(repo, "worktree", "add", "-b", branch, str(checkout),
             record["base_sha"])
    if checkout.is_symlink() or not checkout.is_dir():
        raise ValueError("LOCAL_WORKTREE_UNTRUSTED")
    if _git(checkout, "branch", "--show-current") != branch:
        raise ValueError("LOCAL_WORKTREE_CHANGED")
    current_head = _git(checkout, "rev-parse", "HEAD")
    delivery_started = (len(prior) > 1 and prior[1].status.value
                        in {"RUNNING", "VERIFIED"})
    if current_head != record["base_sha"]:
        # Only the exact one-file child commit created by the existing Draft
        # publisher is allowed for a consumed/uncertain delivery on restart.
        if (not delivery_started
                or _git(checkout, "rev-parse", "HEAD^") != record["base_sha"]
                or _git(checkout, "diff-tree", "--no-commit-id",
                        "--name-only", "-r", "HEAD").splitlines()
                        != [record["target"]]
                or _git(checkout, "status", "--porcelain")):
            raise ValueError("LOCAL_DELIVERY_HEAD_UNVERIFIED")
    changed = _git(checkout, "diff", "--name-only", "HEAD").splitlines()
    # The model must not execute against an extra local Python module,
    # including ignored sitecustomize.py or a staged replacement test.
    # A worktree is acceptable only with the one reviewed source edit.
    untracked = _git(checkout, "ls-files", "--others").splitlines()
    staged = _git(checkout, "diff", "--cached", "--name-only").splitlines()
    if (untracked or staged
            or (changed and (not prior or changed != [record["target"]]))):
        raise ValueError("LOCAL_WORKTREE_DIRTY")
    source = checkout / record["target"]
    test = checkout / record["test"]
    for path in (source, test):
        if (path.is_symlink() or not path.is_file()
                or not path.resolve(strict=True).is_relative_to(checkout)):
            raise ValueError("LOCAL_REVIEWED_SOURCE_UNAVAILABLE")
    if sha256(test.read_bytes()).hexdigest() != record["test_sha256"]:
        raise ValueError("LOCAL_FIXED_TEST_CHANGED")
    if not prior and sha256(source.read_bytes()).hexdigest() != record["source_sha256"]:
        raise ValueError("LOCAL_SOURCE_BASE_CHANGED")
    return checkout, branch


class _NoJobComputeLock:
    # The pinned shared9B adapter holds the canonical compute lease only during
    # its inference. Independent Strata jobs do not need the M1 model slot.
    def hold(self):
        return nullcontext()


class _DiscoveredStrata:
    """Fast exact-model check; a sleeping Windows PC must not burn 300 seconds."""

    def __init__(self, discovery, execution):
        self.discovery = discovery
        self.execution = execution

    def available(self):
        try:
            return any(
                row.binding == "local:mainpc-strata:code-agent"
                and row.health == "ONLINE" and "CODE" in row.capabilities
                and getattr(row, "same_host", True) is False
                for row in self.discovery.candidates())
        except Exception:
            return False

    def chat(self, prompt, model=None):
        if model != "code-agent":
            raise ValueError("STRATA_ALIAS_NOT_AUTHORIZED")
        if not self.available():
            raise RuntimeError("STRATA_DISCOVERY_UNAVAILABLE")
        return self.execution.chat(prompt, model=model)


class _CodeProposal:
    def __init__(self, m1, remote=None, reviewed_prompt_sha256=""):
        self.m1 = m1
        self.remote = remote
        self.reviewed_prompt_sha256 = reviewed_prompt_sha256
        self.last_binding = ""
        self._remote_used = False

    def run(self, request):
        # MainPC is a distinct host, so only the manifest's explicitly
        # reviewed public first prompt may be sent there. A second/repair
        # prompt can include private test failure feedback and stays on M1.
        if self.remote is not None and not self._remote_used:
            self._remote_used = True
            # Exact initial prompt pinned by the reviewed local source and
            # owner instruction, never recomputed from changed untrusted data.
            if (sha256(request.instruction.encode()).hexdigest() !=
                    self.reviewed_prompt_sha256):
                raise PermissionError("STRATA_REVIEWED_PROMPT_CHANGED")
            if contains_sensitive_value(request.instruction):
                raise PermissionError("STRATA_PROMPT_NOT_PUBLIC")
            try:
                answer = self.remote.chat(request.instruction, model="code-agent")
                source = compiled_source(answer)
                self.last_binding = "local:mainpc-strata:code-agent"
                return AgentResult(source)
            except (OSError, ValueError, RuntimeError, KeyError, TypeError):
                pass  # One remote inference attempt, then same-host M1.
        answer = self.m1.chat(request.instruction, model="general")
        source = compiled_source(answer)
        self.last_binding = "local:ollama-shared9b:general"
        return AgentResult(source)



class _CurrentReviewedSourcePort:
    """Keep stale unconsumed tickets from being re-executed after a source merge.

    This only compares the current *installed reviewed checkout* with the
    owner-pinned original source. It cannot prove the remote GitHub main or
    resolve an obsolete task by itself. No model, Work claim or network call.
    """

    def __init__(self, port, *, reviewed_repo, source_hashes, source_roots=None):
        self.port = port
        self.reviewed_repo = Path(reviewed_repo).resolve(strict=True)
        self.source_hashes = dict(source_hashes)
        self.source_roots = {key: Path(root).resolve(strict=True)
                             for key, root in (source_roots or {}).items()}

    def __getattr__(self, name):
        return getattr(self.port, name)

    def status(self, principal, ticket_id):
        current = self.port.status(principal, ticket_id)
        # Historical VERIFIED/FAILED/RUNNING receipts are immutable. Only an
        # unclaimed READY task is subject to current-source admission.
        if current.get("state") != "READY":
            return current
        # The owner CLI and MCP share this gate. A manifest write alone is
        # insufficient when a new MCP request was cancelled during admission.
        prefix = "mcp-development-request:" + sha256(_OWNER.encode()).hexdigest() + ":"
        requests = self.port.work.load(prefix + ticket_id)
        if requests and requests[0].name == "development-request":
            request_state = requests[0].status.value
            if request_state != "VERIFIED":
                return {**current, "state": "REVIEW_REQUIRED" if request_state == "WAITING_HUMAN"
                        else request_state}
        expected = self.source_hashes.get(ticket_id)
        if expected is None:
            return {**current, "state": "SOURCE_BASE_REVIEW_REQUIRED"}
        source_root = self.source_roots.get(ticket_id, self.reviewed_repo)
        path = source_root / self.port.tasks[ticket_id].target
        try:
            if path.is_symlink() or not path.is_file():
                return {**current, "state": "SOURCE_BASE_UNVERIFIED"}
            info = path.stat()
            if info.st_size < 1 or info.st_size > 262144:
                return {**current, "state": "SOURCE_BASE_UNVERIFIED"}
            if not path.resolve(strict=True).is_relative_to(source_root):
                return {**current, "state": "SOURCE_BASE_UNVERIFIED"}
            actual = sha256(path.read_bytes()).hexdigest()
        except (OSError, ValueError):
            return {**current, "state": "SOURCE_BASE_UNVERIFIED"}
        if actual != expected:
            return {**current, "state": "SOURCE_BASE_REVIEW_REQUIRED"}
        return current

    def list_tickets(self, principal, *, authorize_status):
        inventory = self.port.list_tickets(
            principal, authorize_status=authorize_status)
        rows = [self.status(principal, row["ticket_id"])
                for row in inventory["tickets"]]
        return {"tickets": rows, "ticket_count": len(rows)}

    def run(self, principal, ticket_id):
        current = self.status(principal, ticket_id)
        if current.get("state") != "READY":
            return current
        return self.port.run(principal, ticket_id)


class _OwnerScopeBoundPort:
    """Recheck durable owner consent before each new claim or external Draft.

    A revoked/changed delegation does not erase Work history or abort an
    already-running effect. It blocks all *future* run/delivery claims.
    """

    def __init__(self, port, root, grants):
        self.port = port
        self.root = root
        self.grants = dict(grants)

    def __getattr__(self, name):
        return getattr(self.port, name)

    def _active(self, ticket_id):
        ref = self.grants.get(ticket_id)
        if ref is None:
            return True
        from m1_development_scope_delegation import scope_active
        return scope_active(self.root, ref)

    def status(self, principal, ticket_id):
        row = self.port.status(principal, ticket_id)
        if (not self._active(ticket_id) and
                row.get("state") in {"READY", "WAITING_M1", "WAITING_STRATA"}):
            return {"ticket_id": ticket_id, "state": "DELEGATION_REVOKED",
                    "github_published": False}
        return row

    def run(self, principal, ticket_id):
        if not self._active(ticket_id):
            return self.status(principal, ticket_id)
        return self.port.run(principal, ticket_id)

    def authorize_delivery(self, principal, ticket_id):
        return (self._active(ticket_id) and
                self.port.authorize_delivery(principal, ticket_id))

    def deliver(self, principal, ticket_id):
        if not self._active(ticket_id):
            raise PermissionError("DELEGATION_REVOKED")
        return self.port.deliver(principal, ticket_id)

    def list_tickets(self, principal, *, authorize_status):
        inventory = self.port.list_tickets(
            principal, authorize_status=authorize_status)
        return {**inventory, "tickets": [
            self.status(principal, row["ticket_id"])
            for row in inventory["tickets"]]}


def build_development_port(*, root, config, repo, guard):
    """Bind private owner manifest to original Guard and Work, not a new DB."""
    root = Path(root).resolve(strict=True)
    repo = Path(repo).resolve(strict=True)
    records = _strict_json(_owner_manifest(root / "development" / "tickets.json"))
    if (type(records) is not dict or set(records) != {"version", "tickets"}
            or type(records["version"]) is not int or records["version"] != 1
            or type(records["tickets"]) is not list
            or not 1 <= len(records["tickets"]) <= MAX_OWNER_DEVELOPMENT_TICKETS):
        raise ValueError("OWNER_DEVELOPMENT_MANIFEST_INVALID")

    work = SQLiteWorkStore(root / config.work_db)
    m1 = SharedOllama9BExecution(host_lease=HostComputeLease())
    tickets = {}
    source_roots = {}
    local_repo = None
    run_root = _private_dir(root / "development" / "runs")
    for record in records["tickets"]:
        _validate_ticket(record)
        ticket_id = record["ticket_id"]
        if ticket_id in tickets:
            raise ValueError("DUPLICATE_DEVELOPMENT_TICKET")
        job = HostBoundLocalDevelopmentPort._job_id(ticket_id, _OWNER)
        immutable = {k:v for k,v in record.items() if k != "allow_draft_delivery"}
        contract_digest = sha256(json.dumps(
            immutable, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        prior = work.load(job)
        if (prior and prior[0].name !=
                "local-guarded-acceptance:" + contract_digest):
            raise ValueError("DEVELOPMENT_TICKET_CONTRACT_CHANGED")
        source_repo = repo
        if record.get("source_origin") in (
                "owner-local-review-v1", "owner-scope-delegation-v1"):
            if local_repo is None:
                local_repo = _owner_local_repo()
            source_repo = _explicit_review_source_repo(local_repo, record)
            source_roots[ticket_id] = source_repo
        checkout, branch = _prepare_workspace(source_repo, root, record, prior)
        scratch = _private_dir(run_root / ticket_id)
        task = {"recipe": "python-fixed-test", "base": "main",
                "base_sha": record["base_sha"], "target": record["target"],
                "test": record["test"], "test_sha256": record["test_sha256"],
                "instruction": record["instruction"]}
        if (_git(checkout, "rev-parse", "HEAD") != record["base_sha"]
                and len(prior) > 1 and prior[1].status.value
                in {"RUNNING", "VERIFIED"}):
            # No new execution after delivery was claimed. Existing Work
            # state is authoritative; do not re-arm tests at a changed HEAD.
            class _ReadbackOnlyTests:
                def run_acceptance(self, target):
                    raise RuntimeError("DELIVERED_TICKET_CANNOT_EXECUTE")
            tests = _ReadbackOnlyTests()
        else:
            tests = FixedPytest(task, checkout, scratch)
        remote = None
        if record["model"] in ("auto", "strata"):
            # Missing optional owner key/PC connection leaves a usable M1
            # fallback without inventing a remote result or a paid route.
            try:
                rows = [(discovery, execution)
                        for prefix, discovery, execution in
                        load_local_endpoints(root / "local-compute" / "endpoints.json")
                        if prefix == "local:mainpc-strata"
                        and execution.models.get("code-agent") ==
                            "qwen3.8-flash-next-coder-iq1_m"
                        and getattr(execution,"api_key",None)]
                if len(rows) == 1:
                    remote = _DiscoveredStrata(*rows[0])
            except (OSError, ValueError, TypeError, KeyError):
                remote = None
        # Build reference once per bound task, so Strata's exact original
        # prompt SHA checks still cover every byte actually dispatched.
        # Missing package/guide means the historical unmodified instruction.
        bound_instruction = _guided_instruction(record)
        initial_prompt_hash = ""
        if record["model"] in ("auto", "strata"):
            prompt = json.dumps({
                "instruction": bound_instruction,
                "current_source": (checkout / record["target"]).read_text(),
                "test_feedback": "Initial implementation; acceptance has not run.",
                "response_format": "Return only the complete replacement file, without Markdown fences.",
            }, ensure_ascii=False)
            initial_prompt_hash = sha256(prompt.encode()).hexdigest()
        agent = _CodeProposal(m1, remote, initial_prompt_hash)
        tickets[ticket_id] = HostBoundLocalDevelopmentTask(
            ticket_id=ticket_id, principal_id=_OWNER, root=str(checkout),
            instruction=bound_instruction, target=record["target"],
            acceptance_target=record["test"], repository=_REPO,
            branch=branch, proposal_agent=agent, tests=tests,
            lease=_NoJobComputeLock(), max_repairs=1,
            allow_draft_delivery=record.get("allow_draft_delivery", False),
            contract_sha256=contract_digest,
            # The existing CODE loop already runs one independent fixed
            # acceptance after the guarded edit, with exact source readback.
            # A *second* pre-edit test blocked legitimate new work when an
            # old test passed despite unmet instructions and doubled the
            # M1 test cost. Keep immutable source/test admission and Guard;
            # do not run acceptance until there is an actual change.
            baseline_preflight=False,
        )
    port = HostBoundLocalDevelopmentPort(guard=guard, work=work, tasks=tickets)
    port = _CurrentReviewedSourcePort(
        port, reviewed_repo=repo,
        source_hashes={row["ticket_id"]: row["source_sha256"]
                       for row in records["tickets"]},
        source_roots=source_roots)
    strict = {record["ticket_id"] for record in records["tickets"]
              if record["model"] == "strata"}
    local_tickets = {record["ticket_id"]: record["model"]
                     for record in records["tickets"] if record["model"] in {"m1", "auto"}}
    if strict or local_tickets:
        if __package__:
            from .m1_direct_development import StrataReadyPort
        else:
            from m1_direct_development import StrataReadyPort
    if local_tickets:
        def initially_available(ticket_id):
            remote = port.tasks[ticket_id].proposal_agent.remote
            if local_tickets[ticket_id] == "auto" and remote is not None and remote.available():
                return True
            try:
                return any(row.binding == "local:ollama-shared9b:general"
                           and row.health == "ONLINE" and row.same_host is True
                           for row in SharedOllama9BDiscovery()())
            except Exception:
                return False
        # Same admission probe as the active 9B route; execution rechecks
        # under the original lease. Do not consume Work for known pressure.
        if __package__:
            from .m1_direct_development import wake_strata_once
        else:
            from m1_direct_development import wake_strata_once
        port = StrataReadyPort(port, initially_available, local_tickets,
                               waiting_state="WAITING_M1",
                               wake=lambda ticket_id: wake_strata_once(root, ticket_id),
                               wake_first_tickets=tuple(
                                   ticket_id for ticket_id, model in local_tickets.items()
                                   if model == "auto"),
                               wake_tickets=tuple(
                                   ticket_id for ticket_id, model in local_tickets.items()
                                   if model == "auto"))
    if strict:
        # Reuse the owner CLI's existing strict lane for every MCP caller.
        # An unavailable optional PC does not consume Work or start a local model.
        from dataclasses import replace
        if __package__:
            from .m1_direct_development import StrataReadyPort, NoM1Fallback, strata_ready, wake_strata_once
        else:
            from m1_direct_development import StrataReadyPort, NoM1Fallback, strata_ready, wake_strata_once
        for ticket_id in strict:
            task = port.tasks[ticket_id]
            task.proposal_agent.m1 = NoM1Fallback()
            port.tasks[ticket_id] = replace(task, max_repairs=0)
        port = StrataReadyPort(port, lambda ticket_id:
            port.tasks[ticket_id].proposal_agent.remote is not None and strata_ready(root), strict,
            wake=lambda ticket_id: wake_strata_once(root, ticket_id), wake_tickets=strict)
    delegated = {record["ticket_id"]: record["scope_ref"]
                 for record in records["tickets"]
                 if record.get("source_origin") == "owner-scope-delegation-v1"}
    return _OwnerScopeBoundPort(port, root, delegated) if delegated else port


