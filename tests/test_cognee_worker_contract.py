"""Optional actual-OSS protocol regression; never installs software or models.

COGNEE_TEST_PYTHON must identify an existing isolated Cognee 1.6.5 interpreter.
The fixture port must be unused; this never replaces a real Ollama service.
"""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
from threading import Thread
import pytest

PYTHON = os.environ.get('COGNEE_TEST_PYTHON')


@pytest.mark.skipif(not PYTHON, reason='requires explicitly selected existing Cognee interpreter')
@pytest.mark.parametrize('port,model,valid_draft', [
    (11434, 'fixture', True), (9292, 'local-general', True),
    (11434, 'fixture', False)])
def test_actual_cognee_reopens_its_dataset_in_a_new_worker(tmp_path, port, model, valid_draft):
    calls = []
    class Endpoint(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            calls.append((self.path, request['model'], request.get('reasoning_effort')))
            facts = {'facts': [{'subject': 'この開発', 'relation': '優先する',
                               'object': '未実装の機能', 'source_span_id': 0}]}
            if not valid_draft:
                facts['facts'][0]['source_span_id'] = True
            result = {'id': 'fixture', 'object': 'chat.completion', 'created': 1,
                      'model': 'fixture', 'choices': [{'index': 0, 'message': {
                          'role': 'assistant', 'content': json.dumps(facts,ensure_ascii=False)},
                          'finish_reason': 'stop'}],
                      'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}}
            data = json.dumps(result).encode()
            self.send_response(200); self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data))); self.end_headers()
            self.wfile.write(data)
    try: server = ThreadingHTTPServer(('127.0.0.1', port), Endpoint)
    except OSError: pytest.skip('existing local inference port is occupied')
    Thread(target=server.serve_forever, daemon=True).start()
    content = 'この開発では、負荷テストより未実装の機能を優先する。'
    snapshot = {'view_revision': 1, 'records': [{'id': 'fixture', 'content': content,
        'content_sha256': hashlib.sha256(content.encode()).hexdigest(),
        'source_uri': 'synthetic://fixture', 'source_revision': '1', 'privacy': 'private'}]}
    worker = Path(__file__).parents[1]/'scripts/cognee_snapshot_worker.py'
    def invoke(operation, source):
        cp = subprocess.run([PYTHON, '-B', str(worker), operation, '--workspace', str(tmp_path),
                             '--model', model], input=json.dumps({'snapshot': source, 'query': '未実装'}),
                            text=True, capture_output=True, cwd=tmp_path, timeout=120,
                            env={'PATH': os.environ['PATH'], 'HOME': str(tmp_path), 'NO_PROXY': '127.0.0.1'})
        return cp.returncode, json.loads(cp.stdout)
    try:
        code, built = invoke('build', snapshot)
        assert code == 0 and built['interpretation_count'] == int(valid_draft)
        assert built['rejected_interpretation_records'] == int(not valid_draft)
        code, found = invoke('search', snapshot)
        assert code == 0 and found['records'] == snapshot['records']
        if valid_draft:
            assert found['interpretations'][0]['quote'] in content
        else:
            assert found['interpretations'] == []
        assert calls == [('/v1/chat/completions', model, 'none')]
        code, rejected = invoke('search', {**snapshot, 'view_revision': 2})
        assert code == 2 and rejected['error_type'] == 'ValueError'
        assert calls == [('/v1/chat/completions', model, 'none')]
    finally:
        server.shutdown(); server.server_close()
