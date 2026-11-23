import pytest
from ai_foundation.capability_factory import build_daily_capability
from ai_foundation.capability_request import CapabilityRequest

def test_host_mapping_ignores_prompt_and_payload_authority():
 h={'X-Foundation-Capability':'CODE','X-Foundation-Scope':'project-a','X-Foundation-Owner':'u'}
 r=build_daily_capability(h,{'repo_root':'/evil'},repo_roots={'project-a':'/trusted/repo'})
 assert r.repo_root=='/trusted/repo' and r.capability=='CODE'

def test_unknown_scope_fails_closed_for_scoped_capability():
 with pytest.raises(ValueError):build_daily_capability({'X-Foundation-Capability':'FILES','X-Foundation-Scope':'bad'}, {},file_roots={'ok':'/trusted'})

def test_verified_attachment_context_is_preserved():
 a=CapabilityRequest(owner_id='u',attachment_ids=('f1',))
 r=build_daily_capability({'X-Foundation-Capability':'SEARCH'}, {},a)
 assert r.owner_id=='u' and r.attachment_ids==('f1',)

def test_daily_mode_scope_keys_map_only_host_grants():
 h={'X-Foundation-Owner':'u'}
 search=build_daily_capability(h|{'X-Foundation-Capability':'SEARCH'}, {})
 assert search.capability=='SEARCH'
 code=build_daily_capability(h|{'X-Foundation-Capability':'CODE','X-Foundation-Scope':'repo-default'}, {'repo_root':'/evil'},repo_roots={'repo-default':'/trusted/repo'})
 assert code.repo_root=='/trusted/repo'
 data=build_daily_capability(h|{'X-Foundation-Capability':'DATA','X-Foundation-Scope':'json-summary'}, {'data_operation':'evil'},data_operations={'json-summary':'json_summary'})
 assert data.data_operation=='json_summary'
 files=build_daily_capability(h|{'X-Foundation-Capability':'FILES','X-Foundation-Scope':'files-default'}, {'file_read_root':'/evil'},file_roots={'files-default':'/trusted/files'})
 assert files.file_read_root=='/trusted/files'

def test_verified_attachment_grants_are_preserved(tmp_path):
 p=tmp_path/'a.txt';p.write_text('trusted')
 from ai_foundation.capability_request import AttachmentGrant
 a=CapabilityRequest(owner_id='u',attachment_ids=('f1',),attachments=(AttachmentGrant('f1','u',str(p.resolve())),))
 r=build_daily_capability({'X-Foundation-Capability':'SEARCH'}, {},a)
 assert r.attachments==a.attachments and r.attachment_ids==('f1',)

def test_chat_envelope_can_carry_host_repo_grant_for_auto_agent():
 h={
  'X-Foundation-Owner':'u',
  'X-Foundation-Capability':'CHAT',
  'X-Foundation-Scope':'repo-default',
 }
 r=build_daily_capability(
  h,
  {'repo_root':'/evil'},
  repo_roots={'repo-default':'/trusted/repo'},
 )
 assert r.capability=='CHAT'
 assert r.repo_root=='/trusted/repo'


def test_browser_and_compute_scope_keys_map_only_host_grants():
 h={'X-Foundation-Owner':'u','X-Foundation-Scope':'interactive-default'}
 browser=build_daily_capability(
  h|{'X-Foundation-Capability':'BROWSER'},
  {'browser_target':'profile:evil'},
  browser_targets={'interactive-default':'profile:foundation'},
 )
 assert browser.browser_target=='profile:foundation'
 compute=build_daily_capability(
  h|{'X-Foundation-Capability':'COMPUTE'},
  {'compute_profile':'sandbox:evil'},
  compute_profiles={'interactive-default':'sandbox:analysis'},
 )
 assert compute.compute_profile=='sandbox:analysis'

def test_browser_and_compute_unknown_scope_fail_closed():
 with pytest.raises(ValueError):
  build_daily_capability(
   {'X-Foundation-Capability':'BROWSER','X-Foundation-Scope':'bad'},
   {'browser_target':'profile:evil'},
   browser_targets={'ok':'profile:foundation'},
  )
 with pytest.raises(ValueError):
  build_daily_capability(
   {'X-Foundation-Capability':'COMPUTE','X-Foundation-Scope':'bad'},
   {'compute_profile':'sandbox:evil'},
   compute_profiles={'ok':'sandbox:analysis'},
  )


