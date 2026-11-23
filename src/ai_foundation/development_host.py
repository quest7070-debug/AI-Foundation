"""Host entrypoint joining existing Harness, guarded CODE and Draft delivery."""
from dataclasses import dataclass
from pathlib import Path
import subprocess
import ast
import json
import re
from .agent_tools import GuardedToolGateway
from .core import TaskPlan
from .agent import AgentResult
from .development_git_delivery import GitDraftPublisher


_FAILURE_TOKEN = re.compile(r"[A-Z][A-Z0-9_]{2,63}")


def _failure_result(exc):
    """Ledger-safe failure label for a development run.

    Keeps the exception type, plus - for ValueError only - a code-shaped
    token authored by the task/recipe layer (for example
    FIXED_TEST_INFRASTRUCTURE_FAILED), so the owner can tell an acceptance
    infrastructure failure from a moved base or a missing file. Free text,
    paths and model/test-runner output are never persisted: only the token
    before the first ':' is kept, and only when it is a single upper-case
    code containing an underscore.
    """
    name = type(exc).__name__
    if isinstance(exc, ValueError):
        token = str(exc).split(":", 1)[0].strip()
        if "_" in token and _FAILURE_TOKEN.fullmatch(token):
            return name + ":" + token
    return name


def _failure_code(result):
    """Public failure_code for a persisted FAILED step result."""
    allowed = {
        "LOCAL_ACCEPTANCE_NOT_VERIFIED", "RuntimeError", "ValueError",
        "PermissionError", "TimeoutError", "SyntaxError", "OSError",
        "KeyError", "TypeError", "ModuleNotFoundError",
    }
    if type(result) is not str:
        return "UNCLASSIFIED_FAILURE"
    if result in allowed:
        return result
    head, sep, token = result.partition(":")
    if (sep and head == "ValueError" and "_" in token
            and _FAILURE_TOKEN.fullmatch(token)):
        return result
    return "UNCLASSIFIED_FAILURE"


@dataclass(frozen=True)
class HarnessProposalAgent:
    """Run a host-pinned no-tool local Harness profile, one proposal per turn.

    Prefix/environment must come from the existing verified Harness owner,
    including Seatbelt, private DSH_HOME and local-only overlay; never model text.
    This adapter neither starts Ollama nor relaxes ownership/lease requirements.
    """
    argv_prefix: tuple[str, ...]
    cwd: str
    env: dict
    timeout_s: int = 3600

    def run(self, request):
        if (not self.argv_prefix or type(self.timeout_s) is not int
                or not 1 <= self.timeout_s <= 3600):
            raise ValueError("INVALID_HARNESS_BINDING")
        # Spool output to files, rather than accumulating unbounded pipe data.
        import tempfile
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            completed=subprocess.run([*self.argv_prefix, request.instruction],
                cwd=self.cwd, env=self.env, stdin=subprocess.DEVNULL,
                stdout=out, stderr=err, check=False, timeout=self.timeout_s)
            if out.tell() > 262144 or err.tell() > 262144:
                raise ValueError("HARNESS_REPLY_TOO_LARGE")
            if completed.returncode:
                # Stderr is untrusted provider/runtime output. It may contain
                # prompts, credentials or paths, so never export its bytes.
                raise RuntimeError("HARNESS_EXIT_NONZERO")
            out.seek(0)
            source=out.read().decode("utf-8")
        # Accept only complete Python source; never feed CLI prose or reasoning
        # into the guarded writer. No automatic Markdown/substring extraction.
        # Headless JSON output encodes the public answer as one JSON string.
        try:
            decoded=json.loads(source)
        except json.JSONDecodeError:
            decoded=source
        if type(decoded) is not str:
            raise ValueError("HARNESS_PUBLIC_TEXT_REQUIRED")
        source=decoded
        tree=ast.parse(source)
        # ast.parse alone accepts invalid module-level 'return', 'break',
        # 'continue' and 'yield'. Compile without execution before giving
        # any proposal to Guard's write port or consuming fixed-test time.
        compile(source, "<harness-proposal>", "exec")
        if not tree.body or not any(not isinstance(node,ast.Expr) for node in tree.body):
            raise ValueError("HARNESS_SOURCE_IS_ONLY_A_LITERAL")
        return AgentResult(source)


