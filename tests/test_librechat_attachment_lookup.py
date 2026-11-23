from ai_foundation.librechat_attachment_lookup import LibreChatAttachmentLookup

def test_lookup_queries_owner_and_maps_container_upload_path(tmp_path):
 root=tmp_path/'uploads';root.mkdir();p=root/'u'/'a.txt';p.parent.mkdir();p.write_text('x');seen=[]
 def q(query):seen.append(query);return {'filepath':'/app/uploads/u/a.txt'}
 r=LibreChatAttachmentLookup(root,q)('f','owner','tenant')
 assert seen==[{'file_id':'f','user':'owner','tenantId':'tenant'}] and r.path==str(p.resolve())

def test_lookup_rejects_absolute_non_upload_and_traversal(tmp_path):
 root=tmp_path/'uploads';root.mkdir()
 assert LibreChatAttachmentLookup(root,lambda q:{'filepath':'/etc/passwd'})('f','o') is None
 assert LibreChatAttachmentLookup(root,lambda q:{'filepath':'../secret'})('f','o') is None
 assert LibreChatAttachmentLookup(root,lambda q:{'filepath':'x'})('f','') is None


def test_lookup_composes_with_handoff_and_requires_real_file(tmp_path):
 from ai_foundation.attachment_handoff import AttachmentHandoff
 root=tmp_path/'uploads';root.mkdir();p=root/'u'/'a.txt';p.parent.mkdir();p.write_text('x')
 lookup=LibreChatAttachmentLookup(root,lambda q:{'filepath':'/app/uploads/u/a.txt'} if q['user']=='owner' else None)
 grants=AttachmentHandoff(root,lookup).resolve('owner',['f'])
 assert grants[0].path==str(p.resolve())

def test_lookup_prefers_owner_scoped_extracted_text_over_expired_temp_path(tmp_path):
 root=tmp_path/'uploads';root.mkdir()
 r=LibreChatAttachmentLookup(root,lambda q:{'filepath':'/app/uploads/temp/gone.txt','text':'persisted trusted text'})('f','owner')
 assert r.text=='persisted trusted text' and r.owner_id=='owner'


def test_lookup_maps_librechat_public_image_path_inside_trusted_root(tmp_path):
    root=tmp_path/'uploads'
    root.mkdir()
    images=tmp_path/'images'
    images.mkdir()

    p=images/'owner'/'image.png'
    p.parent.mkdir(parents=True)
    p.write_bytes(b'png')

    lookup=LibreChatAttachmentLookup(
        root,
        lambda q:{
            'filepath':'/images/owner/image.png',
            'type':'image/png',
        } if q=={'file_id':'img','user':'owner'} else None,
        images_root=images,
    )

    r=lookup('img','owner')

    assert r is not None
    assert r.path==str(p.resolve())


def test_lookup_rejects_public_image_path_without_explicit_image_root(tmp_path):
    root=tmp_path/'uploads'
    root.mkdir()

    lookup=LibreChatAttachmentLookup(
        root,
        lambda q:{'filepath':'/images/owner/image.png'},
    )

    assert lookup('img','owner') is None


def test_lookup_rejects_image_root_traversal(tmp_path):
    root=tmp_path/'uploads'
    root.mkdir()
    images=tmp_path/'images'
    images.mkdir()

    lookup=LibreChatAttachmentLookup(
        root,
        lambda q:{'filepath':'/images/../../secret'},
        images_root=images,
    )

    assert lookup('img','owner') is None


def test_attachment_handoff_accepts_explicit_trusted_image_root(tmp_path):
    from ai_foundation.attachment_handoff import AttachmentHandoff
    from ai_foundation.librechat_attachment_lookup import LibreChatAttachmentLookup

    uploads = tmp_path / "uploads"
    images = tmp_path / "images"
    uploads.mkdir()
    images.mkdir()

    owner = "owner-1"
    image_dir = images / owner
    image_dir.mkdir()
    image = image_dir / "sample.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\npayload")

    def query_one(query):
        if query == {"file_id": "img-1", "user": owner}:
            return {
                "file_id": "img-1",
                "user": owner,
                "filepath": f"/images/{owner}/sample.png",
            }
        return None

    lookup = LibreChatAttachmentLookup(
        uploads,
        query_one,
        images_root=images,
    )

    handoff = AttachmentHandoff(
        uploads,
        lookup,
        trusted_roots=(uploads, images),
    )

    grants = handoff.resolve(owner, ("img-1",))

    assert len(grants) == 1
    assert grants[0].owner_id == owner
    assert grants[0].attachment_id == "img-1"
    assert grants[0].path == str(image.resolve())


def test_attachment_handoff_rejects_path_outside_all_trusted_roots(tmp_path):
    from ai_foundation.attachment_handoff import AttachmentHandoff, AttachmentRecord

    uploads = tmp_path / "uploads"
    images = tmp_path / "images"
    outside = tmp_path / "outside"
    uploads.mkdir()
    images.mkdir()
    outside.mkdir()

    secret = outside / "secret.png"
    secret.write_bytes(b"\x89PNG\r\n\x1a\nsecret")

    def lookup(attachment_id, owner_id):
        return AttachmentRecord(
            attachment_id,
            owner_id,
            str(secret),
        )

    handoff = AttachmentHandoff(
        uploads,
        lookup,
        trusted_roots=(uploads, images),
    )

    import pytest
    with pytest.raises(PermissionError, match="outside trusted attachment roots"):
        handoff.resolve("owner-1", ("img-1",))


def test_attachment_handoff_default_root_contract_remains_single_root(tmp_path):
    from ai_foundation.attachment_handoff import AttachmentHandoff, AttachmentRecord

    uploads = tmp_path / "uploads"
    images = tmp_path / "images"
    uploads.mkdir()
    images.mkdir()

    image = images / "sample.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\npayload")

    def lookup(attachment_id, owner_id):
        return AttachmentRecord(
            attachment_id,
            owner_id,
            str(image),
        )

    handoff = AttachmentHandoff(uploads, lookup)

    import pytest
    with pytest.raises(PermissionError, match="outside trusted attachment roots"):
        handoff.resolve("owner-1", ("img-1",))
