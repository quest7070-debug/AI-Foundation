from pathlib import Path


def test_toolhive_health_probes_use_composed_ports():
 src=Path('scripts/operator_server.py').read_text()
 assert "composition.file_port._wait_running" in src
 assert "composition.repo_port._wait_running" in src
 assert "composition.files_port" not in src and "composition.code_port" not in src



def test_owner_stable_toolhive_requires_exact_pinned_archive_and_cli_hash(tmp_path):
 from hashlib import sha256
 from ai_foundation.toolhive_owner_runtime import (
     TOOLHIVE_OWNER_DIR, TOOLHIVE_ARCHIVE_SHA256, owner_toolhive_binary)
 root=tmp_path/TOOLHIVE_OWNER_DIR
 root.mkdir(parents=True)
 root.chmod(0o700)
 executable=root/'thv'
 executable.write_bytes(b'SYNTHETIC_TEST_BINARY')
 executable.chmod(0o700)
 (root/'archive.sha256').write_text(TOOLHIVE_ARCHIVE_SHA256+'\n')
 (root/'executable.sha256').write_text(
     sha256(executable.read_bytes()).hexdigest()+'\n')
 assert owner_toolhive_binary(tmp_path)==executable
 executable.write_bytes(b'TAMPERED')
 assert owner_toolhive_binary(tmp_path) is None
 executable.write_bytes(b'SYNTHETIC_TEST_BINARY')
 (root/'archive.sha256').write_text('untrusted')
 assert owner_toolhive_binary(tmp_path) is None
 (root/'archive.sha256').write_text(TOOLHIVE_ARCHIVE_SHA256)
 root.chmod(0o777)
 assert owner_toolhive_binary(tmp_path) is None



def test_verified_toolhive_go_binary_can_exceed_old_64mb_cap(tmp_path, monkeypatch):
 from hashlib import sha256
 import os
 from ai_foundation.toolhive_owner_runtime import (
     TOOLHIVE_OWNER_DIR, TOOLHIVE_ARCHIVE_SHA256,
     TOOLHIVE_EXECUTABLE_MAX_BYTES, owner_toolhive_binary)
 root=tmp_path/TOOLHIVE_OWNER_DIR
 root.mkdir(parents=True)
 root.chmod(0o700)
 executable=root/'thv'
 executable.write_bytes(b'SYNTHETIC_PINNED_CLI')
 executable.chmod(0o700)
 (root/'archive.sha256').write_text(TOOLHIVE_ARCHIVE_SHA256+'\n')
 (root/'executable.sha256').write_text(
     sha256(executable.read_bytes()).hexdigest()+'\n')
 original=Path.lstat
 simulated_size=[80_000_000]
 def fake_lstat(path,*args,**kwargs):
     info=original(path,*args,**kwargs)
     if Path(path)!=executable:
         return info
     fields=list(info)
     fields[6]=simulated_size[0]
     return os.stat_result(fields)
 monkeypatch.setattr(Path,'lstat',fake_lstat)
 assert 64_000_000 < simulated_size[0] < TOOLHIVE_EXECUTABLE_MAX_BYTES
 assert owner_toolhive_binary(tmp_path)==executable
 simulated_size[0]=TOOLHIVE_EXECUTABLE_MAX_BYTES+1
 assert owner_toolhive_binary(tmp_path) is None


def test_installed_operator_only_uses_owner_stable_oss_cli_not_stage_cache():
 entry=Path('scripts/operator_server.py').read_text()
 release=Path('scripts/m1_github_owner_operator_release.py').read_text()
 assert 'thv=owner_toolhive_binary()' in entry
 assert 'if thv is not None:' in entry
 assert 'prepare_pinned_toolhive(home)' in release
 assert release.index('GUARD_OWNER_DECISION_DENIED') < release.index(
     '    prepare_pinned_toolhive(home)')
 assert "scripts/bootstrap-toolhive.sh" in release
 assert '"PINNED_TOOLHIVE_BOOTSTRAP_FAILED"' in release
 assert '"PINNED_TOOLHIVE_PROVENANCE_READBACK_FAILED"' in release


def test_operator_toolhive_bootstrap_stages_verified_cli_without_partial_target():
    from pathlib import Path
    shell=Path('scripts/bootstrap-toolhive.sh').read_text()
    controller=Path('scripts/m1_github_owner_operator_release.py').read_text()
    # Any network/verify failure must leave the owner executable absent.
    assert '--retry 3 --retry-all-errors' in shell
    assert 'EXPECTED_SHA256' in shell and 'exit 32' in shell
    assert 'mktemp -d "$ROOT/.bootstrap.XXXXXXXX"' in shell
    assert 'mv "$tmp/verified-thv" "$TARGET"' in shell
    assert shell.index('mv "$tmp/archive.sha256"') < shell.index(
        'mv "$tmp/executable.sha256"') < shell.index(
        'mv "$tmp/verified-thv" "$TARGET"')
    assert 'cp "$found" "$TARGET"' not in shell
    assert 'find "$tmp" -type f -name thv -print -quit' in shell
    assert 'find "$tmp" -type f -name thv -perm -111' not in shell
    assert shell.index('chmod 0700 "$tmp/verified-thv"') < shell.index(
        'version="$("$tmp/verified-thv" version')
    assert '[ ! -L "$ROOT/archive.sha256" ]' in shell
    for code in ('31','32','33','34','35','36','37'):
        assert f'exit {code}' in shell
    for token in (
        'PINNED_TOOLHIVE_ARCHIVE_DOWNLOAD_FAILED',
        'PINNED_TOOLHIVE_ARCHIVE_DIGEST_MISMATCH',
        'PINNED_TOOLHIVE_ARCHIVE_EXTRACT_FAILED',
        'PINNED_TOOLHIVE_EXTRACTED_VERSION_MISMATCH',
    ):
        assert token in controller
    assert 'proc.stderr' not in controller