def execute_development_task(*, specialist, proposal_agent, instruction, target,
                             acceptance_target, repository, branch, base="main",
                             max_repairs=1, repair_agent=None,
                             review_agent=None, publish_draft=True):
    """Caller retains the existing Native session and host lease for this call.

    Existing host specialist controls Guard, scope and independent tests.
    Only successful tests and readback reach actual Git/Draft publication.
    """
    root=Path(specialist.tools.write_capability.target_root).resolve(strict=True)
    if type(publish_draft) is not bool:
        raise ValueError("INVALID_DELIVERY_MODE")
    publisher=(GitDraftPublisher(root=root,repository=repository,branch=branch,base=base)
               if publish_draft else None)
    return specialist.develop(agent=proposal_agent,instruction=instruction,
        target=target,acceptance_target=acceptance_target,max_repairs=max_repairs,
        publish_draft=publisher, repair_agent=repair_agent,
        review_agent=review_agent)


class LocalDevelopmentGateway(GuardedToolGateway):
    """Trusted local CODE writer using Guard's existing local-only route.

    No decision is overwritten: DENY/WAITING_HUMAN still stop the loop.
    LOCAL_ONLY is executable here because this gateway writes only through the
    host's bound local port, with zero paid cost and no remote write adapter.
    Instantiate only alongside the isolated local filesystem ExecutionPort.
    """
    def write(self, *, run_id, target, content, canon_revision,
              paid_cost=0, effect_id=""):
        if type(paid_cost) is not int or paid_cost != 0:
            raise ValueError("LOCAL_DEVELOPMENT_MUST_BE_FREE")
        plan=TaskPlan(run_id, "write", target, text=content,
                      paid_cost=0, canon_revision=canon_revision,
                      exclusive_target=True, effect_id=effect_id)
        if self.reconciliation_registry is not None:
            if not self.port_binding:
                raise RuntimeError("reconciliation port binding required")
            self.reconciliation_registry.register(
                effect_id or run_id, plan, self.port_binding)
        return self.guard.execute(plan, self.canon, self.port, content,
                                  local_only=True)


@dataclass(frozen=True)
class LocalDevelopmentFilesystem:
    """Local-only read/write port scoped to the existing isolated checkout."""
    root: Path

    def _target(self, plan):
        root=self.root.resolve(strict=True)
        path=Path(plan.target).resolve()
        path.relative_to(root)
        return path

    def observe(self, plan):
        return self._target(plan).read_text(encoding="utf-8")

    def execute(self, plan):
        self._target(plan).write_text(plan.text, encoding="utf-8")


def run_local_development_task(*, root, guard, tests, proposal_agent,
                               lease, instruction, target, acceptance_target,
                               repository, branch, base="main", max_repairs=1,
                               repair_agent=None, review_agent=None,
                               compact_single_edit=False,
                               deliver_to_github=True):
    """Concrete local entry: caller's existing lease covers model through delivery.

    tests must be the host-owned sandboxed fixed acceptance port. No model text
    can choose its command, checkout, provider, lease or publication branch.
    """
    from .agent_tools import CapabilityAgentTools, ReadCapability, WriteCapability
    from .coding import CodingSpecialist
    from .core import CanonContract
    root=Path(root).resolve(strict=True)
    gateway=LocalDevelopmentGateway(guard,CanonContract("foundation-code","code-v1"),
                                    LocalDevelopmentFilesystem(root))
    tools=CapabilityAgentTools(gateway,branch,"code-v1",
                               ReadCapability(str(root)),WriteCapability(str(root)))
    specialist=CodingSpecialist(tools,tests)
    # An explicit trusted-host opt-in only. Existing worker calls and
    # default full-source Harness behavior are unchanged.
    if type(compact_single_edit) is not bool:
        raise ValueError("INVALID_COMPACT_EDIT_OPT_IN")
    if compact_single_edit:
        if type(proposal_agent) is not HarnessProposalAgent:
            raise ValueError("COMPACT_EDIT_REQUIRES_BOUND_HARNESS")
        from .development_compact_edit import (
            CompactEditProposalAgent, OwnerBoundHarnessTextAgent,
            OneFastThenDeepAgent,
        )
        original = proposal_agent
        proposal_agent = OneFastThenDeepAgent(
            CompactEditProposalAgent(OwnerBoundHarnessTextAgent(
                original.argv_prefix, original.cwd, original.env, original.timeout_s)),
            original,
        )
        # Repair uses the existing full-file Harness whenever the host has not
        # specified its own reviewed REPAIR role; never retry the fast adapter.
        if repair_agent is None:
            repair_agent = original
    with lease.hold():
        return execute_development_task(
            specialist=specialist,proposal_agent=proposal_agent,
            instruction=instruction,target=target,acceptance_target=acceptance_target,
            repository=repository,branch=branch,base=base,max_repairs=max_repairs,
            repair_agent=repair_agent,review_agent=review_agent,
            publish_draft=deliver_to_github)

