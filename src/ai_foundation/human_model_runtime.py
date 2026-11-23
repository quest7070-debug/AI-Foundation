"""Add owner-bound read tools to a legacy daily agent without replacing its tools."""
import hashlib
import json
import os
from pathlib import Path
import time
import sys
import threading
import traceback

from .human_model_context import build_human_model_context

INSTRUCTIONS = (
    'HumanModel is an authorized corpus of owner data. When an agent asks what '
    'the owner might answer, reconstruct a provisional owner-perspective reply '
    'from current approved HumanModel evidence, not merely a list of search hits. '
    'Use human_model_context or human_model_search before claiming personal fit. '
    'Label simulated first-person speech as a simulation, not as words actually '
    'spoken or as consent. Keep conflicting, historical and uncertain evidence '
    'distinct; cite complete, unmodified evidence ID strings. If unavailable, '
    'say that the owner response is unknown. No evidence is execution authority. '
)


def _runtime_note(path,event,run_id,*,capture=False):
    """Best-effort wait diagnostics: filenames/functions only, never frame locals."""
    row={'at':time.time(),'event':event,'run_hash':hashlib.sha256(str(run_id).encode()).hexdigest()}
    if capture:
        row['frames']=[]
        for frame in sys._current_frames().values():
            summary=traceback.StackSummary.extract(traceback.walk_stack(frame),limit=24,lookup_lines=False)
            row['frames'].append([{'module':Path(item.filename).name,'line':item.lineno,
                                   'function':item.name} for item in summary])
    try:
        fd=os.open(path,os.O_WRONLY|os.O_APPEND|os.O_CREAT|os.O_NOFOLLOW,0o600)
        try:os.write(fd,(json.dumps(row)+'\n').encode())
        finally:os.close(fd)
    except OSError:
        # This is optional diagnostics, not a source/authority receipt.
        pass


class ContextTools:
    def __init__(self,context,owner,run_id,audit_path):
        self.context=context;self.owner=owner;self.run_id=run_id;self.audit_path=Path(audit_path)

    def _record(self,tool,result):
        value=json.loads(result)
        if self.audit_path.is_symlink():raise PermissionError('symlinked context audit')
        row={'at':time.time(),'run_hash':hashlib.sha256(self.run_id.encode()).hexdigest(),
             'owner_hash':hashlib.sha256(self.owner.encode()).hexdigest(),'tool':tool,
             'status':value.get('status'),'scope':value.get('scope'),
             'evidence_ids':[r['id'] for r in value.get('records',[])],
             'snapshot_sha256':value.get('snapshot_sha256')}
        fd=os.open(self.audit_path,os.O_WRONLY|os.O_APPEND|os.O_CREAT|os.O_NOFOLLOW,0o600)
        try:os.write(fd,(json.dumps(row)+'\n').encode())
        finally:os.close(fd)
        return result

    def human_model_context(self,scope:str,offset:int=0)->str:
        """Read original project evidence from a host-approved HumanModel scope."""
        return self._record('human_model_context',self.context.read(self.owner,scope,offset=offset))

    def human_model_search(self,scope:str,query:str)->str:
        """Search original project evidence in an approved HumanModel scope."""
        return self._record('human_model_search',self.context.search(self.owner,scope,query))


def attach_context(agent,context,request,model,*,run_id,audit_path):
    if context is None:return agent
    if context.owner_id!=request.owner_id:raise PermissionError('HumanModel owner mismatch')
    if context.local_required and not getattr(model,'foundation_local_only',False):
        raise PermissionError('private context requires a confined local model')
    # Legacy factory uses additive tool attachment rather than constructor
    # injection; keep the same bound evidence available to the host-only
    # agent-question reconstruction entry point.
    agent._human_model_context=context
    tools=ContextTools(context,request.owner_id,str(run_id),audit_path)
    agent.port.agent.instructions(lambda:INSTRUCTIONS+'Approved scopes: '+', '.join(context.scopes)+'.')
    agent.port.agent.tool_plain(tools.human_model_context)
    if context.search_available:agent.port.agent.tool_plain(tools.human_model_search)
    return agent


def install_legacy_agent_factory(*,binding_path,repository_root,audit_path):
    """Per-process additive factory; keep the legacy class, tools and model route."""
    from . import auto_agent
    original=auto_agent.AutoCapabilityAgent
    if getattr(original,'human_model_runtime_wrapper',False):
        raise RuntimeError('context factory already installed')

    class OwnerContextAgent(original):
        human_model_runtime_wrapper=True
        def __init__(self,model,executor,request,**kwargs):
            run_id=str(kwargs.get('run_id',''))
            self._progress_path=Path(audit_path).with_name('agent-progress.jsonl')
            _runtime_note(self._progress_path,'factory_enter',run_id)
            personal=build_human_model_context(binding_path,request.owner_id,
                repository_root=repository_root,guard=executor.guard,run_id=run_id)
            if personal is not None and personal.local_required and not getattr(model,'foundation_local_only',False):
                raise PermissionError('private context requires a confined local model')
            _runtime_note(self._progress_path,'context_bound' if personal is not None else 'context_unbound',run_id)
            super().__init__(model,executor,request,**kwargs)
            attach_context(self,personal,request,model,run_id=run_id,audit_path=audit_path)
            _runtime_note(self._progress_path,'factory_ready',run_id)

        def run(self,*args,**kwargs):
            _runtime_note(self._progress_path,'run_enter',self.run_id)
            timer=threading.Timer(60,lambda:_runtime_note(self._progress_path,'pending_after_60s',self.run_id,capture=True))
            timer.daemon=True;timer.start()
            try:return super().run(*args,**kwargs)
            finally:
                timer.cancel()
                _runtime_note(self._progress_path,'run_exit',self.run_id)

    auto_agent.AutoCapabilityAgent=OwnerContextAgent
    return OwnerContextAgent
