"""Withdraw host-configured local aliases whose exact model file is absent."""
from dataclasses import replace
from pathlib import Path
import re

_MODEL=re.compile(r"""--model(?:\s+|=)(?:"([^"]+)"|'([^']+)'|([^\s]+))""")

def manifest_artifacts(manifest_path):
    if manifest_path is None:return {}
    try:lines=Path(manifest_path).read_text().splitlines()
    except OSError:return {}
    result={};slot=None
    for line in lines:
        block=re.match(r'^  ([^ #][^:]*):\s*$',line)
        if block:slot=block.group(1).strip();continue
        match=_MODEL.search(line) if slot else None
        if match:
            value=next(part for part in match.groups() if part is not None)
            path=Path(value).expanduser()
            # Relative paths and shell variables require the runtime's execution
            # context; do not guess a different file or grant a new model role.
            if path.is_absolute():result[slot]=path
    return result

def verify_configured_artifacts(candidates,manifest_path):
    artifacts=manifest_artifacts(manifest_path);result=[]
    for candidate in candidates:
        path=artifacts.get(candidate.slot)
        if path is not None and candidate.health=='ONLINE' and candidate.roles:
            try:present=path.is_file()
            except OSError:present=False
            if not present:
                candidate=replace(candidate,health='UNAVAILABLE',active=False,
                    reason='MODEL_ARTIFACT_MISSING',capabilities=(),roles=())
        result.append(candidate)
    return tuple(result)

def install_legacy_availability_filter():
    from . import llama_swap_adapter
    original=llama_swap_adapter.LlamaSwapDiscovery
    if getattr(original,'verified_manifest_filter',False):return
    class ArtifactAwareDiscovery(original):
        verified_manifest_filter=True
        def __call__(self):
            return verify_configured_artifacts(super().__call__(),self.manifest_path)
    llama_swap_adapter.LlamaSwapDiscovery=ArtifactAwareDiscovery
