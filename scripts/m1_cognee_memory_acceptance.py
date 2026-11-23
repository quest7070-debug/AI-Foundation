"""Install isolated Cognee software, never model weights; test private local path.

No Operator/Native restart, binding, Ledger mutation, Raw mutation or cloud call.
Only derived draft output is written on the existing external HumanModel volume.
"""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import io
import tarfile
import re
import importlib
import time
from urllib.request import urlopen

from m1_human_model_activation_readiness import existing_ledger_roots

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
sys.path.insert(0, str(ROOT/'experiments/human_model'))
from cognee_bridge import invoke_worker, CogneeSearch
from cognee_software_runtime import prepare_runtime


def private_dir(path):
    if path.is_symlink(): raise PermissionError('symlinked workspace')
    path.mkdir(mode=0o700, exist_ok=True)
    if not path.is_dir(): raise PermissionError('invalid workspace')
    return path


def synthetic_diagnostic(root):
    base = root/'evaluation/cognee'
    # acceptance-* workspaces contain only the fixed synthetic fixture. Actual
    # Raw drafts use private-raw-* and are never read by this diagnostic.
    candidates = sorted((p for p in base.glob('acceptance-*') if p.is_dir() and not p.is_symlink()),
                        key=lambda p:p.stat().st_mtime, reverse=True)
    report = {'status':'DIAGNOSTIC_ONLY','real_raw_read':False,'model_calls':0}
    if candidates:
        workspace = candidates[0]
        log = workspace/'worker-private.log'
        if log.is_file() and not log.is_symlink():
            whole = log.read_text(errors='replace')
            marker = whole.rfind('Timeout (')
            text = whole[marker:marker+8000] if marker >= 0 else whole[-5000:]
            text = re.sub(r'\x1b\[[0-9;]*m', '', text)
            text = re.sub(r'https?://\S+', '<url>', text)
            text = re.sub(r'/(?:Users|Volumes|private|var|tmp)/[^\s`]+', '<path>', text)
            text = re.sub(r'qwen3\.5:[A-Za-z0-9_.-]+','<installed-model>',text)
            report['synthetic_worker_tail'] = text
        report['synthetic_archive_created'] = (workspace/'archive').exists()
        report['synthetic_receipt_created'] = (workspace/'receipt.json').exists()
    # Classify only fixed adapter error messages from the Raw worker log.
    # Never return any line, source text, model response, path or identifier.
    private = sorted((p for p in base.glob('private-raw-*') if p.is_dir() and not p.is_symlink()),
                     key=lambda p:p.stat().st_mtime, reverse=True)
    known = {'interpretation must quote the exact source':'EXACT_QUOTE_MISSING',
             'invalid source identity or content hash':'SOURCE_IDENTITY_OR_HASH',
             'snapshot too large; explicit source partition required':'SOURCE_TOO_LARGE',
             'invalid interpretation shape':'INTERPRETATION_SCHEMA',
             'bounded interpretation fields required':'INTERPRETATION_FIELD_BOUNDS',
             'bounded interpretation required':'INTERPRETATION_COUNT'}
    if private:
        log = private[0]/'worker-private.log'
        if log.is_file() and not log.is_symlink():
            tail = log.read_text(errors='replace')[-10000:]
            report['raw_failure_code'] = next((code for message,code in known.items()
                                              if '\nValueError: '+message in tail), 'UNCLASSIFIED')
    print(json.dumps(report,sort_keys=True));return 0


def pinned_uv(install):
    path = install/'uv'
    if path.is_symlink(): raise PermissionError('symlinked installer')
    if path.is_file(): return path
    url = 'https://github.com/astral-sh/uv/releases/download/0.8.22/uv-aarch64-apple-darwin.tar.gz'
    with urlopen(url, timeout=90) as response: archive = response.read(50000000)
    if hashlib.sha256(archive).hexdigest() != '3f61099e261e449527141dbf125629fab33ad696468c8c90cebbac40185a306c':
        raise ValueError('pinned installer checksum mismatch')
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as tar:
        member = tar.getmember('uv-aarch64-apple-darwin/uv')
        if not member.isfile(): raise ValueError('installer must be regular file')
        with path.open('xb') as out: out.write(tar.extractfile(member).read())
    path.chmod(0o700)
    return path


def run_worker(python, workspace, model, operation, payload):
    return invoke_worker(python, workspace, model, operation, payload, repository_root=ROOT)