def run_harness_managed_development_task(*, root, guard, tests, local_harness,
                                         local_registry, settings,
                                         durable_attempts, local_review,
                                         local_final_review, lease,
                                         instruction, target,
                                         acceptance_target, repository,
                                         branch, base="main", max_repairs=1,
                                         job_id, service_adapters=None,
                                         development_lease=None,
                                         deliver_to_github=True,
                                         local_execution_by_prefix=()):
    """Managed Harness route; same Guard, fixed tests, local 9B and Draft PR.

    A trusted host must supply account-accepted settings, a native local
    Harness agent, and *real local* data/final reviewers. These cannot be
    replaced by Groq responses or inferred from the task's public label.
    No new scheduler, write capability or deployment/merge authority.
    """
    from .harness_provider_adapter import create_harness_managed_agent
    from .core import CanonContract
    if type(max_repairs) is not int or not 0 <= max_repairs <= 2:
        raise ValueError("INVALID_REPAIR_BUDGET")
    # The job lease protects the Draft workflow; the 9B lease is acquired
    # only for an actual local fallback, so a free cloud call does not
    # needlessly occupy or wait for the resident local model.
    job_lease = lease
    if development_lease is not None:
        if development_lease is lease:
            raise ValueError("SEPARATE_DEVELOPMENT_LEASE_REQUIRED")
        job_lease = development_lease
        original_local_harness = local_harness
        class _LeaseBoundLocalHarness:
            def run(self, request):
                with lease.hold():
                    return original_local_harness.run(request)
        local_harness = _LeaseBoundLocalHarness()
    agent = create_harness_managed_agent(
        job_id=job_id, canon=CanonContract("foundation-code", "code-v1"),
        guard=guard, settings=settings, local_registry=local_registry,
        local_harness=local_harness, durable_attempts=durable_attempts,
        local_review=local_review, local_final_review=local_final_review,
        service_adapters=service_adapters,
        local_execution_by_prefix=local_execution_by_prefix,
    )
    # Existing host-owned lease/Guard/tests and GitDraftPublisher are
    # unchanged. No direct service invocation bypasses this route.
    return run_local_development_task(
        root=root, guard=guard, tests=tests, proposal_agent=agent,
        lease=job_lease, instruction=instruction, target=target,
        acceptance_target=acceptance_target, repository=repository,
        branch=branch, base=base, max_repairs=max_repairs,
        deliver_to_github=deliver_to_github,
    )



@dataclass(frozen=True)
class HostBoundLocalDevelopmentTask:
    """Trusted host admission; the MCP caller supplies only this ticket ID.

    All capability, checkout, target, acceptance, model, lease and instruction
    bindings are selected before the external agent invokes the MCP tool.
    """
    ticket_id: str
    principal_id: str
    root: str
    instruction: str
    target: str
    acceptance_target: str
    repository: str
    branch: str
    proposal_agent: object
    tests: object
    lease: object
    max_repairs: int = 1
    repair_agent: object = None
    allow_draft_delivery: bool = False
    contract_sha256: str = ""
    baseline_preflight: bool = False


