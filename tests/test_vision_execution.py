from pathlib import Path
import pytest
from ai_foundation.capability_request import CapabilityRequest,AttachmentGrant
from ai_foundation.vision_execution import VisionExecutionPort

PNG=b"\x89PNG\r\n\x1a\n"+b"0"*32
class Backend:
    name="fake-vision"
    def __init__(self):self.calls=[]
    def analyze(self,paths,task):self.calls.append((paths,task));return "observed pixels"
class Handoff:
    def __init__(self):self.events=[]
    def acquire(self,g):self.events.append(("acquire",g.attachment_id));return True
    def release(self,g):self.events.append(("release",g.attachment_id))
def req(path,owner="u"):
    return CapabilityRequest("VISION",owner_id=owner,attachments=(AttachmentGrant("a",owner,str(path)),))
def test_observation_is_non_authoritative_and_leased(tmp_path):
    p=tmp_path/"x.png";p.write_bytes(PNG);b=Backend();h=Handoff()
    out=VisionExecutionPort(b,h).observe(req(p),"describe")
    assert out.text=="observed pixels" and out.authoritative is False and out.backend=="fake-vision"
    assert h.events==[("acquire","a"),("release","a")]
def test_rejects_non_image_before_backend(tmp_path):
    p=tmp_path/"x.txt";p.write_text("not image");b=Backend()
    with pytest.raises(ValueError):VisionExecutionPort(b).observe(req(p),"describe")
    assert b.calls==[]
def test_backend_failure_releases_lease(tmp_path):
    p=tmp_path/"x.png";p.write_bytes(PNG);h=Handoff()
    class Fail:
        def analyze(self,paths,task):raise RuntimeError("fail")
    with pytest.raises(RuntimeError):VisionExecutionPort(Fail(),h).observe(req(p),"describe")
    assert h.events==[("acquire","a"),("release","a")]

def test_rejects_symlink_before_backend(tmp_path):
    real=tmp_path/"real.png";real.write_bytes(PNG)
    link=tmp_path/"link.png";link.symlink_to(real)
    b=Backend()

    with pytest.raises(ValueError,match="invalid image attachment"):
        VisionExecutionPort(b).observe(req(link),"describe")

    assert b.calls==[]


def test_rejects_oversized_image_before_backend(tmp_path):
    p=tmp_path/"large.png";p.write_bytes(PNG)
    b=Backend()

    with pytest.raises(ValueError,match="size rejected"):
        VisionExecutionPort(b,max_bytes=len(PNG)-1).observe(req(p),"describe")

    assert b.calls==[]
