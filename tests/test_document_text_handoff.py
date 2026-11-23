import pytest
from ai_foundation.attachment_handoff import AttachmentHandoff
from ai_foundation.capability_execution import CapabilityExecutor
from ai_foundation.capability_request import CapabilityRequest
from ai_foundation.librechat_attachment_lookup import LibreChatAttachmentLookup, DocumentTextUnavailable
from ai_foundation.librechat_mongo_lookup import LibreChatMongoQuery


@pytest.mark.parametrize('mime,name', [
    ('application/pdf', 'document.pdf'),
    ('application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'document.docx'),
    ('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'document.xlsx'),
])
def test_standard_extracted_text_reaches_files_without_opening_original(tmp_path, mime, name):
    text = '標準抽出の原文\nセルA,セルB\n'
    queries = []
    def query(q):
        queries.append(q)
        return {'type': mime, 'filename': name, 'filepath': '/app/uploads/missing/' + name,
                'text': text} if q == {'file_id': 'doc', 'user': 'owner', 'tenantId': 'tenant'} else None
    lookup = LibreChatAttachmentLookup(tmp_path, query)
    h = AttachmentHandoff(tmp_path, lambda aid, owner: lookup(aid, owner, 'tenant'))
    grants = h.resolve('owner', ('doc',))
    request = CapabilityRequest('FILES', owner_id='owner', attachment_ids=('doc',), attachments=grants)
    assert CapabilityExecutor(None, None, attachment_handoff=h).execute(request, '', 'test-document') == text
    assert queries == [{'file_id': 'doc', 'user': 'owner', 'tenantId': 'tenant'}]
    with pytest.raises(FileNotFoundError): h.resolve('foreign', ('doc',))


@pytest.mark.parametrize('metadata', [
    {'type': 'application/pdf', 'filepath': '/app/uploads/original'},
    {'type': ' Application/PDF; charset=binary ', 'filepath': '/app/uploads/original'},
    {'filename': 'DOCUMENT.DOCX', 'filepath': '/app/uploads/original'},
    {'filepath': '/app/uploads/owner/data.xlsx'},
    {'type': 'application/vnd.ms-powerpoint', 'filepath': '/app/uploads/original'},
    {'filename': 'legacy.doc', 'filepath': '/app/uploads/original'},
])
@pytest.mark.parametrize('text', [None, '', '  \n', 123])
def test_document_without_standard_extraction_never_falls_back_to_binary(tmp_path, metadata, text):
    lookup = LibreChatAttachmentLookup(tmp_path, lambda _: {**metadata, 'text': text})
    with pytest.raises(DocumentTextUnavailable, match='text extraction required'):
        AttachmentHandoff(tmp_path, lookup).resolve('owner', ('doc',))
    assert not (tmp_path / '.foundation-handoff').exists()


def test_plain_text_and_vision_paths_remain_available_without_extracted_text(tmp_path):
    for name, mime in [('note.txt', 'text/plain'), ('photo.png', 'image/png')]:
        lookup = LibreChatAttachmentLookup(tmp_path, lambda _: {'type': mime, 'filepath': '/app/uploads/' + name})
        assert lookup('f', 'owner').path == str(tmp_path / name)


def test_host_mongo_projection_includes_document_type_and_filename(monkeypatch):
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        # The real Mongo projection always carries exact owner/file identity.
        # An ownerless synthetic row is no longer accepted by the trusted port.
        return type('Result', (), {'returncode': 0, 'stdout': '{"file_id":"doc","user":"aaaaaaaaaaaaaaaaaaaaaaaa","type":"application/pdf","filename":"probe.pdf","text":"synthetic"}'})()
    monkeypatch.setattr('ai_foundation.librechat_mongo_lookup.subprocess.run', run)
    result = LibreChatMongoQuery()({'file_id': 'doc', 'user': 'a' * 24})
    assert result['type'] == 'application/pdf'
    assert 'type:1,filename:1' in calls[0][-1]
