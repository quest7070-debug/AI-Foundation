"""Trusted host mapping from authenticated UI metadata to capability envelopes."""
from __future__ import annotations
from .capability_request import CapabilityRequest

_ALLOWED=frozenset({'CHAT','SEARCH','CODE','DATA','COMPUTE','FILES','BROWSER','PC_CONTROL','VISION'})

def build_daily_capability(headers,payload,attachments=None,*,repo_roots=None,file_roots=None,pc_targets=None,data_operations=None,compute_profiles=None,browser_targets=None,file_write_roots=None,ambient_scopes=None):
    cap=(headers.get('X-Foundation-Capability','CHAT') or 'CHAT').upper()
    if cap not in _ALLOWED: raise ValueError('invalid capability')
    owner=headers.get('X-Foundation-Owner','')
    attachment_ids=attachments.attachment_ids if attachments is not None else ()
    attachment_grants=attachments.attachments if attachments is not None and hasattr(attachments,'attachments') else ()
    owner=attachments.owner_id if attachments is not None else owner
    key=headers.get('X-Foundation-Scope','')
    ambient=ambient_scopes or {}
    if cap=='CHAT' and key=='daily-default':
        repo=(repo_roots or {}).get(ambient.get('repo','')) or ''
        file_root=(file_roots or {}).get(ambient.get('files','')) or ''
        # Output is distinct from read authority. Only a trusted host can
        # publish the output key and a nested approved root; model payloads
        # and arbitrary paths never select a write grant.
        output_root=(file_write_roots or {}).get(ambient.get('output','')) or ''
        op=(data_operations or {}).get(ambient.get('data','')) or ''
        compute=(compute_profiles or {}).get(ambient.get('compute','')) or ''
        browser=(browser_targets or {}).get(ambient.get('browser','')) or ''
        pc=''
    else:
        repo=(repo_roots or {}).get(key) or ''
        file_root=(file_roots or {}).get(key) or ''
        output_root=(file_write_roots or {}).get(key) or ''
        pc=(pc_targets or {}).get(key) or ''
        op=(data_operations or {}).get(key) or ''
        compute=(compute_profiles or {}).get(key) or ''
        browser=(browser_targets or {}).get(key) or ''
    # An anonymous request never carries write authority, even when a
    # configured scope key otherwise matches.
    if cap not in {'CHAT','FILES'} or not owner or headers.get('X-Foundation-Long-Running','')=='1':
        output_root=''
    # Scope keys and ambient defaults select only host-preconfigured grants;
    # arbitrary paths/targets in payload are ignored. PC_CONTROL is never ambient.
    return CapabilityRequest(capability=cap,owner_id=owner,repo_root=repo,file_read_root=file_root,file_write_root=output_root,data_operation=op,compute_profile=compute,browser_target=browser,pc_target=pc,attachments=attachment_grants,attachment_ids=attachment_ids,long_running=headers.get('X-Foundation-Long-Running','')=='1')
