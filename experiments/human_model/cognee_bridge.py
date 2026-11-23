"""Host-selected, isolated Cognee worker; never import Cognee into Foundation."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import signal
import re

if __package__:
    from .cognee_memory import ADAPTER_REVISION, VERSION, digest, validate_snapshot, inference_route
    from .foundation_readonly import read_view_snapshot
    from .storage_location import validate_external_root
    from .cognee_software_runtime import runtime_python
else:
    from cognee_memory import ADAPTER_REVISION, VERSION, digest, validate_snapshot, inference_route
    from foundation_readonly import read_view_snapshot
    from storage_location import validate_external_root
    from cognee_software_runtime import runtime_python


def invoke_worker(python, workspace, model, operation, payload, *, repository_root, allow_runtime_ipc=False):
    if sys.platform != 'darwin': raise RuntimeError('OS confined M1 worker required')
    workspace = Path(workspace).resolve(strict=True)
    temporary = workspace/'tmp'; temporary.mkdir(mode=0o700, exist_ok=True)
    profile = workspace/'local-only.sb'
    _, port = inference_route(model)
    profile.write_text('(version 1)\n(allow default)\n(deny network*)\n'
        '(allow network-outbound (remote ip "localhost:'+str(port)+'"))\n'
        '(deny file-write*)\n(allow file-write* (subpath '+json.dumps(str(workspace))+'))\n'
        '(allow file-write* (literal "/dev/null"))\n')
    if allow_runtime_ipc:
        profile.write_text(profile.read_text() + '\n(allow system-socket (socket-domain AF_UNIX))\n'
            '(allow network-bind (local unix-socket))\n'
            '(allow network-outbound (remote unix-socket))\n')
    env = {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin',
           'HOME': str(workspace), 'TMPDIR': str(temporary),
           'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUNBUFFERED': '1'}
    # Preserve only the runner's process-cleanup marker, never provider/proxy
    # credentials, so a cancelled job cannot leave an inference worker behind.
    if os.environ.get('RUNNER_TRACKING_ID'):
        env['RUNNER_TRACKING_ID'] = os.environ['RUNNER_TRACKING_ID']
    process = subprocess.Popen(['/usr/bin/sandbox-exec', '-f', str(profile), str(python), '-B',
                         str(Path(repository_root)/'scripts/cognee_snapshot_worker.py'), operation,
                         '--workspace', str(workspace), '--model', model],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        text=True, cwd=workspace, env=env, start_new_session=True)
    try:
        output, startup_error = process.communicate(json.dumps(payload), timeout=240)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise RuntimeError('COGNEE_WORKER_TIMEOUT') from None
    if process.returncode or len(output.encode()) > 60000:
        error = RuntimeError('Cognee worker failed')
        error.worker_exit_code = process.returncode
        (workspace/'worker-startup-private.log').write_text(startup_error)
        if not output.strip():
            # No worker JSON means failure before source processing. Only OS /
            # interpreter startup diagnostics qualify for public redacted output.
            lines = [line for line in startup_error.splitlines()
                     if line.startswith(('sandbox-exec:', 'dyld[', 'dyld:', 'Python '))][:3]
            summary = ' | '.join(lines)
            summary = re.sub(r'https?://\S+', '<url>', summary)
            summary = re.sub(r'/(?:Users|Volumes|private|var|tmp)/[^\s`]+', '<path>', summary)
            if summary: error.worker_startup_summary = summary[:600]
        try:
            kind = json.loads(output).get('error_type', '')
            if re.fullmatch('[A-Za-z_]{1,60}', kind): error.worker_error_type = kind
        except (ValueError, AttributeError, TypeError): pass
        raise error
    return json.loads(output)


def child_directory(parent, name):
    path = parent/name
    if path.is_symlink(): raise PermissionError('symlinked Cognee directory')
    path.mkdir(mode=0o700, exist_ok=True)
    if not path.is_dir(): raise PermissionError('invalid Cognee directory')
    return path


class CogneeSearch:
    def __init__(self, root, model, repository_root, *, runtime_root=None):
        self.root = root; self.model = model; self.repository_root = repository_root
        self.runtime_root = root if runtime_root is None else runtime_root

    def __call__(self, snapshot, query):
        snapshot_hash = validate_snapshot(snapshot)
        cache_hash = digest({'snapshot': snapshot_hash, 'engine': VERSION,
                             'adapter_revision': ADAPTER_REVISION, 'model': self.model})
        # The graph is a source-derived cache, partitioned by full source identity,
        # scope, privacy and revision. Failed builds remain unreferenced.
        root = validate_external_root(self.root)
        runtime = validate_external_root(self.runtime_root)
        parent = child_directory(child_directory(root, 'indexes'), 'cognee')
        lock = parent/'build.lock'
        if lock.is_symlink(): raise PermissionError('symlinked Cognee lock')
        with lock.open('a') as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            directory = parent/cache_hash
            if directory.is_symlink(): raise PermissionError('symlinked Cognee snapshot')
            if not directory.exists():
                staging = Path(tempfile.mkdtemp(prefix='building-', dir=parent))
                invoke_worker(runtime_python(runtime), staging,
                              self.model, 'build', {'snapshot': snapshot},
                              repository_root=self.repository_root)
                # Cognee stores absolute database paths. The completed physical
                # workspace remains at its original path; publish a host pointer.
                directory.mkdir(mode=0o700)
                (directory/'workspace.json').write_text(json.dumps({'workspace': staging.name}))
            pointer = json.loads((directory/'workspace.json').read_text())['workspace']
            if not isinstance(pointer, str) or not pointer.startswith('building-') or Path(pointer).name != pointer:
                raise ValueError('invalid Cognee workspace receipt')
            workspace = parent/pointer
            if workspace.is_symlink(): raise PermissionError('symlinked Cognee workspace')
            result = invoke_worker(runtime_python(runtime), workspace,
                                   self.model, 'search', {'snapshot': snapshot, 'query': query},
                                   repository_root=self.repository_root)
        # Revalidate after inference: a stale/changed view must not be returned.
        fresh = read_view_snapshot(root, view_id=snapshot['view_id'], scope=snapshot['scope'],
                                   max_privacy=snapshot['_privacy_ceiling'],
                                   max_records=32, max_bytes=32768)
        # Host-only ceiling is part of cache identity, not a source-owned field.
        fresh['_privacy_ceiling'] = snapshot['_privacy_ceiling']
        if digest(fresh) != snapshot_hash: raise ValueError('HumanModel changed during search')
        return result


def configured_search(root, *, repository_root):
    config = Path(root)/'tools/cognee-1.6.5/enabled.json'
    if not config.exists(): return None
    validate_external_root(root)
    for path in (Path(root)/'tools', config.parent, config):
        if path.is_symlink(): raise PermissionError('symlinked Cognee configuration')
    if config.stat().st_size > 1024: raise ValueError('oversized Cognee configuration')
    row = json.loads(config.read_text())
    if (set(row) != {'version', 'enabled', 'model'} or type(row['version']) is not int
            or row['version'] != 1 or row['enabled'] is not True):
        raise ValueError('invalid explicit Cognee configuration')
    return CogneeSearch(root, row['model'], repository_root)
