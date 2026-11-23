"""Trusted adapter for LibreChat owner-scoped file metadata.
The caller owns DB access; this adapter never accepts paths from chat/model input.
"""
from __future__ import annotations
from pathlib import Path
from .attachment_handoff import AttachmentRecord

# These are structured document inputs, never native UTF-8 file content.
# LibreChat owns extraction; Foundation consumes only its owner-scoped text.
_DOCUMENT_MIME_TYPES = frozenset({
    'application/pdf', 'application/msword', 'application/rtf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.ms-excel',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.oasis.opendocument.text',
    'application/vnd.oasis.opendocument.spreadsheet',
    'application/vnd.ms-powerpoint',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'application/epub+zip',
})
_DOCUMENT_SUFFIXES = frozenset({'.pdf', '.doc', '.docx', '.xls', '.xlsx',
                                '.odt', '.ods', '.odp', '.ppt', '.pptx', '.epub', '.rtf',
                                '.docm', '.dotx', '.dotm', '.xlsm', '.xltx', '.xltm',
                                '.pptm', '.potx', '.potm', '.ppsx', '.ppsm'})


class DocumentTextUnavailable(ValueError):
    """The owner's structured document has no usable standard extraction."""


def _is_document(doc):
    mime = doc.get('type')
    mime = mime.split(';', 1)[0].strip().lower() if isinstance(mime, str) else ''
    return (mime in _DOCUMENT_MIME_TYPES or mime.startswith((
        'application/vnd.openxmlformats-officedocument.',
        'application/vnd.oasis.opendocument.', 'application/vnd.ms-')) or any(
        isinstance(doc.get(field), str) and Path(doc[field]).suffix.lower() in _DOCUMENT_SUFFIXES
        for field in ('filename', 'filepath')
    ))


class LibreChatAttachmentLookup:
    def __init__(self,uploads_root,query_one,images_root=None):
        self.root=Path(uploads_root).resolve()
        self.images_root=Path(images_root).resolve() if images_root is not None else None
        self.query_one=query_one
    def __call__(self,attachment_id,owner_id=None,tenant_id=None):
        if not attachment_id or not owner_id: return None
        query={'file_id':attachment_id,'user':owner_id}
        if tenant_id: query['tenantId']=tenant_id
        doc=self.query_one(query)
        if not doc:return None
        document=_is_document(doc)
        text=doc.get('text')
        if document and (not isinstance(text,str) or not text.strip()):
            raise DocumentTextUnavailable('document text extraction required')
        if text is not None:
            if not isinstance(text,str): return None
            return AttachmentRecord(attachment_id,owner_id,text=text)
        raw=doc.get('filepath')
        if not isinstance(raw,str) or not raw:return None
        # LibreChat DB paths map only through explicitly trusted host roots.
        upload_marker='/app/uploads/'
        image_marker='/images/'

        if raw.startswith(upload_marker):
            root=self.root
            rel=raw[len(upload_marker):]
        elif raw.startswith(image_marker) and self.images_root is not None:
            root=self.images_root
            rel=raw[len(image_marker):]
        elif not raw.startswith('/'):
            root=self.root
            rel=raw
        else:
            return None

        path=(root/rel).resolve()
        try:path.relative_to(root)
        except ValueError:return None
        return AttachmentRecord(attachment_id,owner_id,str(path))

