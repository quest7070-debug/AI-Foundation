import json
import re
import secrets
import hmac
import hashlib
from pathlib import Path
from http.server import BaseHTTPRequestHandler
from .bounded_http import BoundedThreadingHTTPServer
from urllib.parse import urlparse,unquote,parse_qs
from .operator import snapshot, OperatorReadError, CachedServiceProbe
from .task_intake import TaskIntake
from .human_operations import tasks as human_tasks,notices as human_notices
from .human_view import from_snapshot as human_view
from .human_renderer import render as render_semantic
from .notification_dismissal import NotificationDismissals
from .presentation import PresentationPreferences,THEMES

def cached_owner_development_status(reader):
    """One bounded owner observation without lock-held host I/O.

    The real owner callback can check launchd, local DB, and ToolHive status.
    Concurrent HTTP callers must get an explicitly unverified observation,
    never block on its execution or start a duplicate host probe.
    """
    from threading import Lock
    from time import monotonic
    lock = Lock()
    state = {"value": None, "until": 0.0, "busy": False}

    def observe():
        with lock:
            if state["value"] is not None and monotonic() < state["until"]:
                return state["value"]
            if state["busy"]:
                return {"state": "UNAVAILABLE", "queue_state": "UNAVAILABLE"}
            state["busy"] = True
        try:
            fresh = reader()
            with lock:
                state["value"] = fresh
                state["until"] = monotonic() + 30.0
            return fresh
        finally:
            with lock:
                state["busy"] = False

    return observe


