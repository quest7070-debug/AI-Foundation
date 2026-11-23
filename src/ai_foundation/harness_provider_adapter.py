"""Harness-owned FREE provider proposal routing; no separate development scheduler.

This adapter plugs into the existing CodingSpecialist.develop AgentPort. It
never receives filesystem, shell, approval, Git delivery or test authority.
Only a trusted local reviewer may authorize the exact CODE prompt for egress.
The canonical Guard, ComputeRouter, FreeRouteAdmission and durable inference
attempt store remain the authorities for each request.

The native Harness CLI remains the local fallback and local final review.
No cloud route can run if a Free account receipt is missing.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
import json
import re
import subprocess

from .agent import AgentRequest, AgentResult
from .cloud_execution import CloudResponse, ObservedCloudExecution
from .compute_routing import ComputeRouter
from .core import CanonContract, TaskPlan
from .inference_service import GuardedInferenceService
from .model_work_roles import ModelWorkContract, ModelWorkRole
from .provider_catalog import spec
from .provider_observer import ProviderResponseObserver
from .harness_service_registry import HarnessServiceAdapter, HarnessServiceRegistry

_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
_MAX_PROMPT = 4096
_MAX_REPLY = 262144


def compiled_source(value):
    """One strict source validator for local and outside Harness proposals."""
    if type(value) is not str or not value or len(value.encode()) > _MAX_REPLY:
        raise ValueError("HARNESS_PUBLIC_SOURCE_INVALID")
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        decoded = value
    if type(decoded) is not str:
        raise ValueError("HARNESS_PUBLIC_TEXT_REQUIRED")
    # Strip a single Markdown code fence if present
    lines = decoded.splitlines()
    if (
        len(lines) >= 2
        and lines[0].lstrip().startswith("```")
        and lines[-1].strip() == "```"
    ):
        decoded = "\n".join(lines[1:-1])
    # Validate Python source
    tree = ast.parse(decoded)
    compile(decoded, "<harness-proposal>", "exec")
    if not tree.body or not any(not isinstance(node, ast.Expr) for node in tree.body):
        raise ValueError("HARNESS_SOURCE_IS_ONLY_A_LITERAL")
    return decoded


class GroqHarnessIPv4Transport:
    """Single host-reviewed CODE proposal; no generic model/tool/agent tunnel."""

    def __init__(self, *, runner=subprocess.run):
        self.runner = runner

    def send(self, provider, secret, payload):
        pinned = spec("GROQ")
        if provider != "GROQ" or not pinned or pinned.endpoint != _GROQ_URL:
            raise ValueError("GROQ_HARNESS_PROVIDER_NOT_PINNED")
        if type(secret) is not str or not re.fullmatch(
                r"gsk_[0-9A-Za-z_-]{16,}", secret):
            raise ValueError("GROQ_HARNESS_KEY_UNAVAILABLE")
        if type(payload) is not dict or set(payload) != {"messages", "model"}:
            raise ValueError("GROQ_HARNESS_PAYLOAD_UNBOUND")
        messages = payload["messages"]
        if (payload["model"] != pinned.model or type(messages) is not list
                or len(messages) != 1 or type(messages[0]) is not dict
                or set(messages[0]) != {"role", "content"}
                or messages[0]["role"] != "user"
                or type(messages[0]["content"]) is not str
                or not 0 < len(messages[0]["content"]) <= _MAX_PROMPT):
            raise ValueError("GROQ_HARNESS_PROMPT_NOT_BOUNDED")
        # Provider-side execution limits never use automatic premium-tier choice.
        body = json.dumps({
            "model": pinned.model,
            "messages": messages,
            "max_completion_tokens": 4096,
            "temperature": 0,
            "service_tier": "on_demand",
        }, separators=(",", ":"), ensure_ascii=True)
        # Body is a host-reviewed public fixture/task only. The key remains in
        # native Keychain until curl takes its stdin; never argv or disk.
        argv = [
            "/usr/bin/curl", "-q", "--ipv4", "--silent", "--show-error",
            "--connect-timeout", "5", "--max-time", "50",
            "--max-filesize", str(_MAX_REPLY), "--proto", "=https",
            "--request", "POST",
            "--header", "Content-Type: application/json",
            "--header", "Accept: application/json",
            "--data-binary", body, "--output", "-",
            "--write-out", "\n%{http_code}", "--config", "-", _GROQ_URL,
        ]
        # No retry, redirect, paid fallback or proxy bypass.
        key_config = ('header = "Authorization: Bearer ' + secret + '"\n').encode()
        try:
            result = self.runner(
                argv, input=key_config, capture_output=True,
                timeout=55, check=False)
        except (OSError, subprocess.SubprocessError):
            raise RuntimeError("GROQ_HARNESS_REQUEST_UNCERTAIN") from None
        if result.returncode != 0 or not isinstance(result.stdout, bytes):
            raise RuntimeError("GROQ_HARNESS_REQUEST_UNCERTAIN")
        raw, divider, code = result.stdout.rpartition(b"\n")
        if (not divider or len(raw) > _MAX_REPLY or
                not re.fullmatch(rb"[1-5][0-9]{2}", code)):
            raise RuntimeError("GROQ_HARNESS_RESPONSE_UNUSABLE")
        try:
            return CloudResponse(int(code), {}, raw.decode("utf-8"))
        except UnicodeError:
            raise RuntimeError("GROQ_HARNESS_RESPONSE_UNUSABLE") from None


@dataclass
class _LocalHarnessExecution:
    harness: object

    def chat(self, text, model=None):
        # Preserves the existing sandboxed local CLI Harness proposal path.
        return self.harness.run(AgentRequest(text)).output


class _HarnessServiceRouter:
    """Filter canonical ComputeRouter choices through reviewed service adapters.

    Unsupported, unapproved, expired, paid or model-drifted services are
    excluded per decision. A local-only route is returned without consulting
    external adapters; local compute remains the canonical fallback.
    """
    def __init__(self, base, settings, services):
        self.base = base
        self.settings = settings
        self.services = services

    def choose(self, function="CODE", **kwargs):
        from .compute_routing import ComputeRoute
        excluded = set(kwargs.pop("exclude", ()))
        for _ in range(32):
            route = self.base.choose(function, exclude=excluded, **kwargs)
            if not route.binding or route.kind != "CLOUD":
                return route
            meta = self.settings.registry.credential(route.binding)
            if self.services.admitted(
                    meta, self.settings.free_route, capability=function):
                return route
            excluded.add(route.binding)
        return ComputeRoute(None, None)

    def record_runtime(self, *args):
        return self.base.record_runtime(*args)


def default_harness_services(*, opencode_host_port=None,
                             opencode_review=None):
    """Default Groq + explicitly host-bound, admitted OpenCode CLI service.

    A missing actual account/sandbox receipt or missing host port leaves the
    OpenCode backend absent. Research candidates never auto-enable a route.
    """
    pinned = spec("GROQ")
    adapters = [HarnessServiceAdapter(
        provider=pinned.name, model=pinned.model,
        endpoint=pinned.endpoint,
        transport_factory=GroqHarnessIPv4Transport,
    )]
    if opencode_host_port is not None:
        from .opencode_harness_service import reviewed_opencode_execution_factory
        factory = reviewed_opencode_execution_factory(
            port=opencode_host_port, review=opencode_review)
        if factory is not None:
            opencode = spec("OPENCODE")
            adapters.append(HarnessServiceAdapter(
                provider=opencode.name, model=opencode_review.model,
                endpoint=opencode.endpoint, transport_factory=factory,
            ))
    return HarnessServiceRegistry(adapters)


class HarnessManagedProposalAgent:
    """Drop-in proposal AgentPort for the existing guarded development loop.

    Trusted host provides a callback implementing local 9B sensitivity review
    for the exact per-attempt prompt and another callback for local final
    review of outside proposals. Both are required; model output cannot
    generate these credentials. The existing tests and Draft publisher remain
    downstream of this AgentPort.
    """
    def __init__(self, *, job_id, canon, inference, local_review,
                 local_final_review):
        if not (type(job_id) is str and job_id.strip()
                and isinstance(canon, CanonContract)
                and callable(local_review) and callable(local_final_review)):
            raise ValueError("HARNESS_TRUSTED_HOST_BINDINGS_REQUIRED")
        if getattr(inference, "attempts", None) is None:
            raise ValueError("HARNESS_DURABLE_CLOUD_ATTEMPTS_REQUIRED")
        self.job_id = job_id
        self.canon = canon
        self.inference = inference
        self.local_review = local_review
        self.local_final_review = local_final_review
        self._attempt = 0

    def run(self, request):
        if not isinstance(request, AgentRequest):
            raise TypeError("HARNESS_AGENT_REQUEST_REQUIRED")
        if self._attempt >= 3:
            raise RuntimeError("HARNESS_REPAIR_BUDGET_EXHAUSTED")
        self._attempt += 1
        prompt = request.instruction
        try:
            contract = self.local_review(prompt)
        except Exception:
            # Classification failure cannot authorize cloud egress.
            contract = None
        if (not isinstance(contract, ModelWorkContract)
                or contract.role != ModelWorkRole.FOUNDATION_DEVELOPMENT):
            contract = ModelWorkContract(ModelWorkRole.LOCAL_DEVELOPMENT)
        plan = TaskPlan(
            run_id=self.job_id + ":" + str(self._attempt),
            action="compute", target="llm",
            text=prompt, privacy_text=prompt,
            paid_cost=0, canon_revision=self.canon.revision,
            effect_id=self.job_id + ":proposal:" + str(self._attempt),
        )
        outcome = self.inference.run(plan, self.canon, function="CODE",
                                     role_contract=contract)
        if outcome.status != "VERIFIED_COMPLETE" or not outcome.result:
            raise RuntimeError("HARNESS_PROPOSAL_" + outcome.status)
        source = compiled_source(outcome.result)
        if outcome.route_kind == "CLOUD":
            # The trusted local reviewer makes final acceptance, not Groq.
            try:
                accepted = self.local_final_review(prompt, source)
            except Exception:
                accepted = False
            if accepted is not True:
                raise RuntimeError("HARNESS_LOCAL_FINAL_REVIEW_REQUIRED")
        return AgentResult(source)


def create_harness_managed_agent(*, job_id, canon, guard, settings,
                                 local_registry, local_harness,
                                 durable_attempts, local_review,
                                 local_final_review, service_adapters=None,
                                 opencode_host_port=None, opencode_review=None,
                                 opencode_reasoning_ranking=None,
                                 opencode_admitted_models=(),
                                 local_execution_by_prefix=()):
    """Compose only existing Guard/route owners; cannot issue Free grants."""
    if getattr(settings, "free_route", None) is None:
        raise ValueError("HARNESS_FREE_ADMISSION_REQUIRED")
    if not durable_attempts:
        raise ValueError("HARNESS_DURABLE_CLOUD_ATTEMPTS_REQUIRED")
    if opencode_reasoning_ranking is not None:
        from .dsh_opencode_acp import first_admitted_llmperks_opencode
        # External ordering is never its own account admission. Only a host
        # pinned to the highest already-admitted model may be registered.
        try:
            candidate = first_admitted_llmperks_opencode(
                opencode_reasoning_ranking, opencode_admitted_models)
        except (ValueError, TypeError):
            # Publisher shape/rank changes cannot abort local development.
            candidate = None
        if (candidate is None or opencode_review is None
                or opencode_review.model != candidate):
            opencode_host_port = None
            opencode_review = None
    services = (default_harness_services(
                    opencode_host_port=opencode_host_port,
                    opencode_review=opencode_review)
                if service_adapters is None else service_adapters)
    if not isinstance(services, HarnessServiceRegistry):
        raise TypeError("HARNESS_REVIEWED_SERVICE_REGISTRY_REQUIRED")
    # Do not advertise a remote-local binding without a real execution port.
    # Otherwise a selected "Strata" route would be falsely served by M1.
    # This is a view over existing candidate discovery, not a second registry.
    class _BoundExecutionCandidates:
        def candidates(self):
            return tuple(candidate for candidate in local_registry.candidates()
                if getattr(candidate, 'same_host', True) is True or any(
                    candidate.binding == prefix or
                    candidate.binding.startswith(prefix + ":")
                    for prefix, _execution in local_execution_by_prefix))
    router = _HarnessServiceRouter(
        ComputeRouter(settings, _BoundExecutionCandidates()), settings, services)
    # The former local adapter ignored the selected local binding/model and
    # always called the M1 Harness. Dispatch explicitly bound MainPC Strata
    # candidates to their real OpenAI execution, retaining M1 fallback.
    from .openai_local_adapter import LocalExecutionDispatcher
    if (not isinstance(local_execution_by_prefix, (tuple, list))
            or any(type(item) not in (tuple, list) or len(item) != 2
                   or type(item[0]) is not str or not item[0].startswith("local:")
                   or not callable(getattr(item[1], "chat", None))
                   for item in local_execution_by_prefix)):
        raise ValueError("HOST_BOUND_LOCAL_EXECUTIONS_REQUIRED")
    execution = LocalExecutionDispatcher(
        _LocalHarnessExecution(local_harness), tuple(local_execution_by_prefix))

    def cloud_factory(binding):
        meta = settings.registry.credential(binding)
        if not services.admitted(meta, settings.free_route, capability="CODE"):
            raise PermissionError("HARNESS_CLOUD_SERVICE_NOT_ADMITTED")
        if meta["provider"] == "OPENCODE":
            # OpenCode is a sandboxed *CLI* backend. Never load an API secret
            # into an HTTP transport or infer that provider name is approval.
            from .opencode_harness_service import OpenCodeHarnessCLIExecution
            execution = services.transport(meta, settings.free_route)
            if not isinstance(execution, OpenCodeHarnessCLIExecution):
                raise PermissionError("OPENCODE_CLI_HOST_EXECUTION_REQUIRED")
            return execution
        return ObservedCloudExecution(
            settings.registry, settings.secret_store,
            ProviderResponseObserver(settings.registry),
            services.transport(meta, settings.free_route),
            admission=settings.free_route)
    inference = GuardedInferenceService(
        guard, router, execution, cloud_factory=cloud_factory,
        attempts=durable_attempts)
    return HarnessManagedProposalAgent(
        job_id=job_id, canon=canon, inference=inference,
        local_review=local_review, local_final_review=local_final_review)
