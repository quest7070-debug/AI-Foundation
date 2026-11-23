from pathlib import Path
import pytest
from ai_foundation.capability_request import CapabilityRequest,AttachmentGrant

def test_chat_has_no_ambient_authority():
 r=CapabilityRequest(); assert r.capability=='CHAT' and not r.repo_root

def test_code_requires_host_resolved_repo(tmp_path):
 with pytest.raises(ValueError): CapabilityRequest('CODE')
 with pytest.raises(ValueError): CapabilityRequest('CODE',repo_root='relative')
 assert CapabilityRequest('CODE',repo_root=str(tmp_path)).repo_root==str(tmp_path)

def test_files_write_must_be_inside_read(tmp_path):
 read=tmp_path/'read'; write=read/'write'; other=tmp_path/'other'
 CapabilityRequest('FILES',file_read_root=str(read),file_write_root=str(write))
 with pytest.raises(PermissionError): CapabilityRequest('FILES',file_read_root=str(read),file_write_root=str(other))

def test_data_and_pc_require_host_bound_fields():
 with pytest.raises(ValueError): CapabilityRequest('DATA')
 with pytest.raises(ValueError): CapabilityRequest('PC_CONTROL')
 assert CapabilityRequest('DATA',data_operation='analyze').data_operation=='analyze'
 assert CapabilityRequest('PC_CONTROL',pc_target='desktop:primary').pc_target=='desktop:primary'

def test_attachment_owner_cannot_be_mixed(tmp_path):
 a=AttachmentGrant('a1','owner-a',str(tmp_path/'a'))
 assert CapabilityRequest(owner_id='owner-a',attachments=(a,)).attachments==(a,)
 with pytest.raises(PermissionError): CapabilityRequest(owner_id='owner-b',attachments=(a,))
 with pytest.raises(ValueError): AttachmentGrant('a1','owner-a','relative')

def test_attachment_ids_are_owner_bound_and_bounded():
 with pytest.raises(ValueError): CapabilityRequest(attachment_ids=('f1',))
 r=CapabilityRequest(owner_id='u1',attachment_ids=('f1','f2'))
 assert r.attachment_ids==('f1','f2')
 with pytest.raises(ValueError): CapabilityRequest(owner_id='u1',attachment_ids=('f1','f1'))


def test_files_accepts_verified_attachment_without_general_read_root(tmp_path):
    p=tmp_path/'note.txt'
    p.write_text('hello')
    a=AttachmentGrant('f1','u1',str(p.resolve()))
    r=CapabilityRequest('FILES',owner_id='u1',attachments=(a,),attachment_ids=('f1',))
    assert r.file_read_root==''
    assert r.attachments==(a,)


def test_files_without_root_or_attachment_cannot_mint_authority():
    with pytest.raises(ValueError):
        CapabilityRequest('FILES',owner_id='u1')


def test_browser_and_compute_require_explicit_host_authority():
 with pytest.raises(ValueError): CapabilityRequest('BROWSER')
 with pytest.raises(ValueError): CapabilityRequest('COMPUTE')
 assert CapabilityRequest('BROWSER',browser_target='profile:foundation').browser_target=='profile:foundation'
 assert CapabilityRequest('COMPUTE',compute_profile='sandbox:analysis').compute_profile=='sandbox:analysis'


def test_data_backend_is_host_selected_and_exclusive():
 assert CapabilityRequest('DATA',data_backend='data-duckdb').data_backend=='data-duckdb'
 with pytest.raises(ValueError): CapabilityRequest('DATA',data_operation='json_summary',data_backend='data-duckdb')