_SUBJECT=re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$')
class OperatorApplication:
    def __init__(self, config, actions, native_credentials=None, required_bindings=(), csrf_token=None, settings=None, reconciliation=None, local_compute=None, inference=None, inference_dispatch=None, auto_agent_factory=None, service_probes=None, backup_dir=None, update_stage=None, human_input=None, activity=None, chat_url='', capability_factory=None, storage_admission=None, operational_notices=None, tracer=None, question_resolver=None, question_authority=None, host_question_resolver=None, mcp_owner_delegations=None, research_ledger=None, development_status=None, development_review=None, klm_review=None):
        self.config = config
        self.actions = actions
        self.native_credentials = native_credentials
        self.required_bindings = required_bindings
        # Polling must never repeat six complete SQLite integrity scans on
        # every HTTP request. Guard and Work state below remain live.
        from .preflight import CachedPreflight, preflight
        self.cached_preflight = CachedPreflight(
            lambda: preflight(config, native_credentials, required_bindings))
        self.csrf_token = csrf_token or secrets.token_urlsafe(32)
        self.settings = settings
        # Read-only source research; never an executable route or approval.
        self.research_ledger = research_ledger
        self.reconciliation = reconciliation
        self.local_compute = local_compute
        self.inference = inference
        from .openai_compat import OpenAICompat
        self.openai = OpenAICompat(inference,inference_dispatch,auto_agent_factory,tracer=tracer) if inference is not None else None
        # Read-only in-process wiring evidence. The trusted source marks the
        # precise callback passed to OpenAICompat. Never use this bit for
        # decisions, activation, owner identity or access to a View.
        registered = getattr(self.openai, 'auto_agent_factory', None)
        self.humanmodel_factory_registered = bool(
            callable(registered) and
            getattr(registered, '_foundation_owner_humanmodel_factory', None) is True)
        # Service health is tri-state. Never classify an overlapping check
        # or failed observation as a real service outage. The same ten-second
        # one-flight observation is shared by HTTP, the UI and MCP.
        self.service_probes = (
            {name: CachedServiceProbe(callback)
             for name, callback in service_probes.items()}
            if service_probes else service_probes
        )
        self.backup_dir = backup_dir
        self.update_stage = update_stage
        self.human_input = human_input
        self.activity = activity
        self.chat_url = chat_url
        self.capability_factory = capability_factory
        self.operational_notices = operational_notices
        # Trusted in-process M1 observation callback; never an HTTP input or grant.
        self.development_status = development_status if callable(development_status) else None
        # Trusted owner-local review adapter; HTTP cannot supply a reader or path.
        self.development_review = development_review
        self.klm_review = klm_review if callable(klm_review) else None
        self.question_resolver = question_resolver
        self.question_authority = question_authority
        # In-process producer only; NEVER expose this callback via HTTP.
        self.host_question_resolver = host_question_resolver
        # Existing Operator UI is the only issuer. Never accept grants from
        # MCP JSON, model output, tool descriptions or untrusted HTTP headers.
        self.mcp_owner_delegations = mcp_owner_delegations
        has_work_store = hasattr(config, 'data_dir') and hasattr(config, 'work_db')
        work_path = Path(config.data_dir) / config.work_db if has_work_store else None
        from .klm_status import CachedKlmLifecycleStatus
        self.klm_lifecycle_status = CachedKlmLifecycleStatus(work_path) if work_path else None
        self.intake = TaskIntake(work_path,storage_admission=storage_admission) if work_path else None
        self.dismissals = NotificationDismissals(work_path,storage_admission=storage_admission) if work_path else None
        self.presentation = PresentationPreferences(Path(config.data_dir) / 'presentation.json',storage_admission=storage_admission) if hasattr(config, 'data_dir') else None
        if self.intake:self.intake.purge_terminal()
    def resolve_attested_question(self, bundle, authority):
        """Only trusted native in-process producers may invoke this callback.

        The unauthenticated loopback /internal/kandev/question route continues
        using question_resolver, which never accesses private HumanModel data.
        """
        if self.host_question_resolver is None:
            raise RuntimeError('authenticated host question producer unavailable')
        return self.host_question_resolver(bundle, authority)

    def snapshot(self):
        return snapshot(
            self.config, self.native_credentials, self.required_bindings,
            self.service_probes, self.backup_dir, self.update_stage,
            preflight_report=self.cached_preflight())
    def credential_token(self,binding): return hmac.new(self.csrf_token.encode(),binding.encode(),hashlib.sha256).hexdigest()[:24]
    def binding_for_token(self,token):
        if not self.settings or not hasattr(self.settings,'credentials'): return None
        for c in self.settings.credentials():
            if secrets.compare_digest(self.credential_token(c['binding']),token): return c['binding']
        return None
    def capability_execution_paths(self):
        """Human-visible host-owned execution wiring, separate from LLM fallback policy."""
        executor=getattr(self,'capability_executor',None)
        if not self.capability_factory or executor is None:
            return {}
        paths={'DATA':('Bounded Compute',)}
        # Inference-backed capabilities are advertised only when a live eligible
        # route exists. Metadata or a stale persisted primary is not availability.
        if self.settings is not None and hasattr(self.settings,'choose_route'):
            if self.settings.choose_route('SEARCH'): paths['SEARCH']=()
        # CODE is currently a host-bound repo/test workflow; it does not consume
        # an LLM route merely because models advertise CODE capability.
        if getattr(executor,'repo_port',None) is not None or getattr(executor,'file_port',None) is not None:
            paths['CODE']=('ToolHive MCP',)
        if getattr(executor,'file_port',None) is not None:
            paths['FILES']=('ToolHive MCP',)
        if (
            getattr(executor,'vision_port',None) is not None
            and self.settings is not None
            and hasattr(self.settings,'choose_route')
            and self.settings.choose_route('VISION')
        ):
            paths['VISION']=('Vision Adapter',)
        return paths

    def _notice_rows(self,snap):
        rows=tuple(human_notices(snap))
        if self.operational_notices:
            try: rows=rows+tuple(self.operational_notices())
            except Exception: pass
        return tuple(sorted(rows,key=lambda n:(-n.level,-n.updated_at,n.subject)))
    def development_state(self, snap):
        """Only current Guard/Work observations, never assumed host availability.

        The Operator does not own the local9B task selector or HumanModel View.
        Until a trusted installed-host producer supplies independent evidence,
        neither may be represented as online or owner-approved in Settings.
        """
        observed = snap.as_dict()
        approvals = tuple(x for x in observed.get("attention", ())
                          if isinstance(x, dict) and x.get("kind") == "approval")
        actionable = sum(bool(x.get("approval_ref")) for x in approvals)
        work = observed.get("work") or {}
        result = {
            "source": "CURRENT_GUARD_WORK_SNAPSHOT",
            "guard_pending": len(approvals),
            "guard_actionable": actionable,
            "guard_unbound": len(approvals) - actionable,
            "work_running": int(work.get("RUNNING", 0)),
            "work_waiting_human": int(work.get("WAITING_HUMAN", 0)),
            "work_failed": int(work.get("FAILED", 0)),
            "work_uncertain": int(work.get("UNCERTAIN", 0)),
            "local9b_worker": "UNVERIFIED",
            "local9b_queue_state": "UNAVAILABLE",
            "local9b_queued_count": None,
            "local9b_last_failure_code": None,
            "eligible_recipes": None,
            "approved_humanmodel_view": "UNVERIFIED",
            "klm_status": "UNVERIFIED",
            "klm_coverage": "UNVERIFIED",
            "klm_changes": "UNVERIFIED",
            "klm_folders": None,
            "klm_objects": None,
            "klm_pages": None,
            "klm_lifecycle_state": "UNVERIFIED",
            "klm_lifecycle_observed_at": None,
            "klm_lifecycle_snapshot_age_seconds": None,
            "klm_atoms": None,
            "klm_missing_features": None,
            "klm_unresolved_reviews": None,
            "klm_relations": None,
            "klm_failed_intake": None,
            "direct_mcp_status": "UNVERIFIED",
            "direct_mcp_running": None,
            "direct_mcp_verified_receipts": None,
            "direct_mcp_failed": None,
            "direct_mcp_last_route": "UNVERIFIED",
            "direct_mcp_updated_at": None,
            "code_review_required": None,
            "code_admitted_requests": None,
            "code_failed_local_attempts": None,
            "humanmodel_factory_registered": self.humanmodel_factory_registered,
            # In-process callback wiring only: not a grant, View read or
            # proof of installed commit identity. Never invoke either callback.
            "legacy_question_resolver_enabled": self.question_resolver is not None,
            "host_question_resolver_registered": callable(self.host_question_resolver),
        }
        # The installed owner host may supply the existing bounded M1 worker
        # probe. Never derive worker health from issue count, HTTP headers or
        # a stale model route; a failure leaves the original unverified state.
        lifecycle_reader = getattr(self, "klm_lifecycle_status", None)
        if callable(lifecycle_reader):
            lifecycle = lifecycle_reader()
            fields = ("atoms", "missing_features", "unresolved_reviews",
                      "relations", "failed_intake")
            if (type(lifecycle) is dict and lifecycle.get("state") == "OBSERVED"
                    and all(type(lifecycle.get(k)) is int
                            and 0 <= lifecycle[k] <= 100000 for k in fields)):
                result["klm_lifecycle_state"] = "OBSERVED"
                result.update({"klm_" + k: lifecycle[k] for k in fields})
                # Fixed owner-local reason buckets only; no private atom IDs,
                # source text, review decisions or implicit accepted links.
                triage = lifecycle.get("review_triage")
                triage_keys = {"conflict", "revision", "qualifier",
                               "dependency", "difference", "duplicate", "other"}
                if (type(triage) is dict and set(triage) == triage_keys
                        and all(type(n) is int and 0 <= n <= 100000
                                for n in triage.values())
                        and sum(triage.values()) == lifecycle["unresolved_reviews"]):
                    result["klm_review_triage"] = dict(triage)
                # The DB read time and monotonic cache age describe only this
                # local index snapshot, not the age of the upstream Drive data.
                observed_at = lifecycle.get("observed_at")
                age = lifecycle.get("snapshot_age_seconds")
                if type(observed_at) is int and 0 < observed_at < 253402300800:
                    result["klm_lifecycle_observed_at"] = observed_at
                if type(age) is int and 0 <= age <= 30:
                    result["klm_lifecycle_snapshot_age_seconds"] = age
        if self.development_status is None:
            return result
        try:
            observed_worker = self.development_status()
        except Exception:
            return result
        if type(observed_worker) is not dict:
            return result
        # Direct-MCP receipts come only from the same Work DB and disclose
        # fixed aggregate codes. They do not prove an active remote caller,
        # current source still matching, or installed/executed Strata.
        direct=observed_worker.get("direct_mcp")
        if type(direct) is dict and direct.get("state") in {
                "WORK_RECEIPTS_ONLY", "NO_WORK_RECEIPTS"}:
            valid=True
            for field in ("running", "verified_receipts", "failed"):
                value=direct.get(field)
                if type(value) is not int or not 0 <= value <= 32:
                    valid=False
            route=direct.get("last_route")
            if route not in ("UNVERIFIED", "M1", "STRATA") or type(route) is not str:
                valid=False
            timestamp=direct.get("updated_at")
            if timestamp is not None and (
                    type(timestamp) not in (int,float) or timestamp < 0):
                valid=False
            if valid:
                result["direct_mcp_status"]=direct["state"]
                result["direct_mcp_running"]=direct["running"]
                result["direct_mcp_verified_receipts"]=direct["verified_receipts"]
                result["direct_mcp_failed"]=direct["failed"]
                result["direct_mcp_last_route"]=route
                result["direct_mcp_updated_at"]=timestamp
        # Owner Work-only CODE backlog from the SAME installed 30s status
        # producer. These counts are not an execution grant or a claim that
        # a current ticket can be retried, delivered or released.
        backlog = observed_worker.get("development_backlog")
        if (type(backlog) is dict
                and backlog.get("source") == "CURRENT_OWNER_WORK"):
            names = (("review_required", "code_review_required"),
                     ("admitted", "code_admitted_requests"),
                     ("failed_local_attempts", "code_failed_local_attempts"))
            if all(type(backlog.get(source)) is int
                   and 0 <= backlog[source] <= 100000
                   for source, _ in names):
                for source, target in names:
                    result[target] = backlog[source]
        # M1 owner status is a fixed label + private report read, not a new
        # deployment grant, current source version or 9B inference receipt.
        # Freshness must be explicit; old, malformed or missing reports never
        # become an optimistic green KLM status on the dashboard.
        klm = observed_worker.get("klm")
        if type(klm) is dict and klm.get("fresh") is True:
            code = klm.get("status")
            if type(code) is str and code in {
                    "CURRENT", "RESYNC_PARTIAL", "REPLAY_PARTIAL",
                    "RESCAN_REQUIRED", "NOT_DUE", "DRIVE_AUTH_REQUIRED",
                    "HOST_BINDING_BLOCKED", "POLL_FAILED",
                    "SYNC_ACTIVE_OR_RECONCILE_REQUIRED",
                    "CLOCK_RECONCILE_REQUIRED"}:
                result["klm_status"] = code
                # Explicit bounded data from the SAME current owner report.
                for key, allowed in (
                        ("coverage", {"COMPLETE", "PARTIAL", "UNKNOWN"}),
                        ("changes", {"COMPLETE", "PARTIAL", "RESCAN_REQUIRED"})):
                    value = klm.get(key)
                    if type(value) is str and value in allowed:
                        result["klm_" + key] = value
                for key in ("folders", "objects", "pages"):
                    value = klm.get(key)
                    if type(value) is int and 0 <= value <= 100000:
                        result["klm_" + key] = value
        # HumanModel view state comes from the same cached owner probe:
        # a read-only look at the bound ledger view's stale flag. Anything
        # unobserved or malformed stays UNVERIFIED.
        humanmodel = observed_worker.get("humanmodel")
        if type(humanmodel) is dict:
            view_state = humanmodel.get("view")
            if view_state in {"AVAILABLE", "STALE", "BLOCKED"}:
                result["approved_humanmodel_view"] = view_state
        # Eligible recipes come from the same cached owner probe: a bounded
        # content check of the recipe module installed beside the worker.
        # Unobserved or malformed values stay None (shown as UNVERIFIED).
        recipes = observed_worker.get("recipes")
        if type(recipes) is dict:
            eligible = recipes.get("eligible")
            if type(eligible) is int and 0 <= eligible <= 16:
                result["eligible_recipes"] = eligible
        state = observed_worker.get("state")
        queue = observed_worker.get("queue_state")
        if state not in {"RUNNING", "RECONCILE_REQUIRED", "LAST_EXIT_NONZERO",
                         "SCHEDULED_IDLE", "UNKNOWN"} or type(state) is not str:
            return result
        if queue not in {"RUNNING", "RECONCILE_REQUIRED", "WORKER_EXIT_NONZERO",
                         "QUEUED_NOT_RUNNING", "NO_QUEUED_TASK",
                         "LOCAL_WORK_CYCLE_OBSERVED", "SCHEDULED_CYCLE_BLOCKED",
                         "UNAVAILABLE", "UNKNOWN"} or type(queue) is not str:
            return result
        result["source"] = "CURRENT_GUARD_WORK_SNAPSHOT+M1_OWNER_RUNTIME"
        result["local9b_worker"] = state
        result["local9b_queue_state"] = queue
        intake = observed_worker.get("intake")
        if (queue in {"QUEUED_NOT_RUNNING", "NO_QUEUED_TASK"}
                and type(intake) is dict):
            count = intake.get("queued_count")
            if type(count) is int and 0 <= count <= 100:
                result["local9b_queued_count"] = count
        failure = observed_worker.get("last_failure")
        if type(failure) is dict:
            code = failure.get("error_code")
            if type(code) is str and re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", code):
                result["local9b_last_failure_code"] = code
        return result

    def human_payload(self):
        snap=self.snapshot()
        all_notice_rows=self._notice_rows(snap)
        notice_rows=all_notice_rows
        if self.dismissals: notice_rows=tuple(n for n in notice_rows if not self.dismissals.hidden(n.subject,n.status))
        task_rows=human_tasks(self.intake) if self.intake else ()
        cards=self.settings.cards() if self.settings and hasattr(self.settings,'cards') else ()
        routes=self.settings.routes() if self.settings and hasattr(self.settings,'routes') else ()
        activity=self.activity.current() if self.activity else ()
        view=human_view(snap,notices=notice_rows,tasks=task_rows)
        # FAILED remains real even if its notice was dismissed. These
        # bounded snapshot-window counts reveal no subjects or source data.
        attention=snap.as_dict().get('attention') or ()
        state_diagnostics={
            'failed_work_window': sum(type(x) is dict and x.get('kind')=='work'
                                      and x.get('status')=='FAILED' for x in attention),
            'failed_effect_window': sum(type(x) is dict and x.get('kind')=='effect'
                                        and x.get('status')=='FAILED' for x in attention),
            'dismissed_failed_notices_window': (
                sum(n.status=='FAILED' for n in all_notice_rows)
                - sum(n.status=='FAILED' for n in notice_rows)),
        }
        return {'development':self.development_state(snap),'state':view.state,
                'runtime_health': view.runtime_health,
                'state_diagnostics':state_diagnostics,'severity_counts':view.severity_counts,'notices':[n.__dict__ for n in notice_rows],'tasks':[t.__dict__ for t in task_rows],'providers':[c.__dict__ for c in cards],'routes':[r.__dict__ for r in routes],'services':list(getattr(snap,'services',())),'activity':[a.__dict__ for a in activity]}
    def compact_human_status(self, *, echo=False):
        """Bounded polling projection; never send notification/answer text.

        The keyed revision only signals that the existing presentation has
        changed. It is not an authority token or evidence of owner consent.
        Existing clients may still request the full legacy /api/human data.
        """
        payload = self.echo_human_payload() if echo else self.human_payload()
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':')).encode('utf-8')
        revision = hmac.new(self.csrf_token.encode('utf-8'), raw,
                            hashlib.sha256).hexdigest()[:32]
        return {
            'schema': 1,
            'state': payload['state'],
            'runtime_health': payload['runtime_health'],
            'severity_counts': payload['severity_counts'],
            'state_diagnostics': payload.get('state_diagnostics', {}),
            'notices_in_window': len(payload['notices']),
            'revision': revision,
            'source_window_bounded': True,
        }

    def human_notice_page(self, *, after=0, revision=None):
        """Explicit bounded local answer page, not the 5-second poll.

        Offset continuation is pinned to a keyed snapshot revision. If Work
        changes mid-page, reject rather than skip or misidentify a notice.
        This pages the existing bounded Operator projection; it does not
        imply complete historical Work coverage.
        """
        if type(after) is not int or not 0 <= after <= 4096:
            raise ValueError('invalid notice offset')
        if revision is not None and (type(revision) is not str
                                     or re.fullmatch('[0-9a-f]{32}', revision) is None):
            raise ValueError('invalid notice revision')
        if after and revision is None:
            raise ValueError('notice continuation requires exact revision')
        notices = self.human_payload()['notices']
        raw = json.dumps(notices, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':')).encode('utf-8')
        current = hmac.new(self.csrf_token.encode('utf-8'), raw,
                           hashlib.sha256).hexdigest()[:32]
        if revision is not None and not secrets.compare_digest(revision, current):
            raise ValueError('stale notice revision')
        if after > len(notices):
            raise ValueError('notice offset beyond current projection')
        page = []
        size = 8192
        for row in notices[after:after + 6]:
            length = len(json.dumps(row, ensure_ascii=False,
                                    separators=(',', ':')).encode('utf-8'))
            if length + 8192 > 192 * 1024:
                raise ValueError('one notice exceeds fixed page budget')
            if size + length > 192 * 1024:
                break
            page.append(row)
            size += length
        next_offset = after + len(page)
        return {
            'schema': 1, 'revision': current, 'after': after,
            'next_after': next_offset if next_offset < len(notices) else None,
            'notices_in_window': len(notices),
            'source_window_bounded': True, 'notices': page,
        }

    def echo_human_payload(self):
        """Echo polls only its constrained presentation, never private answers."""
        payload = self.human_payload()
        fields = ('level', 'kind', 'subject', 'status', 'summary_ja', 'detail_ja',
                  'updated_at')
        return {**{key: payload[key] for key in
                   ('state', 'runtime_health', 'severity_counts')},
                'notices': [{key: row.get(key) for key in fields}
                            for row in payload['notices']]}
    def provider_services_payload(self):
        """Read-only service-first projection; no raw Keychain aliases or keys."""
        from dataclasses import asdict
        services = (self.settings.services() if self.settings and
                    hasattr(self.settings, 'services') else ())
        return {'schema': 1, 'provider_services': [
            asdict(service) for service in services]}

    def harness_service_payload(self):
        """Observe eligible Harness service candidates; never activate a route."""
        if self.settings and hasattr(self.settings, 'harness_services_status'):
            ledger = getattr(self, 'research_ledger', None)
            if ledger is not None:
                return self.settings.harness_services_status(
                    research_ledger=ledger)
            return self.settings.harness_services_status()
        if self.settings and hasattr(self.settings, 'harness_service_status'):
            return self.settings.harness_service_status()
        return {'schema': 2, 'manager': 'FOUNDATION_HARNESS',
                'services': [], 'state': 'NOT_CONFIGURED'}

    def page(self,surface="responsive"):
        snap = self.snapshot()
        cards = self.settings.cards() if self.settings and hasattr(self.settings, 'cards') else []
        task_rows=human_tasks(self.intake) if self.intake else ()
        notice_rows=self._notice_rows(snap)
        if self.dismissals: notice_rows=tuple(n for n in notice_rows if not self.dismissals.hidden(n.subject,n.status))
        route_snapshots = self.settings.routes() if self.settings and hasattr(self.settings, 'routes') else ()
        raw_credentials = self.settings.credentials() if self.settings and hasattr(self.settings,'credentials') else ()
        credential_rows = tuple({k:v for k,v in c.items() if k!='binding'} | {'action_token':self.credential_token(c['binding'])} for c in raw_credentials)
        local_rows = self.local_compute.candidates() if self.local_compute and hasattr(self.local_compute,'candidates') else ()
        route_label=self.settings.route_label if self.settings and hasattr(self.settings,'route_label') else None
        reconcilable={n.subject for n in notice_rows if n.status=='UNCERTAIN' and self.reconciliation is not None and getattr(self.reconciliation,'can_reconcile',lambda _x:False)(n.subject)}
        html = render_semantic(human_view(snap, notices=notice_rows, tasks=task_rows, providers=cards, routes=route_snapshots, credentials=credential_rows, local_compute=local_rows, activity=(self.activity.current() if self.activity else ()), route_label=route_label, execution_paths=(self.capability_execution_paths() if hasattr(self,'capability_execution_paths') else {}), development=self.development_state(snap)), surface, self.csrf_token, reconcilable, self.presentation.get() if self.presentation else 'I', self.human_input is not None, self.chat_url,mcp_owner_delegation=self.mcp_owner_delegations is not None)

        # The unified owner notification surface already provides the only
        # human actions: AUTHORIZE, DENY and RESPOND (additional instruction).
        # Do not add separate CODE/KLM review links into DEVELOPMENT. Historic
        # protected review endpoints remain internal for existing receipts,
        # but normal delegated development is driven by the MCP CODE cycle.
        return html

    def klm_review_error(self, error):
        # Only fixed host-provided categories may leave the owner exception boundary.
        reason=str(error)
        allowed=getattr(self.klm_review,'public_errors',())
        return reason if reason in allowed else 'KLM_REVIEW_UNAVAILABLE'

    def act(self,action,subject,approval_ref=''):
        subject=unquote(subject)
        if subject in {'.','..'} or not _SUBJECT.fullmatch(subject): raise ValueError('invalid subject')
        if action=='approve':
            guard=getattr(self.actions,'guard',None)
            store=getattr(guard,'store',None)
            if store is not None and hasattr(store,'approve_pending'):
                result=self.actions.approve_pending(subject,approval_ref)
            else:
                # Legacy in-memory fixtures; production uses a durable Guard.
                result=self.actions.approve_run(subject)
            # The installed host may wake its existing maintenance loop.
            # Only that fixed loop independently consumes an exact release.
            wake=getattr(self,'guard_decision_wake',None)
            if result.ok and callable(wake):
                try:wake()
                except Exception:pass
            # Approval is useful only if the exact paused intake resumes through the same guarded path.
            if result.ok and self.intake is not None and self.inference is not None:
                try:self.intake.execute(subject,self.inference,authority_resumed=True)
                except KeyError:pass
            return result
        if action=='cancel':
            guard=getattr(self.actions,'guard',None)
            store=getattr(guard,'store',None)
            if store is not None and hasattr(store,'has_pending') and (store.has_pending(subject) or approval_ref):
                result=self.actions.deny_pending(subject,approval_ref)
            else:
                result=self.actions.cancel_run(subject)
            if result.ok and self.intake is not None:
                try:
                    rows=self.intake.store.load(subject)
                    if rows:
                        from .orchestration import WorkStatus
                        self.intake.store.set(subject,rows[-1].position,WorkStatus.CANCELLED,'CANCELLED')
                        self.intake.purge_terminal()
                except KeyError:pass
            return result
        raise ValueError('unsupported operator action')

