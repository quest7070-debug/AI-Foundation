"""Start the unchanged daily Operator with an additive owner-context factory."""
import hashlib
import json
from pathlib import Path
import runpy
import sys


def main():
    root=Path(__file__).resolve().parents[1]
    manifest=json.loads((root/'runtime.json').read_text())
    legacy=Path(manifest['legacy_script'])
    if hashlib.sha256(legacy.read_bytes()).hexdigest()!=manifest['legacy_script_sha256']:
        raise RuntimeError('legacy Operator changed after staging')
    for relative,pin in manifest['files'].items():
        if hashlib.sha256((root/relative).read_bytes()).hexdigest()!=pin:
            raise RuntimeError('context runtime source changed')
    for relative,pin in manifest['legacy_files'].items():
        if hashlib.sha256((legacy.parent.parent/relative).read_bytes()).hexdigest()!=pin:
            raise RuntimeError('legacy module changed after staging')
    sys.path.insert(0,str(legacy.parent.parent/'src'))
    import ai_foundation
    ai_foundation.__path__=[str(root/'src/ai_foundation'),str(legacy.parent.parent/'src/ai_foundation')]
    from ai_foundation.local_model_availability import install_legacy_availability_filter
    install_legacy_availability_filter()
    from ai_foundation.gateway_csrf import install_fast_csrf
    install_fast_csrf()
    from ai_foundation.human_model_runtime import install_legacy_agent_factory
    checking=sys.argv[1:]==['--self-check']
    factory=install_legacy_agent_factory(binding_path=manifest['prepared_binding'] if checking else manifest['active_binding'],
        repository_root=root,audit_path=manifest['audit_path'])
    if checking:
        from types import SimpleNamespace
        from pydantic_ai.models.function import FunctionModel
        from pydantic_ai.messages import ModelResponse,ToolCallPart,ToolReturnPart,TextPart
        from ai_foundation.capability_request import CapabilityRequest
        from ai_foundation.core import GuardState
        from ai_foundation.guard import GuardCore
        owner=json.loads(Path(manifest['prepared_binding']).read_text())['bindings'][0]['owner_id']
        def model(messages,info):
            if any(isinstance(p,ToolReturnPart) for m in messages for p in m.parts):
                return ModelResponse(parts=[TextPart('source-readback-ok')])
            return ModelResponse(parts=[ToolCallPart('human_model_context',{'scope':'ai-foundation-project'})])
        agent=factory(FunctionModel(model),SimpleNamespace(guard=GuardCore(GuardState())),
            CapabilityRequest(owner_id=owner),run_id='staged-self-check')
        if agent.run('Read the host project reference.')!='source-readback-ok':
            raise RuntimeError('staged agent context failed')
        from ai_foundation.llama_swap_adapter import LlamaSwapDiscovery
        inventory=LlamaSwapDiscovery(manifest_path=Path(manifest['active_binding']).parent/'local-compute/llama-swap.yaml')()
        missing=sum(candidate.reason=='MODEL_ARTIFACT_MISSING' for candidate in inventory)
        print(json.dumps({'status':'STAGED_AGENT_CONTEXT_VERIFIED','real_model_calls':0,
                          'missing_model_aliases_excluded':missing}));return
    sys.argv=[str(legacy),*sys.argv[1:]]
    runpy.run_path(str(legacy),run_name='__main__')


if __name__=='__main__':main()
