import sys
from pathlib import Path
import pytest

ROOT=Path(__file__).parents[1]
sys.path.insert(0,str(ROOT/'experiments/human_model'))
import project_reference_sources as project
import development_sources as private
from human_model_ledger import Ledger


def test_project_view_contains_only_pinned_documents_and_preserves_private_originals(tmp_path):
    ledger=Ledger(tmp_path/'source.sqlite3')
    try:
        private.publish(ledger)
        old=ledger.db.execute('SELECT id,content,privacy FROM evidence ORDER BY id').fetchall()
        result=project.publish(ledger,ROOT)
        assert result==project.publish(ledger,ROOT)
        for identifier,content,privacy in old:
            assert ledger.db.execute('SELECT content,privacy FROM evidence WHERE id=?',(identifier,)).fetchone()==(content,privacy)
        found=ledger.query(view_id=project.VIEW,scope=project.SCOPE,audience='foundation',max_privacy='shareable')
        assert len(found)==2 and all(r['privacy']=='shareable' and r['kind']=='observation' for r in found)
        assert all(r['source_uri'].startswith('https://github.com/') for r in found)
        with pytest.raises(PermissionError):
            ledger.query(view_id=project.VIEW,scope=private.SCOPE,audience='foundation')
    finally:ledger.close()


def test_changed_project_document_is_not_published_as_the_pinned_source(tmp_path):
    for relative,_,_,_ in project.DOCUMENTS:
        p=tmp_path/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('Different document.')
    ledger=Ledger(tmp_path/'source.sqlite3')
    try:
        with pytest.raises(ValueError):project.publish(ledger,tmp_path)
        assert ledger.db.execute('SELECT COUNT(*) FROM evidence').fetchone()[0]==0
    finally:ledger.close()