def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        def _send(self,status,body,content_type):
            raw=body.encode('utf-8'); self.send_response(status); self.send_header('Content-Type',content_type); self.send_header('Content-Length',str(len(raw))); self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff'); self.send_header('Content-Security-Policy',"default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'"); self.end_headers(); self.wfile.write(raw)
        def do_GET(self):
            try:
                return self._read_get()
            except OperatorReadError:
                # Durable Guard/Work database contention is not an empty or
                # healthy UI state. Surface a bounded 503 without private
                # filesystem paths, statements, or automatic action retries.
                self._send(503,'{"error":"operator snapshot unavailable"}\n',
                           'application/json; charset=utf-8')

        def _read_get(self):
            host=self.headers.get('Host',''); host_name=host.rsplit(':',1)[0].strip('[]').lower()
            if host_name not in {'127.0.0.1','localhost','::1'}: self._send(403,'forbidden\n','text/plain; charset=utf-8'); return
            route=urlparse(self.path).path
            if route in ('/klm/review','/development/review'):
                self._send(503,'review pages frozen\n','text/plain; charset=utf-8'); return
            if route=='/klm/review':
                if app.klm_review is None:
                    self._send(503,'review unavailable\n','text/plain; charset=utf-8'); return
                try:
                    query=parse_qs(urlparse(self.path).query)
                    if (set(query)-{'after'} or any(len(v)!=1 for v in query.values())
                            or ('after' in query and re.fullmatch('[0-9a-f]{64}',query['after'][0]) is None)):
                        raise ValueError('invalid review cursor')
                    from .klm_review_renderer import render_klm_review
                    listing=app.klm_review().list_reviews(limit=25,after=query.get('after',[''])[0])
                    theme=app.presentation.get() if app.presentation else 'I'
                    self._send(200,render_klm_review(app.csrf_token,listing=listing,theme=theme),'text/html; charset=utf-8')
                except Exception as error:
                    self._send(409,app.klm_review_error(error)+'\n','text/plain; charset=utf-8')
                return
            if route=='/development/review':
                if app.development_review is None:
                    self._send(503,'review unavailable\n','text/plain; charset=utf-8'); return
                from .development_review_renderer import render_review
                try:
                    statuses = app.development_review.pending_review_statuses()
                except Exception:
                    # No private paths, request text or owner DB messages.
                    self._send(503,'owner review queue unavailable\n',
                               'text/plain; charset=utf-8'); return
                self._send(200,render_review(app.csrf_token,
                    delegation_status=app.development_review.delegation_status(),
                    pending_ids=tuple(row["ticket_id"] for row in statuses),
                    pending_states={row["ticket_id"]:row["state"] for row in statuses}),
                    'text/html; charset=utf-8'); return
            if route=='/v1/models':
                models=('foundation-auto','foundation-search','foundation-code','foundation-data','foundation-files','foundation-vision')
                self._send(200,json.dumps({'object':'list','data':[{'id':model,'object':'model','owned_by':'ai-foundation'} for model in models]})+'\n','application/json; charset=utf-8'); return
            if route=='/presentation/theme':
                theme=app.presentation.get() if app.presentation else 'I'
                self._send(200,json.dumps({'theme':theme})+'\n','application/json; charset=utf-8'); return
            if route=='/api/human/status':
                self._send(200,json.dumps(app.compact_human_status(),ensure_ascii=False)+'\n','application/json; charset=utf-8'); return
            if route=='/api/human/echo/status':
                self._send(200,json.dumps(app.compact_human_status(echo=True),ensure_ascii=False)+'\n','application/json; charset=utf-8'); return
            if route=='/api/human/notices':
                try:
                    query=parse_qs(urlparse(self.path).query,keep_blank_values=True)
                    if set(query)-{'after','revision'} or any(len(v)!=1 for v in query.values()):
                        raise ValueError('invalid notice query')
                    cursor=query.get('after',['0'])[0]
                    if re.fullmatch(r'(0|[1-9][0-9]{0,3})',cursor) is None:
                        raise ValueError('invalid notice cursor')
                    revision=query.get('revision',[None])[0]
                    result=app.human_notice_page(after=int(cursor),revision=revision)
                    self._send(200,json.dumps(result,ensure_ascii=False)+'\n','application/json; charset=utf-8')
                except ValueError:
                    self._send(409,'{"error":"notice page cursor stale or over budget"}\n','application/json; charset=utf-8')
                return
            if route=='/api/human':
                self._send(200,json.dumps(app.human_payload(),ensure_ascii=False)+'\n','application/json; charset=utf-8'); return
            if route=='/api/human/echo':
                self._send(200,json.dumps(app.echo_human_payload(),ensure_ascii=False)+'\n','application/json; charset=utf-8'); return
            if route=='/api/provider-services':
                self._send(200,json.dumps(app.provider_services_payload(),ensure_ascii=False)+'\n','application/json; charset=utf-8'); return
            if route=='/api/harness-services':
                self._send(200,json.dumps(app.harness_service_payload(),ensure_ascii=False)+'\n','application/json; charset=utf-8'); return
            if route=='/mobile': self.send_response(308); self.send_header('Location','/'); self.send_header('Cache-Control','no-store'); self.send_header('Content-Length','0'); self.end_headers(); return
            surfaces={'/':'responsive','/echo':'echo'}
            if route not in surfaces: self._send(404,'not found\n','text/plain; charset=utf-8'); return
            self._send(200,app.page(surfaces[route]),'text/html; charset=utf-8')
        def _mutation_response(self,payload,form,status=200):
            return_to=form.get('return_to',[''])[0]
            if return_to in {'/','/echo'}:
                self.send_response(303);self.send_header('Location',return_to);self.send_header('Cache-Control','no-store');self.send_header('Content-Length','0');self.end_headers();return
            self._send(status,json.dumps(payload,ensure_ascii=False)+'\n','application/json; charset=utf-8')
        def do_POST(self):
            host=self.headers.get('Host','')
            host_name=host.rsplit(':',1)[0].strip('[]').lower()
            if host_name not in {'127.0.0.1','localhost','::1'}:
                self._send(403,'{"error":"host rejected"}\n','application/json; charset=utf-8'); return
            origin=self.headers.get('Origin')
            if origin and origin not in {f'http://{host}',f'https://{host}'}:
                self._send(403,'{"error":"origin rejected"}\n','application/json; charset=utf-8'); return
            if self.headers.get('Transfer-Encoding'):
                self._send(411,'{"error":"content-length required"}\n','application/json; charset=utf-8'); return
            try:
                n=int(self.headers.get('Content-Length','0') or 0)
                request_path=urlparse(self.path).path
                max_body=2*1024*1024 if request_path=='/v1/chat/completions' else 8192
                if n<0 or n>max_body: self._send(413,'{"error":"request too large"}\n','application/json; charset=utf-8'); return
                body=self.rfile.read(n).decode('utf-8')
                from urllib.parse import parse_qs
                form=parse_qs(body,keep_blank_values=request_path.startswith('/klm/review/'))
            except (ValueError,UnicodeDecodeError):
                self._send(400,'{"error":"invalid request"}\n','application/json; charset=utf-8'); return
            if request_path=='/internal/kandev/question':
                # This server is loopback-only and Host is already rejected above.
                # Keep this machine-local ingress off the browser CSRF surface:
                # Supervisor is a local service peer, not an operator/browser.
                if app.question_resolver is None:
                    self._send(503,'{"error":"question resolver unavailable"}\n','application/json; charset=utf-8'); return
                try:
                    payload=json.loads(body or '{}')
                    result=app.question_resolver(payload)
                    self._send(200,json.dumps(result,ensure_ascii=False)+'\n','application/json; charset=utf-8')
                except (ValueError,json.JSONDecodeError):
                    self._send(400,'{"error":"invalid question bundle"}\n','application/json; charset=utf-8')
                return
            token=self.headers.get('X-Foundation-CSRF') or form.get('csrf',[''])[0]
            if not secrets.compare_digest(token or '',app.csrf_token):
                self._send(403,'{"error":"csrf rejected"}\n','application/json; charset=utf-8'); return
            if request_path in {'/klm/review/preview','/klm/review/confirm',
                                '/development/review/preview','/development/review/confirm',
                                '/development/review/cancel'}:
                self._send(503,'{"error":"review pages frozen"}\n','application/json; charset=utf-8'); return
            if request_path in {'/development/delegation/enable',
                                '/development/delegation/revoke'}:
                if app.development_review is None:
                    self._send(503,'{"error":"review unavailable"}\n','application/json; charset=utf-8'); return
                try:
                    if request_path.endswith('/enable'):
                        if (set(form) != {'csrf','model','allow_draft_delivery','scope_confirmed'}
                                or any(len(values) != 1 for values in form.values())
                                or form['scope_confirmed'] != ['yes']
                                or form['allow_draft_delivery'][0] not in ('yes','no')):
                            raise PermissionError("EXPLICIT_OWNER_SCOPE_DELEGATION_REQUIRED")
                        result = app.development_review.enable_delegation(
                            model=form['model'][0],
                            allow_draft_delivery=form['allow_draft_delivery'] == ['yes'],
                            scope_confirmed=True)
                    else:
                        if (set(form) != {'csrf','revoke_confirmed'}
                                or any(len(values) != 1 for values in form.values())
                                or form['revoke_confirmed'] != ['yes']):
                            raise PermissionError("EXPLICIT_OWNER_SCOPE_REVOCATION_REQUIRED")
                        result = app.development_review.revoke_delegation(
                            revoke_confirmed=True)
                    self._send(200,json.dumps(result)+'\n','application/json; charset=utf-8')
                except Exception:
                    self._send(409,'{"error":"owner delegation unavailable"}\n',
                               'application/json; charset=utf-8')
                return
            if request_path in {'/development/review/preview','/development/review/confirm','/development/review/cancel'}:
                if app.development_review is None:
                    self._send(503,'{"error":"review unavailable"}\n','application/json; charset=utf-8'); return
                try:
                    fields = ({'csrf','ticket_id'} if request_path.endswith('/preview') else
                              {'csrf','ticket_id','preview_token','withdrawal_confirmed'} if request_path.endswith('/cancel') else
                              {'csrf','ticket_id','preview_token','model','source_reviewed','test_reviewed','public_nonsecret'})
                    if set(form) != fields or any(len(values) != 1 for values in form.values()):
                        raise ValueError('exact review fields required')
                    ticket = form['ticket_id'][0]
                    if request_path.endswith('/preview'):
                        from .development_review_renderer import render_review
                        preview = app.development_review.preview(ticket)
                        self._send(200,render_review(app.csrf_token,preview),'text/html; charset=utf-8')
                    elif request_path.endswith('/cancel'):
                        result = app.development_review.cancel(
                            ticket, preview_token=form['preview_token'][0],
                            withdrawal_confirmed=form['withdrawal_confirmed']==['yes'])
                        self._send(200,json.dumps(result)+'\n','application/json; charset=utf-8')
                    else:
                        result = app.development_review.confirm(
                            ticket, preview_token=form['preview_token'][0], model=form['model'][0],
                            source_reviewed=form['source_reviewed']==['yes'],
                            test_reviewed=form['test_reviewed']==['yes'],
                            public_nonsecret=form['public_nonsecret']==['yes'])
                        self._send(200,json.dumps(result)+'\n','application/json; charset=utf-8')
                except Exception:
                    # Owner instructions/source/exception paths stay on this local preview only.
                    self._send(409,'{"error":"review unavailable, changed or not confirmed"}\n','application/json; charset=utf-8')
                return
            if request_path in {'/klm/review/preview','/klm/review/confirm'}:
                if app.klm_review is None:
                    self._send(503,'{"error":"KLM review unavailable"}\n','application/json; charset=utf-8'); return
                try:
                    fields=({'csrf','review_key'} if request_path.endswith('/preview') else
                            {'csrf','review_key','preview_token','decision','relation_kind','reviewed'})
                    if set(form)!=fields or any(len(v)!=1 for v in form.values()):
                        raise ValueError('exact review fields required')
                    from .klm_review_renderer import render_klm_review
                    theme=app.presentation.get() if app.presentation else 'I'
                    if request_path.endswith('/preview'):
                        preview=app.klm_review().preview(form['review_key'][0])
                        page=render_klm_review(app.csrf_token,preview=preview,theme=theme)
                    else:
                        if form['reviewed']!=['yes']:
                            raise PermissionError('explicit owner decision required')
                        service=app.klm_review()
                        args={'preview_token':form['preview_token'][0],
                              'decision':form['decision'][0],'relation_kind':form['relation_kind'][0]}
                        staged=service.request(form['review_key'][0],**args)
                        if staged['status']=='WAITING_HUMAN':
                            approved=app.actions.approve_pending(staged['run_id'],staged['approval_ref'])
                            if approved.ok is not True:
                                raise PermissionError('exact owner approval rejected')
                        elif staged['status']!='APPROVED':
                            raise PermissionError('exact owner approval unavailable')
                        result=service.resolve(form['review_key'][0],**args)
                        if result.get('status') not in {'RECORDED','ALREADY_RECORDED'}:
                            raise ValueError('review not recorded')
                        page=render_klm_review(app.csrf_token,result=result,theme=theme)
                    self._send(200,page,'text/html; charset=utf-8')
                except Exception as error:
                    self._send(409,json.dumps({'error':app.klm_review_error(error)})+'\n','application/json; charset=utf-8')
                return
            if urlparse(self.path).path=='/v1/chat/completions':
                if app.openai is None:
                    self._send(503,'{"error":{"message":"inference unavailable"}}\n','application/json; charset=utf-8'); return
                try:
                    payload=json.loads(body or '{}')
                    capability_request=None
                    owner=self.headers.get('X-Foundation-Owner','')
                    raw_ids=self.headers.get('X-Foundation-Attachments','')
                    trusted_meta=owner or raw_ids or self.headers.get('X-Foundation-Capability','') or self.headers.get('X-Foundation-Scope','') or self.headers.get('X-Foundation-Long-Running','')
                    if trusted_meta:
                        if not owner: raise ValueError('incomplete trusted capability context')
                        ids=json.loads(raw_ids or '[]')
                        if not isinstance(ids,list): raise ValueError('invalid trusted attachment context')
                        from .capability_request import CapabilityRequest
                        capability_request=CapabilityRequest(owner_id=owner,attachment_ids=tuple(ids))
                    if app.capability_factory is not None:
                        resolving_id='request-'+secrets.token_hex(8)+':resolve'
                        cap_label=(self.headers.get('X-Foundation-Capability','CHAT') or 'CHAT').upper()
                        if app.activity: app.activity.start(resolving_id,cap_label,'request:'+cap_label.lower(),'RESOLVING','RESOLVING')
                        try:
                            capability_request=app.capability_factory(self.headers,payload,capability_request)
                        finally:
                            if app.activity: app.activity.finish(resolving_id)
                    result=app.openai.chat(payload,capability_request)
                    if payload.get('stream') is True:
                        from .openai_compat import as_sse
                        self._send(200,as_sse(result),'text/event-stream; charset=utf-8')
                    else:
                        self._send(200,json.dumps(result,ensure_ascii=False)+'\n','application/json; charset=utf-8')
                except (ValueError,json.JSONDecodeError) as exc:
                    self._send(400,json.dumps({'error':{'message':str(exc)}})+'\n','application/json; charset=utf-8')
                except FileNotFoundError as exc:
                    self._send(404,json.dumps({'error':{'message':str(exc)}})+'\n','application/json; charset=utf-8')
                except PermissionError:
                    self._send(403,'{"error":{"message":"capability denied"}}\n','application/json; charset=utf-8')
                except RuntimeError as exc:
                    from .research_adapter import ResearchGroundingError
                    message='grounded search unavailable' if isinstance(exc,ResearchGroundingError) else 'no eligible compute'
                    self._send(503,json.dumps({'error':{'message':message}})+'\n','application/json; charset=utf-8')
                return
            path=urlparse(self.path).path.strip('/').split('/')
            if path==['settings','routing','optimize']:
                if app.settings is None or not hasattr(app.settings,'optimize_routing'):
                    self._send(409,'{"error":"routing unavailable"}\n','application/json; charset=utf-8'); return
                function=form.get('function',['CHAT'])[0].upper()
                allowed={'CHAT','SEARCH','CODE','DATA','FILES','PC_CONTROL','VISION'}
                if function=='ALL':
                    rows=app.settings.optimize_all_routes()
                    self._mutation_response({'routes':[{'function':r.function,'primary':r.primary,'standby':list(r.standby)} for r in rows]},form); return
                if function not in allowed:
                    self._send(400,'{"error":"invalid function"}\n','application/json; charset=utf-8'); return
                r=app.settings.optimize_routing(function)
                self._mutation_response({'function':r.function,'primary':r.primary,'standby':list(r.standby)},form); return
            if len(path)==4 and path[:3]==['settings','provider','replace']:
                try:
                    if app.settings is None or not hasattr(app.settings,'replace_provider_credential'): raise ValueError('settings unavailable')
                    token=unquote(path[3])
                    if not re.fullmatch(r'[0-9a-f]{24}',token): raise ValueError('invalid credential token')
                    binding=app.binding_for_token(token)
                    if binding is None: raise KeyError(token)
                    result=app.settings.replace_provider_credential(binding,form.get('api_key',[''])[0]); self._mutation_response(result,form)
                except KeyError: self._send(404,'{"error":"credential not found"}\n','application/json; charset=utf-8')
                except (ValueError,RuntimeError): self._send(409,'{"error":"credential update failed"}\n','application/json; charset=utf-8')
                return
            if len(path)==4 and path[:3]==['settings','provider','refresh']:
                try:
                    if app.settings is None or not hasattr(app.settings,'refresh_provider'): raise ValueError('settings unavailable')
                    token=unquote(path[3])
                    if not re.fullmatch(r'[0-9a-f]{24}',token): raise ValueError('invalid credential token')
                    binding=app.binding_for_token(token)
                    if binding is None: raise KeyError(token)
                    result=app.settings.refresh_provider(binding); self._mutation_response(result,form)
                except KeyError: self._send(404,'{"error":"credential not found"}\n','application/json; charset=utf-8')
                except (ValueError,RuntimeError): self._send(409,'{"error":"provider refresh failed"}\n','application/json; charset=utf-8')
                return
            if len(path)==4 and path[:3]==['settings','provider','remove']:
                try:
                    if app.settings is None or not hasattr(app.settings,'remove_provider'): raise ValueError('settings unavailable')
                    token=unquote(path[3])
                    if not re.fullmatch(r'[0-9a-f]{24}',token): raise ValueError('invalid credential token')
                    binding=app.binding_for_token(token)
                    if binding is None: raise KeyError(token)
                    result=app.settings.remove_provider(binding); self._mutation_response(result,form)
                except KeyError: self._send(404,'{"error":"credential not found"}\n','application/json; charset=utf-8')
                except (ValueError,RuntimeError): self._send(409,'{"error":"credential removal failed"}\n','application/json; charset=utf-8')
                return
            if path==['settings','provider','add']:
                try:
                    if app.settings is None: raise ValueError('settings unavailable')
                    api_key=form.get('api_key',[''])[0]; provider=form.get('provider',[''])[0] or None; tier=form.get('tier',['FREE'])[0].upper()
                    if tier not in {'FREE','PAID'}: raise ValueError('invalid tier')
                    result=app.settings.add_provider(api_key,provider,tier); self._mutation_response(result,form,201)
                except ValueError as exc:
                    safe={'credential already registered':'credential already registered','provider selection required':'provider selection required','provider validation transport failed':'provider unreachable','HTTP 401':'credential rejected','HTTP 403':'credential rejected','HTTP 429':'provider rate limited'}
                    raw=str(exc); msg=safe.get(raw, raw if re.fullmatch(r'HTTP [0-9]{3}',raw) else 'provider registration failed')
                    if msg=='provider selection required' and form.get('return_to',[''])[0] in {'/','/echo'}:
                        # Renderer already owns this state via the documented provider_error query contract.
                        self.send_response(303); self.send_header('Location','/?provider_error=selection_required#settings'); self.send_header('Cache-Control','no-store'); self.send_header('Content-Length','0'); self.end_headers()
                    else:
                        self._send(400,json.dumps({'error':msg})+'\n','application/json; charset=utf-8')
                return
            if len(path)==3 and path[:2]==['presentation','theme']:
                theme=path[2].upper()
                if theme=='TOGGLE' and app.presentation is not None:theme='C' if app.presentation.get()=='I' else 'I'
                if app.presentation is None or theme not in THEMES:
                    self._send(400,'{"error":"invalid theme"}\n','application/json; charset=utf-8');return
                app.presentation.set(theme); return_to=form.get('return_to',['/'])[0]; return_to=return_to if return_to in {'/','/echo'} else '/'; self.send_response(303); self.send_header('Location',return_to); self.send_header('Cache-Control','no-store'); self.send_header('Content-Length','0'); self.end_headers(); return
            if len(path)==3 and path[:2]==['notification','dismiss'] and path[2]=='group':
                if app.dismissals is None:
                    self._send(400,'{"error":"invalid notification"}\n','application/json; charset=utf-8'); return
                subjects=[x.strip() for x in form.get('subjects',[''])[0].split('\n') if x.strip()]
                if not subjects or len(subjects)>64 or any(not _SUBJECT.fullmatch(x) for x in subjects):
                    self._send(400,'{"error":"invalid notification"}\n','application/json; charset=utf-8'); return
                current={n.subject:n for n in human_notices(app.snapshot())}
                dismissed=0
                for subj in subjects:
                    notice=current.get(subj)
                    if notice is not None:
                        app.dismissals.dismiss(subj,notice.status);dismissed+=1
                self._mutation_response({'status':'dismissed','count':dismissed},form);return
            if len(path)==3 and path[:2]==['notification','dismiss']:
                subject=unquote(path[2])
                if subject in {'.','..'} or not _SUBJECT.fullmatch(subject) or app.dismissals is None:
                    self._send(400,'{"error":"invalid notification"}\n','application/json; charset=utf-8'); return
                current=next((n for n in human_notices(app.snapshot()) if n.subject==subject),None)
                if current is None:self._send(404,'{"error":"notification not found"}\n','application/json; charset=utf-8');return
                app.dismissals.dismiss(subject,current.status)
                self._mutation_response({'status':'dismissed'},form);return
            if len(path)==3 and path[0]=='action' and path[1]=='promote-question':
                if app.question_authority is None:
                    self._send(409,'{"error":"question authority unavailable"}\n','application/json; charset=utf-8'); return
                try:
                    bundle=json.loads(form.get('bundle',[''])[0]); answers=json.loads(form.get('answers',[''])[0])
                    source=form.get('authority_source',[''])[0]; revision=form.get('authority_revision',[''])[0]
                    digest=app.question_authority.promote(bundle,answers,authority_source=source,authority_revision=revision)
                    self._mutation_response({'status':'promoted','question_digest':digest},form); return
                except (ValueError,json.JSONDecodeError):
                    self._send(400,'{"error":"question authority promotion rejected"}\n','application/json; charset=utf-8'); return
            if len(path)==3 and path[0]=='action' and path[1]=='respond':
                subject=unquote(path[2])
                if subject in {'.','..'} or not _SUBJECT.fullmatch(subject) or app.human_input is None:
                    self._send(409,'{"error":"human input unavailable"}\n','application/json; charset=utf-8'); return
                try: result=app.human_input.respond(subject,form.get('response',[''])[0]); code=200 if result.ok else 409
                except ValueError: self._send(400,'{"error":"invalid human input"}\n','application/json; charset=utf-8'); return
                if code==200: self._mutation_response(result.__dict__,form); return
                self._send(code,json.dumps(result.__dict__,ensure_ascii=False)+'\n','application/json; charset=utf-8'); return
            if len(path)==3 and path[0]=='action' and path[1]=='reconcile':
                if app.reconciliation is None:
                    self._send(409,'{"error":"reconciliation unavailable"}\n','application/json; charset=utf-8'); return
                subject=unquote(path[2])
                if subject in {'.','..'} or not _SUBJECT.fullmatch(subject):
                    self._send(400,'{"error":"invalid operator action"}\n','application/json; charset=utf-8'); return
                result=app.reconciliation.reconcile(subject); code=200 if result.get('ok') else 409
                if code==200: self._mutation_response(result,form); return
                self._send(code,json.dumps(result,ensure_ascii=False)+'\n','application/json; charset=utf-8'); return
            if len(path)==3 and path[0]=='action' and path[1]=='delegate-mcp':
                # Owner decisions live in the original Operator Guard actions,
                # never a second MCP approval-issuer path. Keep CSRF/Origin
                # checks above intact and close this legacy write surface.
                self._send(404,'not found\n','text/plain; charset=utf-8')
                return
            if len(path)!=3 or path[0]!='action': self._send(404,'not found\n','text/plain; charset=utf-8'); return
            try:
                result=app.act(path[1],path[2],approval_ref=form.get('approval_ref',[''])[0]); code=200 if result.ok else 409
                if code==200: self._mutation_response(result.__dict__,form); return
                response_body=json.dumps(result.__dict__,ensure_ascii=False)+'\n'
            except ValueError: code=400; response_body='{"error":"invalid operator action"}\n'
            self._send(code,response_body,'application/json; charset=utf-8')
        def log_message(self,format,*args): pass
    return Handler

def serve(app,host='127.0.0.1',port=0):
    if host not in {'127.0.0.1','localhost','::1'}: raise ValueError('operator server must bind loopback')
    return BoundedThreadingHTTPServer((host,port),make_handler(app))



