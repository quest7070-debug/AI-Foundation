"""Synthetic archived binary extraction without any download or execution."""
import zipfile
import pytest
from scripts.extract_verified_uv_wheel import extract_uv


def test_extract_only_uv_binary(tmp_path):
    wheel = tmp_path / "uv-0.8.22.whl"
    with zipfile.ZipFile(wheel, "w") as z:
        z.writestr("uv/uv", b"synthetic-uv")
        z.writestr("uv/untrusted-script", b"not-extracted")
    destination = tmp_path / "bin/uv"
    extract_uv(wheel, destination)
    assert destination.read_bytes() == b"synthetic-uv"
    assert not (tmp_path / "bin/untrusted-script").exists()
    with pytest.raises(ValueError, match="already exists"):
        extract_uv(wheel, destination)


def test_reject_missing_or_multiple_uv_members(tmp_path):
    wheel = tmp_path / "uv.whl"
    dest = tmp_path / "uv"
    for names in [
        ["uv/private"],
        ["uv/uv", "uv-0.8.22.data/scripts/uv"],
    ]:
        with zipfile.ZipFile(wheel, "w") as z:
            for name in names:
                z.writestr(name, b"not-executable")
        with pytest.raises(ValueError, match="exactly one"):
            extract_uv(wheel, dest)
        assert not dest.exists()
