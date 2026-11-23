import base64
import hashlib
import importlib.util
import io
from pathlib import Path
import zipfile
import pytest

spec = importlib.util.spec_from_file_location('document_probe', Path(__file__).parents[1] / 'scripts/m1_librechat_document_probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def test_probe_requires_unique_published_librechat_container():
    selected = {'ID': 'a' * 12, 'Image': 'ai-foundation/librechat:v0.8.8', 'Ports': '127.0.0.1:3080->3080/tcp'}
    rag = {'ID': 'b' * 12, 'Image': 'librechat-rag-api:latest', 'Ports': '8000/tcp'}
    assert probe.select_container([rag, selected]) == 'a' * 12
    for rows in ([], [selected, selected], [{**selected, 'Ports': '127.0.0.1:13080->3080/tcp'}], [{**selected, 'ID': 'not-an-id'}]):
        with pytest.raises(probe.ProbeBlocked): probe.select_container(rows)


def test_synthetic_fixtures_are_small_deterministic_documents():
    samples = probe.fixtures()
    assert samples == probe.fixtures()
    assert [x['name'] for x in samples] == ['probe.pdf', 'probe.docx', 'probe.xlsx']
    for sample in samples:
        data = base64.b64decode(sample['data'])
        assert len(data) < 4096
        if sample['name'].endswith('.pdf'):
            assert data.startswith(b'%PDF-1.4') and b'startxref' in data
        else:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                assert archive.testzip() is None


def test_synthetic_parser_results_use_real_foundation_handoff_and_deny_foreign_owner():
    rows = [{'name': row['name'], 'mime': row['mime'], 'text': row['expected'] + '\n',
             'sha256': hashlib.sha256((row['expected'] + '\n').encode()).hexdigest()} for row in probe.fixtures()]
    report = probe.verify_handoff({'results': rows})
    assert len(report) == 3
    assert all(row['foundation_files'] and row['foreign_owner_denied'] for row in report)
    rows[0]['text'] = 'unverified replacement'
    with pytest.raises(probe.ProbeBlocked): probe.verify_handoff({'results': rows})