class HostBoundLocalDevelopmentPort:
    """One-shot local CODE execution on existing Guard, Work and Harness.

    A cancelled, failed, running or verified ticket is never automatically
    reclaimed. The host owns tickets and Work storage; this is not a new queue
    or scheduler. No GitHub API is contacted for proposal/repair/test.
    """

    def __init__(self, *, guard, work, tasks):
        import re
        if (not callable(getattr(guard, "execute", None))
                or not callable(getattr(work, "ensure", None))
                or not callable(getattr(work, "transition", None))
                or type(tasks) is not dict or not 1 <= len(tasks) <= 32):
            raise ValueError("TRUSTED_LOCAL_DEVELOPMENT_BINDING_REQUIRED")
        for key, task in tasks.items():
            if (type(task) is not HostBoundLocalDevelopmentTask
                    or type(key) is not str or key != task.ticket_id
                    or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", key)
                    or type(task.principal_id) is not str or not task.principal_id
                    or type(task.instruction) is not str or not task.instruction.strip()
                    or len(task.instruction) > 4000
                    or type(task.branch) is not str or not task.branch
                    or task.branch in {"main", "master"}
                    or type(task.allow_draft_delivery) is not bool
                    or type(task.baseline_preflight) is not bool
                    or (task.contract_sha256 != "" and (
                        type(task.contract_sha256) is not str or
                        re.fullmatch(r"[a-f0-9]{64}", task.contract_sha256) is None))
                    or type(task.max_repairs) is not int
                    or not 0 <= task.max_repairs <= 2
                    or not callable(getattr(task.lease, "hold", None))
                    or not callable(getattr(task.proposal_agent, "run", None))):
                raise ValueError("INVALID_HOST_DEVELOPMENT_TICKET")
            for item in (task.target, task.acceptance_target):
                path = Path(item)
                if (type(item) is not str or not item or path.is_absolute()
                        or ".." in path.parts):
                    raise ValueError("EXACT_RELATIVE_DEVELOPMENT_TARGET_REQUIRED")
            if task.target == task.acceptance_target:
                raise ValueError("INDEPENDENT_DEVELOPMENT_ACCEPTANCE_REQUIRED")
            root = Path(task.root).resolve(strict=True)
            if not root.is_dir():
                raise ValueError("ISOLATED_DEVELOPMENT_CHECKOUT_REQUIRED")
        self.guard = guard
        self.work = work
        self.tasks = dict(tasks)

    @staticmethod
    def _job_id(ticket_id, principal_id):
        from hashlib import sha256
        return "mcp-local-development:" + sha256(
            json.dumps([principal_id, ticket_id], separators=(",", ":")).encode()).hexdigest()

    @staticmethod
    def _step_names(task):
        from hashlib import sha256
        stable = [task.principal_id, task.ticket_id, task.root,
                  task.instruction, task.target, task.acceptance_target,
                  task.repository, task.branch, task.max_repairs]
        digest = task.contract_sha256 or sha256(json.dumps(
            stable, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return ["local-guarded-acceptance:" + digest, "git-draft-delivery"]

    def _bound(self, principal, ticket_id):
        if type(ticket_id) is not str:
            raise PermissionError("UNAUTHORIZED_DEVELOPMENT_TICKET")
        task = self.tasks.get(ticket_id)
        if task is None or task.principal_id != getattr(principal, "principal_id", None):
            raise PermissionError("UNAUTHORIZED_DEVELOPMENT_TICKET")
        return task

    def authorize(self, principal, ticket_id):
        return (type(ticket_id) is str and ticket_id in self.tasks
                and self.tasks[ticket_id].principal_id ==
                getattr(principal, "principal_id", None))

    def authorize_delivery(self, principal, ticket_id):
        return (self.authorize(principal, ticket_id)
                and self.tasks[ticket_id].allow_draft_delivery is True)

    def authorize_list(self, principal):
        return any(self.authorize(principal, ticket_id) for ticket_id in self.tasks)

    def list_tickets(self, principal, *, authorize_status):
        """Bounded owner inventory; no Work creation, claim, model or GitHub call."""
        if not self.authorize_list(principal):
            raise PermissionError("UNAUTHORIZED_DEVELOPMENT_INVENTORY")
        rows = []
        for ticket_id in sorted(self.tasks):
            if (self.authorize(principal, ticket_id)
                    and authorize_status(ticket_id) is True):
                rows.append(self.status(principal, ticket_id))
        return {"tickets": rows, "ticket_count": len(rows)}

    def status(self, principal, ticket_id):
        from .orchestration import WorkStatus
        task = self._bound(principal, ticket_id)
        job = self._job_id(task.ticket_id, task.principal_id)
        steps = self.work.load(job)
        if not steps:
            return {"ticket_id": ticket_id, "state": "READY", "github_published": False}
        if (len(steps) != 2
                or [step.name for step in steps] != self._step_names(task)):
            return {"ticket_id": ticket_id, "state": "RECONCILE_REQUIRED",
                    "github_published": False}
        step, delivery = steps[0], steps[1]
        # Do not export source, prompts, private checkout paths or test logs.
        if step.status is WorkStatus.VERIFIED:
            try:
                receipt = json.loads(step.result)
                import re
                from hashlib import sha256
                if (receipt.get("status") == "TESTED_CHANGE"
                        and type(receipt.get("sha256")) is str
                        and re.fullmatch(r"[a-f0-9]{64}", receipt["sha256"])):
                    root = Path(task.root).resolve(strict=True)
                    source = (root / task.target).resolve(strict=True)
                    source.relative_to(root)
                    if sha256(source.read_bytes()).hexdigest() != receipt["sha256"]:
                        return {"ticket_id": ticket_id,
                                "state": "SOURCE_CHANGED_RECONCILE_REQUIRED",
                                "github_published": False}
                    response = {"ticket_id": ticket_id, "state": "VERIFIED_LOCAL",
                                "source_sha256": receipt["sha256"],
                                "github_published": False}
                    if receipt.get("execution_binding") in {
                            "local:llama-swap:local-code-agent",
                            "local:ollama-shared9b:general",
                            "local:mainpc-strata:code-agent"}:
                        response["execution_binding"] = receipt["execution_binding"]
                    if delivery.status is WorkStatus.VERIFIED:
                        import re
                        if (type(delivery.result) is str and re.fullmatch(
                                "https://github.com/" + re.escape(task.repository)
                                + r"/pull/[1-9][0-9]*", delivery.result)):
                            response["github_published"] = True
                            response["draft_pr_url"] = delivery.result
                        else:
                            response["delivery_state"] = "RECONCILE_REQUIRED"
                    elif delivery.status is WorkStatus.RUNNING:
                        response["delivery_state"] = "RECONCILE_REQUIRED"
                    elif delivery.status is WorkStatus.FAILED:
                        response["delivery_state"] = "FAILED_REVIEW_REQUIRED"
                    return response
            except (OSError, ValueError, TypeError, AttributeError):
                pass
            return {"ticket_id": ticket_id, "state": "RECONCILE_REQUIRED"}
        state = {
            WorkStatus.PLANNED: "READY",
            WorkStatus.RUNNING: "RUNNING_OR_RECONCILE_REQUIRED",
            WorkStatus.WAITING_HUMAN: "WAITING_HUMAN",
            WorkStatus.FAILED: "FAILED_REVIEW_REQUIRED",
            WorkStatus.CANCELLED: "CANCELLED",
        }.get(step.status, "RECONCILE_REQUIRED")
        # Passing the original fixed tests is only a review hint, not CODE
        # delivery evidence or proof the entire instruction is fulfilled.
        if (step.status is WorkStatus.WAITING_HUMAN and step.result in {
                "BASELINE_ALREADY_PASSES_REVIEW_REQUIRED",
                "BASELINE_PREFLIGHT_UNVERIFIED"}):
            state = step.result
        response = {"ticket_id": ticket_id, "state": state, "github_published": False}
        if step.status is WorkStatus.FAILED:
            # Work saves a fixed failure class or local acceptance code, not
            # provider stderr or the owner's instruction. Never reveal unknown
            # historical text through the public MCP status/inventory.
            response["failure_code"] = _failure_code(step.result)
        return response

    def run(self, principal, ticket_id):
        from .orchestration import WorkStatus
        task = self._bound(principal, ticket_id)
        job = self._job_id(task.ticket_id, task.principal_id)
        self.work.ensure(job, self._step_names(task))
        # Only explicitly owner-reviewed tickets can opt into original-source
        # fixed acceptance before any model or CODE claim. Do not re-check
        # already consumed/failed/uncertain Work under another principal.
        if task.baseline_preflight:
            saved = self.work.load(job)
            if not saved or saved[0].status is not WorkStatus.PLANNED:
                return self.status(principal, ticket_id)
            from .development_loop import TestAcceptanceReceipt
            try:
                baseline = task.tests.run_acceptance(task.acceptance_target)
                trusted = (isinstance(baseline, TestAcceptanceReceipt)
                           and type(baseline.passed) is bool
                           and type(baseline.detail) is str)
            except Exception:
                trusted = False
                baseline = None
            if not trusted or baseline.passed:
                # A passing test can miss instruction requirements. Do not
                # grant VERIFIED_LOCAL or Draft; hold for explicit review.
                # Invalid test evidence must fail closed. Neither case
                # stores private runner output or calls a model.
                reason = ("BASELINE_ALREADY_PASSES_REVIEW_REQUIRED"
                          if trusted else "BASELINE_PREFLIGHT_UNVERIFIED")
                self.work.transition(job, 0, WorkStatus.PLANNED,
                                     WorkStatus.WAITING_HUMAN, reason)
                return self.status(principal, ticket_id)
        # Only a fresh host-authored ticket can start. No uncertain-model
        # retry even when an MCP timeout hides a completed edit or test.
        if not self.work.transition(job, 0, WorkStatus.PLANNED,
                                    WorkStatus.RUNNING):
            return self.status(principal, ticket_id)
        try:
            result = run_local_development_task(
                root=task.root, guard=self.guard, tests=task.tests,
                proposal_agent=task.proposal_agent, lease=task.lease,
                instruction=task.instruction, target=task.target,
                acceptance_target=task.acceptance_target,
                repository=task.repository, branch=task.branch,
                max_repairs=task.max_repairs, deliver_to_github=False,
                repair_agent=task.repair_agent)
        except Exception as exc:
            # Never persist error messages from a model/CLI/test runner;
            # only the code-shaped label from _failure_result is stored.
            self.work.transition(job, 0, WorkStatus.RUNNING,
                                 WorkStatus.FAILED, _failure_result(exc))
            return self.status(principal, ticket_id)
        if result.status == "TESTED_CHANGE" and isinstance(result.source_sha256, str):
            binding = getattr(task.proposal_agent, "last_binding", "")
            receipt = {"status": "TESTED_CHANGE", "sha256": result.source_sha256}
            if binding in {"local:llama-swap:local-code-agent",
                           "local:ollama-shared9b:general",
                           "local:mainpc-strata:code-agent"}:
                receipt["execution_binding"] = binding
            receipt = json.dumps(receipt, sort_keys=True)
            self.work.transition(job, 0, WorkStatus.RUNNING,
                                 WorkStatus.VERIFIED, receipt)
        else:
            self.work.transition(job, 0, WorkStatus.RUNNING,
                                 WorkStatus.FAILED, "LOCAL_ACCEPTANCE_NOT_VERIFIED")
        return self.status(principal, ticket_id)

    def deliver(self, principal, ticket_id):
        """One separately owner-authorized Draft; no edit/model/test replay.

        A lost Git acknowledgment can still mean a published remote effect.
        Retain the durable RUNNING claim for reconciliation, never resend.
        """
        from .orchestration import WorkStatus
        task = self._bound(principal, ticket_id)
        if not task.allow_draft_delivery:
            raise PermissionError("DRAFT_DELIVERY_NOT_OWNER_AUTHORIZED")
        observed = self.status(principal, ticket_id)
        if observed.get("state") != "VERIFIED_LOCAL" or observed.get("github_published"):
            return observed
        job = self._job_id(task.ticket_id, task.principal_id)
        if not self.work.transition(job, 1, WorkStatus.PLANNED,
                                    WorkStatus.RUNNING):
            return self.status(principal, ticket_id)
        try:
            publisher = GitDraftPublisher(
                root=task.root, repository=task.repository,
                branch=task.branch, base="main")
            ref = publisher(target=task.target,
                            source_sha256=observed["source_sha256"])
            import re
            if (type(ref) is not str or re.fullmatch(
                    "https://github.com/" + re.escape(task.repository)
                    + r"/pull/[1-9][0-9]*", ref) is None):
                return self.status(principal, ticket_id)
            self.work.transition(job, 1, WorkStatus.RUNNING,
                                 WorkStatus.VERIFIED, ref)
        except Exception:
            # Remote commit / push / PR might already exist. No blind retry.
            return self.status(principal, ticket_id)
        return self.status(principal, ticket_id)

