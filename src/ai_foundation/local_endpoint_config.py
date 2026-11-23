"""Host-owned configuration for optional remote/local OpenAI-compatible compute."""
from __future__ import annotations
import json
import os
import platform
from pathlib import Path
from .local_compute_registry import LocalComputeRegistry
from .openai_local_adapter import OpenAILocalDiscovery,OpenAILocalExecution,OpenAILocalModelPolicy

def _resolved_api_key(row):
    env=row.get('api_key_env')
    if env is None:return None
    if not isinstance(env,str) or not env:raise ValueError('api_key_env must name a non-empty environment variable')
    key=os.environ.get(env)
    # Only the owner-pinned MainPC credential may be read from native macOS
    # Keychain. Generic remote endpoints/providers never inherit this secret.
    if (not key and row.get('name')=='mainpc-strata' and
            env=='STRATA_API_KEY' and platform.system()=='Darwin'):
        from .native_credentials import MacOSNativeCredentialStore
        try:
            key=MacOSNativeCredentialStore().load('local:mainpc-strata:api-key')
        except (KeyError,OSError,RuntimeError,ValueError):
            pass
    if not key:raise ValueError(f'api_key_env {env!r} is not set in the environment')
    return key

def load_local_endpoints(path):
    path=Path(path)
    try:data=json.loads(path.read_text())
    except FileNotFoundError:return ()
    if not isinstance(data,dict) or data.get('version')!=1:raise ValueError('unsupported local endpoint config')
    out=[]
    for row in data.get('endpoints',[]):
        if not isinstance(row,dict):raise ValueError('invalid local endpoint')
        name=row['name'];base=row['base_url'];hosts=tuple(row.get('allowed_hosts') or ())
        policies=tuple(OpenAILocalModelPolicy(m['runtime_model'],m['alias'],tuple(m.get('capabilities') or ('CHAT',)),tuple(m.get('roles') or m.get('capabilities') or ('CHAT',)),tuple(m.get('characteristics') or ())) for m in row.get('models',[]))
        prefix=f'local:{name}'
        # An optional remote Windows model must not prevent M1 Foundation
        # startup if its owner key has not yet been restored. Required
        # endpoints preserve the existing fail-closed config error.
        optional=row.get('optional',False)
        if type(optional) is not bool:
            raise ValueError('optional endpoint must be boolean')
        env_name=row.get('api_key_env')
        try:
            api_key=_resolved_api_key(row)
        except ValueError as exc:
            # Optional missing owner secrets do not start an unauthenticated
            # connection. Invalid names/schemas remain errors.
            if (optional and type(env_name) is str and env_name and
                    str(exc)==f"api_key_env {env_name!r} is not set in the environment"):
                continue
            raise
        discovery_timeout=row.get('discovery_timeout')
        execution_timeout=row.get('timeout')
        request_defaults=row.get('request_defaults') or {}
        discovery_kwargs=dict(base_url=base,binding_prefix=prefix,allowed_hosts=hosts,models=policies,api_key=api_key)
        if discovery_timeout is not None:discovery_kwargs['timeout']=discovery_timeout
        discovery=LocalComputeRegistry(OpenAILocalDiscovery(**discovery_kwargs))
        execution_kwargs=dict(base_url=base,allowed_hosts=hosts,alias_to_model={m.alias:m.runtime_model for m in policies},api_key=api_key,request_defaults=request_defaults)
        if execution_timeout is not None:execution_kwargs['timeout']=execution_timeout
        execution=OpenAILocalExecution(**execution_kwargs)
        out.append((prefix,discovery,execution))
    return tuple(out)
