"""Real filesystem persistence/reopen and exclusive refresh; no model calls."""
import subprocess
from pathlib import Path

import pytest

from ai_foundation.infigraph_adapter import InfigraphCodeIntelligence
from ai_foundation.infigraph_receipt import InfigraphIndexReceipt
from ai_foundation.code_intelligence import CodeIntelligenceStatus


def setup(tmp_path):
    root=tmp_path/'repo';root.mkdir()
    index=root/'.infigraph';index.mkdir()
    (index/'graph.db').write_bytes(b'persisted local graph')
    executable=tmp_path/'infigraph';executable.write_bytes(b'pinned fixture');executable.chmod(0o700)
    receipt=tmp_path/'private'/'index.json'
    store=InfigraphIndexReceipt(root=root,executable=executable,receipt=receipt)
    return root,executable,receipt,store


def test_commit_reopens_and_validates_all_artifacts(tmp_path):
    root,exe,receipt,store=setup(tmp_path)
    with store.refresh_lock():store.commit('source','3.2.16')
    assert receipt.stat().st_mode & 0o077==0
    assert InfigraphIndexReceipt(root=root,executable=exe,receipt=receipt).verify('source','3.2.16')=='source'


@pytest.mark.parametrize('change',['artifact','extra','missing','source','binary','receipt','symlink'])
def test_drift_never_restores_freshness(tmp_path,change):
    root,exe,receipt,store=setup(tmp_path)
    with store.refresh_lock():store.commit('source','3.2.16')
    if change=='artifact':(root/'.infigraph/graph.db').write_bytes(b'changed')
    if change=='extra':(root/'.infigraph/extra').write_text('new')
    if change=='missing':(root/'.infigraph/graph.db').unlink()
    if change=='binary':exe.write_bytes(b'new executable')
    if change=='receipt':receipt.chmod(0o644)
    if change=='symlink':(root/'.infigraph/alias').symlink_to(exe)
    with pytest.raises((OSError,ValueError)):
        store.verify('changed' if change=='source' else 'source','3.2.16')


def test_refresh_excludes_second_writer(tmp_path):
    root,exe,receipt,store=setup(tmp_path)
    other=InfigraphIndexReceipt(root=root,executable=exe,receipt=receipt)
    with store.refresh_lock():
        with pytest.raises(BlockingIOError):
            with other.refresh_lock():pytest.fail('second writer entered')


def test_refresh_commit_then_new_adapter_restores_without_reindex(tmp_path):
    root,exe,receipt,store=setup(tmp_path)
    calls=[]
    def runner(argv,**kwargs):
        calls.append(argv)
        assert kwargs['env']['INFIGRAPH_BACKEND']=='kuzu'
        return subprocess.CompletedProcess(argv,0,'infigraph 3.2.16\n' if '--version' in argv else '', '')
    backend=InfigraphCodeIntelligence(executable=exe,root=root,runner=runner,
        source_identity=lambda:'source',index_receipt=receipt)
    assert backend.refresh().fresh
    reopened=InfigraphCodeIntelligence(executable=exe,root=root,runner=runner,
        source_identity=lambda:'source',index_receipt=receipt)
    assert reopened._freshness()==(True,'source','')
    assert len(calls)==2
    (root/'.infigraph/graph.db').write_text('drift')
    assert reopened._freshness()[0] is False


def test_failed_refresh_invalidates_previous_receipt(tmp_path):
    root,exe,receipt,store=setup(tmp_path)
    with store.refresh_lock():store.commit('source','3.2.16')
    def runner(argv,**kwargs):
        return subprocess.CompletedProcess(argv,0 if '--version' in argv else 1,'infigraph 3.2.16','failed')
    backend=InfigraphCodeIntelligence(executable=exe,root=root,runner=runner,
        source_identity=lambda:'source',index_receipt=receipt)
    assert backend.refresh().status is CodeIntelligenceStatus.UNAVAILABLE
    assert not receipt.exists()
    assert not backend._freshness()[0]


def test_receipt_cannot_be_inside_source_tree(tmp_path):
    root,exe,receipt,store=setup(tmp_path)
    with pytest.raises(ValueError,match='outside'):
        InfigraphIndexReceipt(root=root,executable=exe,receipt=root/'.infigraph/receipt.json')


def test_source_change_during_commit_does_not_publish_fresh_success(tmp_path):
    root,exe,receipt,store=setup(tmp_path)
    state={'source':'before'}
    def runner(argv,**kwargs):
        return subprocess.CompletedProcess(argv,0,'infigraph 3.2.16','')
    backend=InfigraphCodeIntelligence(executable=exe,root=root,runner=runner,
        source_identity=lambda:state['source'],index_receipt=receipt)
    commit=backend._receipt_store.commit
    def changing_commit(*args):
        commit(*args);state['source']='after'
    backend._receipt_store.commit=changing_commit
    assert backend.refresh().status is CodeIntelligenceStatus.UNAVAILABLE
    assert not receipt.exists()


def test_shared_read_lock_excludes_refresh_writer(tmp_path):
    root, exe, receipt, store = setup(tmp_path)
    with store.read_lock():
        with pytest.raises(BlockingIOError):
            with store.refresh_lock():
                pytest.fail("refresh writer entered while an inventory read held the lock")


def test_relative_executable_path_is_normalized_without_following_symlinks(
    tmp_path, monkeypatch
):
    root, exe, receipt, store = setup(tmp_path)
    monkeypatch.chdir(tmp_path)
    relative = InfigraphIndexReceipt(
        root=root, executable=Path("infigraph"), receipt=receipt
    )

    assert relative.executable.is_absolute()
    assert relative.executable_identity() == store.executable_identity()
