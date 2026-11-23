"""Trusted daily artifact output grants; no implicit write authority from chat."""
import pytest

from ai_foundation.capability_factory import build_daily_capability


def granted(tmp_path, *, owner="owner", long_running=False):
    read = tmp_path / "files"
    read.mkdir()
    output = read / "output"
    output.mkdir()
    headers = {
        "X-Foundation-Capability": "CHAT",
        "X-Foundation-Scope": "daily-default",
        "X-Foundation-Owner": owner,
    }
    if long_running:
        headers["X-Foundation-Long-Running"] = "1"
    options = {
        "file_roots": {"files-default": str(read)},
        "file_write_roots": {"output-default": str(output)},
        "ambient_scopes": {"files": "files-default", "output": "output-default"},
    }
    return headers, options, read, output


def test_daily_output_requires_host_mapped_write_scope(tmp_path):
    headers, options, read, output = granted(tmp_path)
    result = build_daily_capability(headers, {}, **options)
    assert result.file_read_root == str(read)
    assert result.file_write_root == str(output)
    assert result.owner_id == "owner"


def test_existing_read_only_daily_scope_remains_read_only(tmp_path):
    headers, options, read, _ = granted(tmp_path)
    without_output = {**options, "file_write_roots": {}}
    result = build_daily_capability(headers, {"file_write_root": "/tmp/untrusted"},
                                    **without_output)
    assert result.file_read_root == str(read)
    assert result.file_write_root == ""


def test_host_requires_distinct_explicit_ambient_output_selection(tmp_path):
    headers, options, _, _ = granted(tmp_path)
    without_key = {**options, "ambient_scopes": {"files": "files-default"}}
    result = build_daily_capability(headers, {"ambient_scopes": {"output": "output-default"}},
                                    **without_key)
    assert result.file_write_root == ""


def test_payload_cannot_invent_output_root_or_override_host_mapping(tmp_path):
    headers, options, _, output = granted(tmp_path)
    for attack in (
        {"file_write_root": "/tmp/evil"},
        {"output_root": "/tmp/evil"},
        {"file_write_roots": {"output-default": "/tmp/evil"}},
        {"ambient_scopes": {"output": "/tmp/evil"}},
    ):
        result = build_daily_capability(headers, attack, **options)
        assert result.file_write_root == str(output)


def test_owner_and_long_running_gates_remove_output_grant(tmp_path):
    headers, options, _, _ = granted(tmp_path, owner="")
    assert build_daily_capability(headers, {}, **options).file_write_root == ""
    headers["X-Foundation-Owner"] = "owner"
    headers["X-Foundation-Long-Running"] = "1"
    result = build_daily_capability(headers, {}, **options)
    assert result.long_running and result.file_write_root == ""


def test_scoped_nonambient_output_needs_matching_explicit_trusted_read_root(tmp_path):
    headers, options, read, output = granted(tmp_path)
    headers["X-Foundation-Capability"] = "FILES"
    headers["X-Foundation-Scope"] = "explicit-output"
    result = build_daily_capability(
        headers, {"file_write_root": "/tmp/evil"},
        file_roots={"explicit-output": str(read)},
        file_write_roots={"explicit-output": str(output)},
    )
    assert result.file_write_root == str(output)
    assert result.file_read_root == str(read)
    with pytest.raises(ValueError, match="write scope requires read scope"):
        build_daily_capability(
            headers, {}, file_write_roots={"explicit-output": str(output)},
        )


def test_output_root_outside_trusted_read_area_is_denied(tmp_path):
    headers, options, _, _ = granted(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(PermissionError, match="write scope must be inside read scope"):
        build_daily_capability(
            headers, {}, **{**options, "file_write_roots": {"output-default": str(outside)}},
        )


def test_scope_free_chat_and_wrong_key_receive_no_artifact_output(tmp_path):
    headers, options, _, _ = granted(tmp_path)
    headers.pop("X-Foundation-Scope")
    assert build_daily_capability(headers, {}, **options).file_write_root == ""
    headers["X-Foundation-Scope"] = "wrong-key"
    assert build_daily_capability(headers, {}, **options).file_write_root == ""


def test_default_production_call_without_host_output_roots_is_unchanged(tmp_path):
    headers, options, _, _ = granted(tmp_path)
    original = build_daily_capability(
        headers, {"file_write_root": "/tmp/evil"},
        file_roots=options["file_roots"],
        ambient_scopes=options["ambient_scopes"],
    )
    assert original.file_write_root == ""


def test_other_capability_alias_cannot_inherit_output_even_if_key_collides(tmp_path):
    headers, options, _, _ = granted(tmp_path)
    headers["X-Foundation-Capability"] = "CODE"
    headers["X-Foundation-Scope"] = "combined"
    result = build_daily_capability(
        headers, {},
        repo_roots={"combined": str(tmp_path)},
        file_roots={"combined": str(tmp_path)},
        file_write_roots={"combined": str(tmp_path)},
    )
    assert result.capability == "CODE"
    assert result.file_write_root == ""
