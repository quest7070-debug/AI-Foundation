"""Independent reader lifetimes, snapshot identity and process ownership."""
import os
from pathlib import Path
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from ai_foundation.attachment_handoff import AttachmentHandoff, AttachmentRecord


def handoff(root):
    return AttachmentHandoff(root, lambda *_: AttachmentRecord('file', 'owner', text='original'))


def aged_grant(h):
    grant = h.resolve('owner', ['file'])[0]
    os.utime(grant.path, (100, 100))
    return grant


def test_nested_readers_keep_protection_until_last_release(tmp_path):
    h = handoff(tmp_path)
    grant = aged_grant(h)
    h.acquire(grant)
    h.acquire(grant)
    h.release(grant)
    assert h.cleanup(max_age_seconds=1, now=200) == ()
    assert Path(grant.path).read_text() == 'original'
    h.release(grant)
    assert h.cleanup(max_age_seconds=1, now=200) == (Path(grant.path).name,)


def test_distinct_handoffs_cannot_release_each_others_readers(tmp_path):
    first, second = handoff(tmp_path), handoff(tmp_path)
    grant = aged_grant(first)
    first.acquire(grant)
    second.acquire(grant)
    first.release(grant)
    first.release(grant)  # unmatched release is harmless
    assert first.cleanup(max_age_seconds=1, now=200) == ()
    second.release(grant)
    assert first.cleanup(max_age_seconds=1, now=200) == (Path(grant.path).name,)


def test_changed_upstream_text_does_not_replace_active_snapshot(tmp_path):
    records = {'text': 'original'}
    h = AttachmentHandoff(tmp_path, lambda *_: AttachmentRecord('file', 'owner', text=records['text']))
    old = h.resolve('owner', ['file'])[0]
    h.acquire(old)
    try:
        records['text'] = 'updated'
        new = h.resolve('owner', ['file'])[0]
        assert new.path != old.path
        assert Path(old.path).read_text() == 'original'
        assert Path(new.path).read_text() == 'updated'
    finally:
        h.release(old)


def test_deleted_snapshot_cannot_acquire_a_phantom_lease(tmp_path):
    h = handoff(tmp_path)
    grant = aged_grant(h)
    h.cleanup(max_age_seconds=1, now=200)
    with pytest.raises(FileNotFoundError):
        h.acquire(grant)
    assert not list(h.handoff_root.glob('*.lease'))


def test_parallel_materializations_do_not_share_temporary_files(tmp_path):
    with ThreadPoolExecutor(max_workers=8) as pool:
        grants = list(pool.map(lambda _: handoff(tmp_path).resolve('owner', ['file'])[0], range(24)))
    assert len({g.path for g in grants}) == 1
    assert Path(grants[0].path).read_text() == 'original'
    assert not list(handoff(tmp_path).handoff_root.glob('*.tmp'))


def test_dead_reader_recovery_preserves_other_live_markers(tmp_path):
    h = handoff(tmp_path)
    grant = aged_grant(h)
    h.acquire(grant)
    dead = Path(grant.path + '.dead.lease')
    dead.write_text('999999999\n1\n')
    assert h.recover_stale_leases(pid_alive=lambda pid: pid == os.getpid()) == (dead.name,)
    assert h.cleanup(max_age_seconds=1, now=200) == ()
    h.release(grant)


def test_independent_process_reader_survives_parent_release(tmp_path):
    h = handoff(tmp_path)
    grant = aged_grant(h)
    h.acquire(grant)
    code = '''
import sys
from ai_foundation.attachment_handoff import AttachmentHandoff, AttachmentRecord
h=AttachmentHandoff(sys.argv[1],lambda *_:AttachmentRecord('file','owner',text='original'))
g=h.resolve('owner',['file'])[0]
h.acquire(g)
print('READY',flush=True)
sys.stdin.readline()
h.release(g)
'''
    with subprocess.Popen([sys.executable, '-c', code, str(tmp_path)], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as child:
        try:
            assert child.stdout.readline().strip() == 'READY'
            os.utime(grant.path, (100, 100))
            h.release(grant)
            assert h.cleanup(max_age_seconds=1, now=200) == ()
            assert Path(grant.path).read_text() == 'original'
            _, stderr = child.communicate('\n', timeout=10)
            assert child.returncode == 0, stderr
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=10)
    assert h.cleanup(max_age_seconds=1, now=200) == (Path(grant.path).name,)
