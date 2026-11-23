"""Execute only host-bound capability requests. Prompt text never expands authority."""
from __future__ import annotations
from dataclasses import dataclass
from .research import ResearchSpecialist
from .research_adapter import InferenceResearchPort
from .data_adapter import build_data_specialist
from .files_adapter import build_files
from .coding_adapter import build_coding_specialist

@dataclass
class CapabilityExecutor:
    inference: object
    guard: object
    file_port: object|None = None
    reconciliation_registry: object|None = None
    file_port_binding: str = ''
    protected: object|None = None
    activity: object|None = None
    repo_port: object|None = None
    repo_port_binding: str = ''
    attachment_handoff: object|None = None
    tracer: object|None = None
    vision_port: object|None = None
    mcp_registry: object|None = None

    def execute_text_artifact(self, request, target, content, run_id):
        """Explicit host write grant only; attachment grants never authorize output."""
        import json
        from dataclasses import asdict
        if request.capability != 'FILES' or not request.file_write_root or not request.owner_id:
            raise PermissionError('host-authorized artifact output required')
        if self.file_port is None:
            raise RuntimeError('FILES unavailable')
        activity_id = f'{run_id}:artifact'
        if self.activity: self.activity.active(activity_id, 'FILES', 'FILES')
        try:
            files = build_files(request, self.guard, self.file_port,
                reconciliation_registry=self.reconciliation_registry,
                port_binding=self.file_port_binding, protected=self.protected)
            def produce():
                result = files.produce_text_artifact(run_id, target, content)
                return json.dumps({**asdict(result), 'verified': result.verified}, ensure_ascii=False)
            if self.tracer:
                from .observability import safe_attributes
                with self.tracer.span('capability.execute', safe_attributes({'run_id': run_id, 'capability': 'FILES'})):
                    return produce()
            return produce()
        finally:
            if self.activity: self.activity.inactive(activity_id)

    def execute(self,request,text,run_id):
        cap=request.capability
        activity_id=f'{run_id}:capability'
        if self.activity:self.activity.active(activity_id,cap,cap)
        try:
            if self.tracer:
                from .observability import safe_attributes
                with self.tracer.span('capability.execute',safe_attributes({'run_id':run_id,'capability':cap})):
                    return self._execute(request,text,run_id)
            return self._execute(request,text,run_id)
        finally:
            if self.activity:self.activity.inactive(activity_id)

    def _execute(self,request,text,run_id):
        cap=request.capability
        if cap=='SEARCH':
            r=ResearchSpecialist(InferenceResearchPort(self.inference)).investigate(text)
            # SEARCH is a tool boundary, not the final conversational renderer.
            # Preserve the observed evidence so the Agent can synthesize instead of
            # repeatedly searching after a provider adapter's generic answer marker.
            import json
            return json.dumps({'answer':r.answer,'evidence':[{'source':e.source,'claim':e.claim,'excerpt':e.excerpt,'confidence':e.confidence,'observed_at':e.observed_at,'published_at':e.published_at} for e in r.evidence],'uncertainty':r.uncertainty},ensure_ascii=False)
        if cap=='VISION':
            if self.vision_port is None: raise RuntimeError('VISION unavailable')
            return self.vision_port.observe(request,text).text
        if cap=='COMPUTE':
            if self.mcp_registry is None: raise RuntimeError('COMPUTE unavailable')
            import json
            try: command=json.loads(text)
            except (TypeError,json.JSONDecodeError) as e: raise ValueError('COMPUTE command must be an object') from e
            if not isinstance(command,dict): raise ValueError('COMPUTE command must be an object')
            tool=command.get('tool')
            args=command.get('args',{})
            if not isinstance(tool,str) or not tool: raise ValueError('COMPUTE tool required')
            if not isinstance(args,dict): raise ValueError('COMPUTE args must be an object')
            return json.dumps(self.mcp_registry.invoke(request.compute_profile,tool,args),ensure_ascii=False)
        if cap=='BROWSER':
            if self.mcp_registry is None: raise RuntimeError('BROWSER unavailable')
            import json
            try: command=json.loads(text)
            except (TypeError,json.JSONDecodeError) as e: raise ValueError('BROWSER command must be an object') from e
            if not isinstance(command,dict): raise ValueError('BROWSER command must be an object')
            tool=command.get('tool')
            args=command.get('args',{})
            if not isinstance(tool,str) or not tool: raise ValueError('BROWSER tool required')
            if not isinstance(args,dict): raise ValueError('BROWSER args must be an object')
            return json.dumps(self.mcp_registry.invoke(request.browser_target,tool,args),ensure_ascii=False)
        if cap=='DATA':
            if not request.data_backend:
                if request.data_value_contract == "numeric_array":
                    import json
                    try:
                        payload = json.loads(text)
                    except (ValueError, TypeError) as exc:
                        raise ValueError("DATA_NUMERIC_ARRAY_CONTRACT_REQUIRED") from exc
                    if (type(payload) is not list or not 1 <= len(payload) <= 256
                            or any(type(x) not in (int, float) or not -1e12 <= x <= 1e12
                                   for x in payload)):
                        raise ValueError("DATA_NUMERIC_ARRAY_CONTRACT_REQUIRED")
                return build_data_specialist(request).analyze(text).output
            if self.mcp_registry is None: raise RuntimeError('DATA backend unavailable')
            import json
            try: command=json.loads(text)
            except (TypeError,json.JSONDecodeError) as err: raise ValueError('DATA backend command must be an object') from err
            if not isinstance(command,dict): raise ValueError('DATA backend command must be an object')
            tool=command.get('tool')
            args=command.get('args',{})
            if not isinstance(tool,str) or not tool: raise ValueError('DATA backend tool required')
            if not isinstance(args,dict): raise ValueError('DATA backend args must be an object')
            return json.dumps(self.mcp_registry.invoke(request.data_backend,tool,args),ensure_ascii=False)
        if cap=='FILES':
            if request.file_operation=='list_directory':
                if self.file_port is None: raise RuntimeError('FILES unavailable')
                files=build_files(request,self.guard,self.file_port,protected=self.protected)
                return files.list_directory(run_id,text)
            if request.attachments:
                if len(request.attachments)!=1: raise ValueError('FILES attachment mode requires exactly one attachment')
                grant=request.attachments[0]
                leased=self.attachment_handoff.acquire(grant) if self.attachment_handoff is not None else False
                try:return open(grant.path,'r',encoding='utf-8',errors='replace').read()
                finally:
                    if leased:self.attachment_handoff.release(grant)
            if self.file_port is None: raise RuntimeError('FILES unavailable')
            files=build_files(request,self.guard,self.file_port,reconciliation_registry=self.reconciliation_registry,port_binding=self.file_port_binding,protected=self.protected)
            return files.read(run_id,text)
        if cap=='CODE':
            if self.repo_port is None and self.file_port is None: raise RuntimeError('CODE unavailable')
            code=build_coding_specialist(request,self.guard,self.repo_port or self.file_port,run_id,reconciliation_registry=self.reconciliation_registry,port_binding=self.repo_port_binding or self.file_port_binding,protected=self.protected)
            import json
            try:
                command=json.loads(text)
            except (TypeError,json.JSONDecodeError):
                command={'operation':'inspect','target':text}
            if not isinstance(command,dict): raise ValueError('CODE command must be an object')
            operation=command.get('operation','inspect')
            target=command.get('target','')
            if not isinstance(target,str): raise ValueError('CODE target must be text')
            if operation=='inspect':
                result=code.inspect(target)
            elif operation=='change':
                content=command.get('content')
                if not isinstance(content,str): raise ValueError('CODE change requires text content')
                result=code.apply_verified_change(target,content)
            else:
                raise ValueError('unsupported CODE operation')
            import json as _json
            return _json.dumps({
                'operation':operation,
                'target':target,
                'observed':result.observed,
                'verification':result.test_result,
                'effect':result.write_result,
                # Machine-readable receipt: a verified Guard write alone does
                # not prove independent post-change acceptance passed.
                'status': ('INSPECTED' if operation=='inspect' else
                           'VERIFIED_COMPLETE' if getattr(result,'verified',False) else 'FAILED_VERIFICATION'),
            },ensure_ascii=False)
        raise ValueError('capability execution not available')
