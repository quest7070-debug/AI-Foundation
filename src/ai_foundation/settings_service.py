from pathlib import Path
import secrets
from .provider_registry import SQLiteProviderRegistry
from .native_credentials import MacOSNativeCredentialStore
from .provider_onboarding import ProviderOnboarding
from .routing import SQLiteRoutingPolicy
import hashlib
import threading
import fcntl
from contextlib import contextmanager

class SettingsService:
    def __init__(self,data_dir,probe,secret_store=None,local_compute=None,storage_admission=None,free_route=None):
        root=Path(data_dir); root.mkdir(parents=True,exist_ok=True)
        self.local_compute=local_compute
        self.free_route=free_route
        self.registry=SQLiteProviderRegistry(root/'providers.sqlite',storage_admission=storage_admission)
        self.routing=SQLiteRoutingPolicy(root/'routing.sqlite',storage_admission=storage_admission)
        self.routing.retain_functions(self.ROUTE_FUNCTIONS)
        catalog_changed=self._reconcile_catalog_execution_metadata()
        self._lock_path=root/'providers.lock'
        self.secret_store=secret_store or MacOSNativeCredentialStore()
        self._mutation_lock=threading.RLock()
        self.onboarding=ProviderOnboarding(self.registry,self.secret_store,probe,duplicate_checker=self._duplicate_binding)
        # Persisted routes are derived policy. If the shipped adapter/catalog changed
        # model/endpoint/protocol/capabilities, recompute them immediately so stale
        # capability availability cannot survive a software upgrade/reload.
        if catalog_changed:
            self.optimize_all_routes()
    def _reconcile_catalog_execution_metadata(self):
        # Runtime execution support belongs to the shipped adapter/catalog, not stale DB rows.
        # Reconcile only catalog providers with an actual execution protocol/model; probes,
        # health and quota remain observational state in the registry.
        from .provider_catalog import spec
        changed=False
        for row in self.registry.credentials():
            ps=spec(row['provider'])
            if row['provider']=='GITHUB':
                if row.get('health')!='RETIRED': changed=True
                self.registry.observe(row['binding'],health='RETIRED',reason='GitHub Models retired 2026-07-30')
                continue
            if ps and ps.protocol and ps.model:
                desired=(ps.endpoint,ps.model,ps.auth_style,ps.protocol,tuple(ps.capabilities))
                current=(row.get('endpoint'),row.get('model'),row.get('auth_style'),row.get('protocol'),tuple(row.get('capabilities') or ()))
                if current!=desired: changed=True
                self.registry.set_execution_metadata(
                    row['binding'],endpoint=ps.endpoint,model=ps.model,
                    auth_style=ps.auth_style,protocol=ps.protocol,capabilities=ps.capabilities,
                )
            elif any(row.get(k) for k in ('endpoint','model','protocol','capabilities')):
                # A provider removed from executable catalog must not retain stale
                # runtime metadata merely because an old DB row still has it.
                changed=True
                self.registry.set_execution_metadata(row['binding'],endpoint=None,model=None,auth_style=None,protocol=None,capabilities=())
                self.registry.observe(row['binding'],health='RETIRED',reason='provider execution adapter unavailable')
        return changed

    @contextmanager
    def _mutation_guard(self):
        with self._mutation_lock:
            with open(self._lock_path,'a+b') as lock:
                fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
                try: yield
                finally: fcntl.flock(lock.fileno(),fcntl.LOCK_UN)
    def _stage_provider_no_network(self, api_key, provider, tier):
        """Register a key without running any potentially billable provider probe."""
        from .provider_catalog import detect, spec
        if type(api_key) is not str or not api_key.strip():
            raise ValueError('API key required')
        secret=api_key.strip()
        selected=detect(secret) or (provider or '').upper()
        definition=spec(selected)
        if not definition:
            raise ValueError('provider selection required')
        if tier not in {'FREE','PAID'}:
            raise ValueError('invalid tier')
        if self._duplicate_binding(secret):
            raise ValueError('credential already registered')
        binding='llm:'+selected.lower()+':'+secrets.token_hex(6)
        self.secret_store.save(binding,secret)
        try:
            self.registry.upsert(
                binding,selected,tier,health='UNVERIFIED',
                reason='NOT_MANUALLY_SELECTED',
                endpoint=definition.endpoint,model=definition.model,
                auth_style=definition.auth_style,protocol=definition.protocol,
                capabilities=definition.capabilities)
        except Exception:
            self.secret_store.delete(binding)
            raise
        return binding

    def add_provider(self,api_key,provider=None,tier='FREE'):
        with self._mutation_guard():
            binding=(self._stage_provider_no_network(api_key,provider,tier)
                     if self.free_route is not None
                     else self.onboarding.add(api_key,provider,tier))
            try:
                self.optimize_all_routes()
            except Exception:
                self.registry.remove(binding)
                self.secret_store.delete(binding)
                raise
            meta=self.registry.credential(binding)
            card=next(c for c in self.registry.cards() if meta['provider']==c.provider and meta['tier']==c.tier)
            return {'provider':card.provider,'tier':card.tier,'credentials':card.credentials,'health':card.health}
    def cards(self): return self.registry.cards()
    def credentials(self): return self.registry.credentials()
    def services(self):
        from .provider_service_view import service_inventory
        return service_inventory(self.registry.credentials(),self.free_route,self._secret_available)
    # Unified capability routes: native LLM abilities and composed program paths use the same namespace.
    ROUTE_FUNCTIONS=('CHAT','SEARCH','CODE','DATA','FILES','PC_CONTROL','VISION')
    def harness_service_status(self):
        """Read-only Harness service eligibility, never a grant or key listing.

        Credentials/Manual selections are owned by their existing registries;
        Harness merely observes whether a pinned CODE proposal route could
        be considered after host local data and final-code review.
        """
        from .provider_catalog import spec
        pinned = spec("GROQ")
        records = [
            r for r in self.registry.credentials()
            if r["provider"] == "GROQ" and r["tier"] == "FREE"
        ]
        admitted = 0
        for r in records:
            if (self.free_route is not None and pinned is not None
                    and r.get("model") == pinned.model
                    and r.get("endpoint") == pinned.endpoint
                    and r.get("health") in ("ONLINE", "UNVERIFIED")
                    and self.free_route.decide(r).allowed
                    and self._secret_available(r["binding"])):
                admitted += 1
        if self.free_route is None:
            state = "NO_CHARGE_GUARD_NOT_INSTALLED"
        elif not records:
            state = "NOT_REGISTERED"
        elif admitted == 0:
            state = "HOLD_NO_APPROVED_FREE_CONNECTION"
        else:
            state = "ACCOUNT_ADMITTED_HOST_REVIEW_STILL_REQUIRED"
        return {
            "schema": 1,
            "manager": "FOUNDATION_HARNESS",
            "service": "GROQ",
            "model": pinned.model if pinned else None,
            "free_credentials": len(records),
            "account_admitted_connections": admitted,
            "state": state,
            "external_role": "FOUNDATION_DEVELOPMENT",
            "local_protected_roles": [
                "HUMAN_MODEL", "SECRET_MANAGEMENT", "DATA_SENSITIVITY_REVIEW",
                "FINAL_CODE_REVIEW", "ERROR_RECOVERY", "PRIVATE_KLM",
                "M1_ACCEPTANCE",
            ],
            "fallback": "LOCAL_HARNESS_9B",
            "live_deployment_confirmed": False,
        }

    def harness_services_status(self, service_adapters=None, research_ledger=None):
        """All known CODE services under Harness; registration is not admission.

        A newly registered service is discoverable in the Operator status, but
        remains ADAPTER_REQUIRED until a reviewed transport is installed. Even
        then it stays disabled until exact-account no-charge evidence exists.
        The registry is injected by the trusted host; no dynamic plugin imports.
        """
        from .harness_provider_adapter import default_harness_services
        from .harness_service_registry import HarnessServiceRegistry
        from .provider_catalog import spec
        services = (default_harness_services()
                    if service_adapters is None else service_adapters)
        if not isinstance(services, HarnessServiceRegistry):
            raise TypeError("HARNESS_REVIEWED_SERVICE_REGISTRY_REQUIRED")
        rows = self.registry.credentials()
        names = set(services.providers())
        names.update(
            row["provider"] for row in rows
            if spec(row["provider"]) and
            "CODE" in spec(row["provider"]).capabilities)
        output = []
        for provider in sorted(names):
            pinned = spec(provider)
            entries = [row for row in rows if row["provider"] == provider]
            free_rows = [row for row in entries if row["tier"] == "FREE"]
            approved = sum(
                services.admitted(row, self.free_route)
                and self._secret_available(row["binding"])
                for row in free_rows)
            has_adapter = services.get(provider) is not None
            if not has_adapter:
                state = "ADAPTER_REQUIRED"
            elif self.free_route is None:
                state = "NO_CHARGE_GUARD_NOT_INSTALLED"
            elif not free_rows:
                state = "NOT_REGISTERED"
            elif approved == 0:
                state = "HOLD_NO_APPROVED_FREE_CONNECTION"
            else:
                state = "ACCOUNT_ADMITTED_HOST_REVIEW_STILL_REQUIRED"
            output.append({
                "service": provider,
                "pinned_model": pinned.model if has_adapter and pinned else None,
                "adapter_installed": has_adapter,
                "registered_accounts_keys": len(entries),
                "free_credentials": len(free_rows),
                "account_admitted_connections": approved,
                "state": state,
            })
        # The external research inventory is a separate authority-free
        # collection. A service can be known to research before any native
        # credential or source-reviewed transport exists. Do not coerce these
        # into executable registry entries.
        research_candidates = []
        if research_ledger is not None:
            for entry in self.external_services(research_ledger):
                research_candidates.append({
                    "service_id": entry.service_id,
                    "name": entry.name,
                    "integration_kind": entry.integration_kind,
                    "research_state": entry.research_state,
                    "connection_state": entry.connection_state,
                    "billing_state": entry.billing_state,
                    "execution_authorized": False,
                })
        # These static preflights report missing trusted host evidence only.
        # Do not convert a research ledger, API key or model advertisement into
        # a runnable agent/remote session or a manual Free-route selection.
        from .next_service_preflight import next_services_status
        known_research = {row["service_id"] for row in research_candidates}
        candidate_preflights = [
            report for report in next_services_status()
            if report["service"] in known_research
        ]
        return {
            "schema": 2,
            "manager": "FOUNDATION_HARNESS",
            "services": output,
            "research_candidates": research_candidates,
            "candidate_preflights": candidate_preflights,
            "research_loaded": research_ledger is not None,
            "default_fallback": "LOCAL_HARNESS_9B",
            "runtime_enabled": False,
        }

    def external_services(self, research_ledger):
        """One service card per audited service, not one card per API key.

        Caller owns the audited research data; credentials and charge receipts
        are fetched from existing live owners. Never exposes Keychain secrets.
        No provider probe, billing change, model inference, or auto-enrollment.
        """
        from .external_service_inventory import service_inventory
        return service_inventory(
            research_ledger, credentials=self.registry.credentials(),
            secret_available=self._secret_available, free_route=self.free_route)
    def _secret_available(self,binding):
        # Native production stores expose `available`; tiny legacy/test adapters may
        # implement only save/delete and therefore cannot make a revocation claim.
        fn=getattr(self.secret_store,'available',None)
        return bool(fn(binding)) if fn is not None else True
    def _free_route_eligible(self,row):
        return (row.get('kind')=='LOCAL' or self.free_route is None
                or self.free_route.decide(row).allowed)

    def _routing_candidates(self):
        # One live inventory for the whole routing decision; do not probe the same
        # local backends again for every capability.
        from .routing_candidates import merged_candidates
        local=self.local_compute.candidates() if self.local_compute else ()
        rows=merged_candidates(self.registry.credentials(),local)
        return tuple(x for x in rows if self._free_route_eligible(x) and
                     (x.get('kind')=='LOCAL' or
                      (x.get('binding') and self._secret_available(x['binding']))))

    def _optimize_from_candidates(self,function,candidates):
        function=function.upper()
        if function not in self.ROUTE_FUNCTIONS: raise ValueError('invalid route function')
        from .routing_capabilities import supports
        from .capability_topology import uses_llm_route
        # Only real LLM capabilities get LLM providers; never route host tools
        # through a chat model or re-enable paid candidates.
        eligible=tuple(x for x in candidates if uses_llm_route(function)
                       and supports(x,function) and x.get('tier')!='PAID')
        return self.routing.optimize(function,eligible,self.routing.preferences(function))

    def optimize_routing(self,function='CHAT'):
        return self._optimize_from_candidates(function,self._routing_candidates())

    def optimize_all_routes(self):
        snapshot=self._routing_candidates()
        return tuple(self._optimize_from_candidates(f,snapshot) for f in self.ROUTE_FUNCTIONS)
    def routes(self):
        return tuple(self.routing.get(f) for f in self.ROUTE_FUNCTIONS)

    def route_label(self,binding):
        if not binding:return '—'
        meta=self.registry.credential(binding)
        if meta:
            name={'OPENROUTER':'OpenRouter'}.get(meta['provider'],meta['provider'].title())
            return f"{name} / PAID" if meta['tier']=='PAID' else name
        for c in (self.local_compute.candidates() if self.local_compute else ()):
            if c.binding==binding:return c.model or 'Local'
        return 'UNAVAILABLE'
    def route(self,function='CHAT'):
        return self.routing.get(function)
    def choose_route(self,function='CHAT',exclude=(),phase=None,local_candidates=None):
        from .routing_candidates import merged_candidates
        # The canonical ComputeRouter already took a fresh per-decision snapshot.
        # Reuse it instead of a duplicate local HTTP discovery.
        local=(self.local_compute.candidates() if self.local_compute else ()) if local_candidates is None else local_candidates
        states=merged_candidates(self.registry.credentials(),local)
        # Registry rows restored from backup cannot resurrect revoked cloud authority.
        states=tuple(x for x in states if self._free_route_eligible(x) and
                     (x.get('kind')=='LOCAL' or (x.get('binding') and self._secret_available(x['binding']))))
        from .routing_capabilities import supports
        from .capability_topology import uses_llm_route
        excluded=set(exclude)
        states=tuple(x for x in states if uses_llm_route(function) and supports(x,function) and x.get('binding') not in excluded and x.get('tier')!='PAID')
        # Route snapshots are derived display/policy state. Execution must not mutate
        # persisted policy as a side effect of a read/choose call. Provider add/remove,
        # refresh/recovery and catalog reconciliation already republish routes at their
        # authoritative mutation boundaries.
        # phase is accepted for compatibility/telemetry callers only; execution
        # selection remains the single capability-level routing policy.
        chosen=self.routing.choose(function,states)
        if chosen:return chosen
        # Persisted routes may predate a concrete local-model binding migration.
        # Never keep returning a stale alias when a currently discovered capable
        # candidate exists; choose from live state without rewriting policy here.
        return next((x.get('binding') for x in states if x.get('kind')=='LOCAL' and x.get('health')=='ONLINE' and x.get('binding') and x.get('binding') not in excluded),None)
    def _duplicate_binding(self,secret):
        # Compare in memory only; no secret or digest is persisted.
        target=hashlib.sha256(secret.encode()).digest()
        for binding in self.registry.bindings():
            try:
                if hashlib.sha256(self.secret_store.load(binding).encode()).digest()==target:return binding
            except (KeyError,RuntimeError): continue
        return None
    def replace_provider_credential(self, binding, secret):
        if not secret or not secret.strip():
            raise ValueError('API key required')
        secret = secret.strip()
        with self._mutation_guard():
            meta = self.registry.credential(binding)
            if not meta:
                raise KeyError(binding)
            old_secret = self.secret_store.load(binding)
            if self.free_route is not None:
                # Rotation may change billing account. Revoke before updating the key.
                from .provider_catalog import detect
                detected=detect(secret)
                if detected is not None and detected != meta['provider']:
                    raise ValueError('credential provider mismatch')
                self.free_route.revoke(binding)
                self.secret_store.save(binding,secret)
                try:
                    self.registry.upsert(
                        binding,meta['provider'],meta['tier'],'UNVERIFIED',
                        reason='NOT_MANUALLY_SELECTED',
                        endpoint=meta.get('endpoint'),model=meta.get('model'),
                        auth_style=meta.get('auth_style'),
                        protocol=meta.get('protocol'),
                        capabilities=meta.get('capabilities') or ())
                except Exception:
                    self.secret_store.save(binding,old_secret)
                    raise
                self.optimize_all_routes()
                return {'provider':meta['provider'],'tier':meta['tier'],
                        'health':'UNVERIFIED'}
            result = self.onboarding.probe.probe(secret, meta['provider'])
            provider = (result.provider or meta['provider']).upper()
            if provider != meta['provider'] or result.health not in {'ONLINE','RATE_LIMITED'}:
                raise ValueError(result.reason or 'provider validation failed')
            self.secret_store.save(binding, secret)
            try:
                self.registry.upsert(
                    binding, provider, meta['tier'], result.health,
                    result.short_remaining, result.short_reset,
                    result.long_remaining, result.long_reset,
                    reason=result.reason,
                    endpoint=meta.get('endpoint'), model=meta.get('model'),
                    auth_style=meta.get('auth_style') or 'bearer',
                    protocol=meta.get('protocol'), capabilities=meta.get('capabilities') or (),
                )
            except Exception:
                self.secret_store.save(binding, old_secret)
                raise
            self.optimize_all_routes()
            return {'provider': provider, 'tier': meta['tier'], 'health': result.health}

    def refresh_provider(self, binding):
        with self._mutation_guard():
            meta = self.registry.credential(binding)
            if not meta:
                raise KeyError(binding)
            # GitHub identity may still be ONLINE, but GitHub Models inference was retired.
            # Provider-card health describes the LLM service we can execute, not unrelated account identity.
            if meta['provider']=='GITHUB':
                self.registry.observe(binding,health='RETIRED',reason='GitHub Models retired 2026-07-30')
                self.optimize_all_routes()
                return {'provider':'GITHUB','tier':meta['tier'],'health':'RETIRED'}
            if self.free_route is not None:
                verdict=self.free_route.decide(meta)
                if not verdict.allowed:
                    self.registry.observe(binding,health='UNVERIFIED',reason=verdict.reason)
                    self.optimize_all_routes()
                    return {'provider':meta['provider'],'tier':meta['tier'],
                            'health':'UNVERIFIED','reason':verdict.reason}
            secret = self.secret_store.load(binding)
            result = self.onboarding.probe.probe(secret, meta['provider'])
            # Catalog probe result is the current recovery observation; do not preserve stale registry health over newer evidence.
            health = (result.health or 'DOWN').upper()
            self.registry.observe(
                binding,
                health=health,
                short_remaining=result.short_remaining,
                short_reset=result.short_reset,
                long_remaining=result.long_remaining,
                long_reset=result.long_reset,
                reason=result.reason or (None if health == 'ONLINE' else 'provider probe failed'),
            )
            self.optimize_all_routes()
            return {'provider': meta['provider'], 'tier': meta['tier'], 'health': health}

    def remove_provider(self,binding):
        with self._mutation_guard():
            return self._remove_provider_locked(binding)
    def _remove_provider_locked(self,binding):
        meta=self.registry.credential(binding)
        if not meta: raise KeyError(binding)
        # Revoke an old Free-route selection before credential removal.
        if self.free_route is not None: self.free_route.revoke(binding)
        if not self.secret_store.delete(binding): raise RuntimeError('credential delete failed; registry retained for reconciliation')
        try:self.registry.remove(binding)
        except Exception as exc:
            raise RuntimeError('credential deleted but registry cleanup failed; reconciliation required') from exc
        self.optimize_all_routes()
        return {'removed':True,'provider':meta['provider'],'tier':meta['tier']}
    def reconcile_missing_credential(self,binding):
        """Repair only the known Keychain-first delete split; never deletes a present secret."""
        with self._mutation_guard():
            meta=self.registry.credential(binding)
            if not meta: return {'repaired':False,'status':'NOT_FOUND'}
            if self.secret_store.available(binding): return {'repaired':False,'status':'SECRET_PRESENT'}
            if self.free_route is not None: self.free_route.revoke(binding)
            self.registry.remove(binding);self.optimize_all_routes()
            return {'repaired':True,'status':'STALE_REGISTRY_REMOVED','provider':meta['provider'],'tier':meta['tier']}

    def preflight(self):
        integrity=self.registry.integrity_check(); missing=[]
        if integrity['ok']:
            missing=[b for b in self.registry.bindings() if not self.secret_store.available(b)]
        return {'ok':integrity['ok'] and not missing,'integrity':integrity,'missing_credentials':tuple(missing)}