def test_chat_daily_ambient_defaults_compose_multiple_host_grants():
    r = build_daily_capability(
        {
            'X-Foundation-Owner': 'u',
            'X-Foundation-Capability': 'CHAT',
            'X-Foundation-Scope': 'daily-default',
        },
        {},
        repo_roots={'repo-default': '/trusted/repo'},
        file_roots={'files-default': '/trusted/files'},
        data_operations={'json-summary': 'json_summary'},
        compute_profiles={'compute-default': 'sandbox:analysis'},
        browser_targets={'browser-default': 'profile:foundation'},
        ambient_scopes={
            'repo': 'repo-default',
            'files': 'files-default',
            'data': 'json-summary',
            'compute': 'compute-default',
            'browser': 'browser-default',
        },
    )

    assert r.capability == 'CHAT'
    assert r.repo_root == '/trusted/repo'
    assert r.file_read_root == '/trusted/files'
    assert r.data_operation == 'json_summary'
    assert r.compute_profile == 'sandbox:analysis'
    assert r.browser_target == 'profile:foundation'
    assert r.pc_target == ''


def test_chat_daily_ambient_defaults_ignore_prompt_and_payload_authority():
    r = build_daily_capability(
        {
            'X-Foundation-Owner': 'u',
            'X-Foundation-Capability': 'CHAT',
            'X-Foundation-Scope': 'daily-default',
        },
        {
            'repo_root': '/evil',
            'file_read_root': '/evil-files',
            'data_operation': 'evil',
            'compute_profile': 'evil-compute',
            'browser_target': 'evil-browser',
            'pc_target': 'evil-pc',
            'ambient_scopes': {'repo': 'evil'},
        },
        repo_roots={'repo-default': '/trusted/repo'},
        file_roots={'files-default': '/trusted/files'},
        data_operations={'json-summary': 'json_summary'},
        ambient_scopes={
            'repo': 'repo-default',
            'files': 'files-default',
            'data': 'json-summary',
        },
    )

    assert r.repo_root == '/trusted/repo'
    assert r.file_read_root == '/trusted/files'
    assert r.data_operation == 'json_summary'
    assert r.compute_profile == ''
    assert r.browser_target == ''
    assert r.pc_target == ''


def test_explicit_diagnostic_scope_does_not_gain_unrequested_ambient_authority():
    r = build_daily_capability(
        {
            'X-Foundation-Owner': 'u',
            'X-Foundation-Capability': 'CODE',
            'X-Foundation-Scope': 'repo-default',
        },
        {},
        repo_roots={'repo-default': '/trusted/repo'},
        file_roots={'files-default': '/trusted/files'},
        data_operations={'json-summary': 'json_summary'},
        ambient_scopes={
            'repo': 'repo-default',
            'files': 'files-default',
            'data': 'json-summary',
        },
    )

    assert r.capability == 'CODE'
    assert r.repo_root == '/trusted/repo'
    assert r.file_read_root == ''
    assert r.data_operation == ''
    assert r.compute_profile == ''
    assert r.browser_target == ''
    assert r.pc_target == ''


def test_chat_daily_ambient_defaults_fail_closed_when_host_mapping_is_missing():
    r = build_daily_capability(
        {
            'X-Foundation-Owner': 'u',
            'X-Foundation-Capability': 'CHAT',
            'X-Foundation-Scope': 'daily-default',
        },
        {},
        repo_roots={},
        data_operations={},
        ambient_scopes={
            'repo': 'missing-repo',
            'data': 'missing-data',
        },
    )

    assert r.capability == 'CHAT'
    assert r.repo_root == ''
    assert r.data_operation == ''
    assert r.pc_target == ''


def test_scope_free_chat_does_not_receive_ambient_authority():
    r = build_daily_capability(
        {
            'X-Foundation-Owner': 'u',
            'X-Foundation-Capability': 'CHAT',
        },
        {},
        repo_roots={'repo-default': '/trusted/repo'},
        file_roots={'files-default': '/trusted/files'},
        data_operations={'json-summary': 'json_summary'},
        ambient_scopes={
            'repo': 'repo-default',
            'files': 'files-default',
            'data': 'json-summary',
        },
    )

    assert r.capability == 'CHAT'
    assert r.repo_root == ''
    assert r.file_read_root == ''
    assert r.data_operation == ''
    assert r.compute_profile == ''
    assert r.browser_target == ''
    assert r.pc_target == ''