def source_row(identifier, text, revision='1'):
    return {'id': identifier, 'source_uri': 'synthetic://memory/'+identifier,
            'source_revision': revision, 'privacy': 'private', 'scope': 'work',
            'kind': 'instruction', 'content': text,
            'content_sha256': hashlib.sha256(text.encode()).hexdigest()}


def read_one_raw(root):
    """Existing source format from pinned #81; no schema creation or mutation."""
    path = root/'sources/raw_inbox.sqlite3'
    if not path.is_file(): return None
    for part in (root/'sources', *(Path(str(path)+suffix) for suffix in ('', '-wal', '-shm', '-journal'))):
        if part.is_symlink(): raise PermissionError('symlinked Raw source')
    db = sqlite3.connect(path.as_uri()+'?mode=ro', uri=True)
    try:
        db.execute('PRAGMA query_only=ON')
        row = db.execute('SELECT id,source_uri,source_revision,privacy,kind,content_sha256,content,observed_at,captured_at '
                         'FROM raw_items WHERE length(CAST(content AS BLOB)) BETWEEN 1 AND 8192 '
                         'ORDER BY captured_at,id LIMIT 1').fetchone()
        if row is None: return None
        return dict(zip(('id','source_uri','source_revision','privacy','kind','content_sha256','content','observed_at','captured_at'),row))
    finally: db.close()


def source_context_acceptance(base, root, model):
    """Real approved-source adapter + Guard + Cognee, isolated synthetic ledger."""
    from ai_foundation.human_model_context import HumanModelBinding, HumanModelContext, _source_reader
    from ai_foundation.core import GuardState
    from ai_foundation.guard import GuardCore
    reader = _source_reader(ROOT)
    Ledger = importlib.import_module(reader.__module__.rsplit('.',1)[0]+'.human_model_ledger').Ledger
    source = Path(tempfile.mkdtemp(prefix='synthetic-source-',dir=base))
    (source/'ledger').mkdir(mode=0o700)
    ledger = Ledger(source/'ledger/human_model.sqlite3')
    try:
        original = ledger.add(source_uri='synthetic://priority',source_revision='1',kind='instruction',
                              scope='work',privacy='private',
                              content='この開発では、負荷テストより未実装の機能を優先する。')
        ledger.define_view(view_id='synthetic-work',purpose='synthetic source integration only',
                           audience='foundation',allowed_scopes=['work'])
        ledger.rebuild_view(view_id='synthetic-work')
        context = HumanModelContext(HumanModelBinding('synthetic-owner',str(source),
                                    'synthetic-work',('work',),'private'),reader,
                                    guard=GuardCore(GuardState()),run_id='synthetic-cognee',
                                    search_backend=CogneeSearch(source,model,ROOT,runtime_root=root))
        result = json.loads(context.search('synthetic-owner','work','未実装の機能'))
        if result.get('status') != 'AVAILABLE' or result['records'][0]['id'] != original:
            raise RuntimeError('APPROVED_SOURCE_COGNEE_READ_FAILED')
        corrected = ledger.add(source_uri='synthetic://priority',source_revision='2',kind='instruction',
                               scope='work',privacy='private',supersedes=original,
                               content='この開発では、機能追加より先にデータ復旧を優先する。')
        if json.loads(context.search('synthetic-owner','work','優先'))['status'] != 'UNAVAILABLE':
            raise RuntimeError('STALE_SOURCE_NOT_REJECTED')
        ledger.rebuild_view(view_id='synthetic-work')
        result = json.loads(context.search('synthetic-owner','work','データ復旧'))
        if (result.get('status') != 'AVAILABLE' or result['view_revision'] != 2
                or [r['id'] for r in result['records']] != [corrected]):
            raise RuntimeError('CORRECTED_SOURCE_COGNEE_READ_FAILED')
        return {'approved_source_guard_cognee_readback':True,
                'stale_view_rejected':True,'corrected_source_current':True}
    finally: ledger.close()


