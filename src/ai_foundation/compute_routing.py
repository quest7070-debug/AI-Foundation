from dataclasses import dataclass

@dataclass(frozen=True)
class ComputeRoute:
    binding:str|None
    kind:str|None
    model:str|None = None
    execution_slot:str|None = None

class ComputeRouter:
    """Provider-agnostic selector. Guard privacy remains a harder boundary than this policy."""
    def __init__(self,settings,local_registry):self.settings=settings;self.local_registry=local_registry

    def _measured_faster_9b(self, candidates):
        """Yield public CHAT to 9B only after comparable, fresh real completions.

        Evidence is optional: a new installation or missing/invalid telemetry
        retains Strata-first. No extra model calls, loading or probes here.
        """
        import math
        import sqlite3
        import time
        local9b = next(
            (c for c in candidates if c.binding == 'local:ollama-shared9b:general'
             and c.health == 'ONLINE' and getattr(c, 'same_host', False) is True),
            None)
        policy = getattr(getattr(self.settings, 'routing', None), 'runtime', None)
        if local9b is None or not callable(policy):
            return None
        try:
            strata = policy('local:mainpc-strata:code-agent', 'CHAT')
            nine = policy(local9b.binding, 'CHAT')
            if not isinstance(strata, dict) or not isinstance(nine, dict):
                return None
            now = time.time()
            for sample in (strata, nine):
                count = sample.get('successes')
                latency = sample.get('success_latency_ms')
                observed = sample.get('updated_at')
                if (type(count) is not int or count < 4
                    or not isinstance(latency, (int, float)) or not math.isfinite(latency)
                    or latency <= 0
                    or not isinstance(observed, (int, float)) or not math.isfinite(observed)
                    or not 0 <= now - observed <= 7 * 86400):
                    return None
            # Require a material gap, not a tie/noisy minor difference.
            if (strata['success_latency_ms'] >= nine['success_latency_ms'] * 1.75
                and strata['success_latency_ms'] - nine['success_latency_ms'] >= 10000):
                return local9b
        except (OSError, ValueError, TypeError, KeyError, RuntimeError, sqlite3.Error):
            return None
        return None

    def choose(self,function='CHAT',*,local_required=False,prefer_local=False,exclude=(),phase=None,external_preferred=False,strata_first=False):
        from .routing_capabilities import supports, normalize_capability
        function=normalize_capability(function)
        excluded=set(exclude)
        snapshot=self.local_registry.candidates()
        locals=[c for c in snapshot if c.health=='ONLINE' and supports({'kind':'LOCAL','capabilities':c.capabilities},function) and c.binding not in excluded]
        # A CHAT capability in the endpoint config does not authorize egress
        # of an unreviewed daily message to another computer. Only exact
        # trusted-public admission exposes this remote candidate for CHAT.
        strata_binding='local:mainpc-strata:code-agent'
        strata=next((c for c in locals
                     if c.binding==strata_binding
                     and c.model=='qwen3.8-flash-next-coder-iq1_m'
                     and c.slot=='code-agent'
                     and getattr(c,'same_host',True) is False),None)
        strata_chat_admitted=(strata_first and not prefer_local and
                              not local_required and strata is not None)
        if function=='CHAT' and not strata_chat_admitted:
            locals=[c for c in locals if c.binding!=strata_binding]
        local=locals[0] if locals else None
        if local_required:
            # LOCAL_ONLY protects the execution machine too, not just a
            # provider's billing classification. Never send owner/private
            # evidence to a separate Windows/Tailscale/remote-local host.
            same_host=next((c for c in locals if getattr(c, 'same_host', True) is True),None)
            return (ComputeRoute(same_host.binding,'LOCAL',same_host.model or None,same_host.slot or None)
                    if same_host else ComputeRoute(None,None))
        # Only a trusted caller's reviewed PUBLIC request may prefer the exact
        # authenticated MainPC specialist. Discovery/capability policy is
        # still required; private LOCAL_ONLY never crosses hosts.
        if strata_first and not prefer_local and function in ('CHAT', 'CODE'):
            if strata:
                # High-confidence comparative telemetry may select the
                # already-admitted M1 9B for public CHAT when materially
                # faster. CODE stays Strata-first; unknown evidence does not
                # create a new 9B gate, background task or model eviction.
                faster = self._measured_faster_9b(locals) if function == 'CHAT' else None
                if faster:
                    return ComputeRoute(faster.binding, 'LOCAL',
                                        faster.model or None, faster.slot or None)
                return ComputeRoute(strata.binding,'LOCAL',strata.model,strata.slot)
            # MainPC is opportunistic. Only already-ONLINE same-host compute
            # can recover public CHAT after absence, or CODE after a failed
            # MainPC attempt. No wake, loading or second scheduler.
            m1=next((c for c in locals if getattr(c,'same_host',True) is True),None)
            if m1 and (function=='CHAT' or strata_binding in excluded):
                return ComputeRoute(m1.binding,'LOCAL',m1.model or None,m1.slot or None)
        if prefer_local and not external_preferred and local:return ComputeRoute(local.binding,'LOCAL',local.model or None,local.slot or None)
        # Prefer only already-admitted cloud routes for explicitly reviewed public work.
        # Keep a local fallback without sending local bindings to a cloud factory.
        search_excluded=excluded | ({c.binding for c in snapshot} if external_preferred else set())
        if function=='CHAT' and not strata_chat_admitted:
            search_excluded.add(strata_binding)
        selected=self.settings.choose_route(function,exclude=search_excluded,phase=phase,local_candidates=snapshot) if self.settings else None
        if selected:
            # Settings persists cloud and local candidates in one route order. Preserve the
            # candidate kind here; a local primary must never be sent to cloud_factory.
            local_match=next((c for c in locals if c.binding==selected),None)
            if local_match:return ComputeRoute(selected,'LOCAL',local_match.model or None,local_match.slot or None)
            # A cached/stale local route in Settings cannot be reclassified as
            # CLOUD when offline or absent from the current admitted registry.
            if isinstance(selected,str) and selected.startswith('local:'):
                return (ComputeRoute(local.binding,'LOCAL',local.model or None,local.slot or None)
                        if local else ComputeRoute(None,None))
            return ComputeRoute(selected,'CLOUD')
        if local:return ComputeRoute(local.binding,'LOCAL',local.model or None,local.slot or None)
        return ComputeRoute(None,None)
    def record_runtime(self,function,binding,success,latency_ms):
        policy=getattr(self.settings,'routing',None)
        if policy and hasattr(policy,'record_runtime'):policy.record_runtime(function,binding,success,latency_ms)
    def record_phase_runtime(self,function,phase,binding,success,latency_ms):
        policy=getattr(self.settings,'routing',None)
        if policy and hasattr(policy,'record_phase_runtime'):policy.record_phase_runtime(function,phase,binding,success,latency_ms)
