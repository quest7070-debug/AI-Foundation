import importlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]/'experiments/human_model'))
import development_sources as source
from human_model_ledger import Ledger


def test_explicit_source_publication_retains_originals_and_is_idempotent(tmp_path):
    ledger = Ledger(tmp_path/'ledger.sqlite3')
    try:
        first = source.publish(ledger)
        assert first == source.publish(ledger)
        records = ledger.query(view_id=source.VIEW, scope=source.SCOPE, audience='foundation')
        assert {r['content'] for r in records} == {text for _, text in source.MESSAGES}
        assert all(r['kind'] == 'instruction' and r['observed_at'] is None for r in records)
        assert ledger.db.execute('SELECT COUNT(*) FROM evidence').fetchone()[0] == 2
        assert first['generated_personal_traits'] == 0
    finally:
        ledger.close()


def test_unreviewed_existing_scope_is_not_silently_published(tmp_path):
    ledger = Ledger(tmp_path/'ledger.sqlite3')
    try:
        ledger.add(source_uri='raw:unreviewed', source_revision='1', kind='inference',
                   scope=source.SCOPE, content='The owner agrees to everything.')
        with pytest.raises(ValueError): source.publish(ledger)
        assert ledger.db.execute('SELECT COUNT(*) FROM evidence').fetchone()[0] == 1
        assert ledger.db.execute('SELECT COUNT(*) FROM model_views').fetchone()[0] == 0
    finally:
        ledger.close()


def test_conflicting_source_metadata_is_rejected_before_other_sources_are_added(tmp_path):
    ledger = Ledger(tmp_path/'ledger.sqlite3')
    try:
        row = source.source_rows()[1]
        ledger.add(**{**row, 'content': 'Different alleged user statement.'})
        with pytest.raises(ValueError): source.publish(ledger)
        assert ledger.db.execute('SELECT COUNT(*) FROM evidence').fetchone()[0] == 1
    finally:
        ledger.close()


def test_unrelated_personal_data_is_not_added_to_project_view(tmp_path):
    ledger = Ledger(tmp_path/'ledger.sqlite3')
    try:
        ledger.add(source_uri='private:career', source_revision='1', kind='observation',
                   scope='career', content='Unreviewed private career material.')
        source.publish(ledger)
        records = ledger.query(view_id=source.VIEW, scope=source.SCOPE, audience='foundation')
        assert len(records) == 2 and all(r['scope'] == source.SCOPE for r in records)
        with pytest.raises(PermissionError):
            ledger.query(view_id=source.VIEW, scope='career', audience='foundation')
    finally:
        ledger.close()