def main():
    report = {'status': 'BLOCKED', 'phase': 'external_root', 'new_model_downloads': 0,
              'paid_api_calls': 0, 'production_ledger_mutations': 0, 'raw_mutations': 0,
              'native_dispatches': 0, 'private_content_logged': False}
    try:
        if sys.platform != 'darwin': raise RuntimeError('M1_REQUIRED')
        os.umask(0o077)
        roots = existing_ledger_roots()
        if len(roots) != 1: raise RuntimeError('EXTERNAL_ROOT_NOT_UNIQUE')
        root = roots[0]
        if '--diagnose-only' in sys.argv: return synthetic_diagnostic(root)
        tools = private_dir(root/'tools'); install = private_dir(tools/'cognee-1.6.5')
        python = install/'venv/bin/python'
        report['phase'] = 'software_install'
        old_log = install/'install-private.log'
        if old_log.is_file():
            lines = old_log.read_text(errors='replace')[-20000:].splitlines()
            report['previous_install_packages'] = [m.group(1) for line in lines
                if (m := re.match(r'(?:Collecting|Downloading|Using cached) ([A-Za-z0-9_.-]+)', line))][-5:]
        with (install/'install-private.log').open('a') as log:
            if not python.is_file():
                subprocess.run([sys.executable, '-m', 'venv', str(install/'venv')],
                               stdout=log, stderr=log, check=True, timeout=60)
            # No extras, CLI model pulls or runtime cognition during installation.
            uv = pinned_uv(install)
            # uv's cache uses filesystem operations unavailable on some external
            # volumes. Keep persistent software/data outside, use the existing
            # runner's disposable download cache and copy installed files.
            with tempfile.TemporaryDirectory(prefix='cognee-install-', dir=os.environ.get('RUNNER_TEMP')) as cache:
                completed = subprocess.run([str(uv), '--cache-dir', cache, 'pip', 'install',
                            '--link-mode', 'copy', '--python', str(python),
                            '--index-url', 'https://pypi.org/simple', 'cognee==1.6.5'],
                           stdout=log, stderr=log, timeout=900)
            log.flush()
            report['installation_method'] = 'uv_copy'
            if completed.returncode:
                previous = (install/'install-private.log').read_text(errors='replace')[-6000:]
                if 'Operation not supported (os error 45)' not in previous:
                    completed.check_returncode()
                # pip's normal copy path also works when the target venv cannot
                # support uv's locking/link operations. Reuse its prior download
                # cache; no new models or runtime environment are introduced.
                report['installation_method'] = 'pip_copy_unsupported_filesystem'
                subprocess.run([str(python), '-m', 'pip', '--isolated', 'install', '--prefer-binary',
                                '--index-url', 'https://pypi.org/simple', 'cognee==1.6.5'],
                               stdout=log, stderr=log, check=True, timeout=900)
        metadata = subprocess.run([str(python), '-m', 'pip', 'freeze'],capture_output=True,text=True,check=True,timeout=30)
        (install/'installed-requirements.txt').write_text(metadata.stdout)
        report['phase'] = 'internal_software_runtime'
        python = prepare_runtime(install)
        report['software_runtime_internal'] = True
        print(json.dumps({'checkpoint': 'isolated_cognee_software_installed', 'new_model_downloads': 0}), flush=True)
        report['phase'] = 'existing_local_model'
        from ai_foundation.shared_ollama9b_adapter import SharedOllama9BDiscovery, MODEL
        rows = SharedOllama9BDiscovery()()
        model = (MODEL if len(rows) == 1
                 and rows[0].binding == 'local:ollama-shared9b:general'
                 and rows[0].model == MODEL and rows[0].health == 'ONLINE'
                 else None)
        # Canonical and synthetic Cognee paths share the same single admitted
        # M1 9B; legacy llama-swap and 2B/4B are never selected.
        if '--canonical-input' in sys.argv:
            report['canonical_input_pinned_9b_selected'] = model is not None
        if model is None: raise RuntimeError('EXISTING_MODEL_UNAVAILABLE')
        evaluation = private_dir(root/'evaluation'); base = private_dir(evaluation/'cognee')
        workspace = Path(tempfile.mkdtemp(prefix='acceptance-', dir=base))
        report['phase'] = 'synthetic_extract_graph_search'
        snapshot = {'view_id': 'synthetic', 'scope': 'work', 'view_revision': 1,
                    'records': [source_row('feature-priority', 'この開発では、負荷テストよりも未実装の機能を優先する。')]}
        started = time.monotonic()
        built = run_worker(python, workspace, model, 'build', {'snapshot': snapshot})
        report['synthetic_build_seconds'] = round(time.monotonic()-started,2)
        if built['interpretation_count'] < 1: raise RuntimeError('NO_GROUNDED_INTERPRETATION')
        started = time.monotonic()
        found = run_worker(python, workspace, model, 'search', {'snapshot': snapshot, 'query': '未実装の機能'})
        report['synthetic_search_seconds'] = round(time.monotonic()-started,2)
        if [r['id'] for r in found['records']] != ['feature-priority'] or not found['interpretations']:
            raise RuntimeError('SOURCE_GRAPH_READBACK_FAILED')
        report['synthetic_source_graph_readback'] = True
        report['synthetic_interpretations'] = built['interpretation_count']
        if '--smoke-only' in sys.argv:
            report.update(status='SYNTHETIC_PATH_SUCCESS', phase='complete',
                          private_raw_processed=False, canonical_runtime_activated=False)
            print(json.dumps(report,sort_keys=True)); return 0
        report['phase'] = 'approved_source_context_and_correction'
        started = time.monotonic()
        report.update(source_context_acceptance(base, root, model))
        report['approved_source_correction_seconds'] = round(time.monotonic()-started,2)
        report['phase'] = 'private_raw_draft'
        raw = read_one_raw(root)
        report['real_raw_available_within_bound'] = raw is not None
        if raw:
            raw_snapshot = {'source_kind': 'uncurated_raw', 'records': [raw]}
            raw_workspace = Path(tempfile.mkdtemp(prefix='private-raw-', dir=base))
            (raw_workspace/'source-snapshot.json').write_text(json.dumps(raw_snapshot,ensure_ascii=False))
            started = time.monotonic()
            built = run_worker(python, raw_workspace, model, 'build', {'snapshot': raw_snapshot})
            report['real_raw_build_seconds'] = round(time.monotonic()-started,2)
            report['real_raw_graph_records'] = built['record_count']
            report['real_raw_draft_interpretations'] = built['interpretation_count']
            # Retained locally, not uploaded. These are still uncurated Raw drafts.
            started = time.monotonic()
            found = run_worker(python, raw_workspace, model, 'search',
                               {'snapshot':raw_snapshot,'query':raw['content'].strip()[:64]})
            if [row['id'] for row in found['records']] != [raw['id']]:
                raise RuntimeError('PRIVATE_RAW_GRAPH_READBACK_FAILED')
            report['real_raw_search_seconds'] = round(time.monotonic()-started,2)
            report['real_raw_graph_readback'] = True
            report['raw_search_probe_uses_source_text'] = True
            report['real_raw_is_approved_personal_evidence'] = False
        # Existing 2B/4B models validate the transport only. Production input
        # remains the separately configured 9B route; acceptance grants no activation.
        report['host_search_adapter_configured'] = False
        report['validation_model_test_only'] = True
        report.update(status='SUCCESS', phase='complete', semantic_vector_search=False,
                      canonical_runtime_activated=False)
        print(json.dumps(report, sort_keys=True)); return 0
    except Exception as exc:
        report['error_type'] = type(exc).__name__
        if 'workspace' in locals():
            progress = workspace/'worker-phases.jsonl'
            if progress.is_file() and not progress.is_symlink():
                rows = [json.loads(line) for line in progress.read_text().splitlines()[-40:]]
                report['synthetic_worker_phases'] = [r for r in rows
                    if set(r) == {'phase','seconds'} and isinstance(r['seconds'],(int,float))
                    and re.fullmatch(r'(worker|build|extract|search)\.[a-z.]{1,50}',str(r['phase']))]
        if hasattr(exc, 'worker_error_type'): report['worker_error_type'] = exc.worker_error_type
        if hasattr(exc, 'worker_exit_code'): report['worker_exit_code'] = exc.worker_exit_code
        if hasattr(exc, 'worker_startup_summary'): report['worker_startup_summary'] = exc.worker_startup_summary
        if isinstance(exc, RuntimeError) and re.fullmatch('[A-Z_]{1,80}', str(exc)):
            report['reason_code'] = str(exc)
        if report['phase'] == 'software_install' and 'install' in locals():
            lines = (install/'install-private.log').read_text(errors='replace')[-12000:].splitlines()
            errors = [line for line in lines if re.search(r'(?i)error:|caused by:|╰─▶|├─▶', line)][-8:]
            def public_package_error(line):
                line = re.sub(r'https?://\S+', '<url>', line)
                line = re.sub(r'/(?:Users|Volumes|private|var|tmp)/[^\s`]+', '<path>', line)
                return line[:300]
            report['package_install_errors'] = [public_package_error(line) for line in errors]
        print(json.dumps(report, sort_keys=True)); return 2


if __name__ == '__main__': raise SystemExit(main())
