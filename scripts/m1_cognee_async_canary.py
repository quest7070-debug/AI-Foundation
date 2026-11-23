"""Read-only data handling: compare local asyncio IPC in two OS profiles.
No model calls, Raw reads, source mutations, service restart or Native effects.
"""
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'experiments/human_model'))
from cognee_bridge import invoke_worker
from cognee_software_runtime import runtime_python
from m1_human_model_activation_readiness import existing_ledger_roots

def main():
    if sys.platform != 'darwin': raise RuntimeError('M1_REQUIRED')
    os.umask(0o077)
    roots = existing_ledger_roots()
    if len(roots) != 1: raise RuntimeError('EXTERNAL_ROOT_NOT_UNIQUE')
    root = roots[0]; base = root/'evaluation/cognee'
    result = {'model_calls':0,'raw_reads':0,'production_mutations':0}
    for name, allowed in [('baseline',False),('runtime_ipc',True)]:
        workspace = Path(tempfile.mkdtemp(prefix='async-probe-',dir=base))
        try:
            result[name] = invoke_worker(runtime_python(root),workspace,'unused-local',
                'async-probe',{},repository_root=ROOT,allow_runtime_ipc=allowed)
        except Exception as exc:
            result[name] = {'error_type':type(exc).__name__,
                            'worker_error_type':getattr(exc,'worker_error_type',None),
                            'startup':getattr(exc,'worker_startup_summary',None)}
    fast = result.get('runtime_ipc',{})
    result['runtime_ipc_working'] = (fast.get('socketpair_ok') is True and
        fast.get('thread_loop_ok') is True and fast.get('seconds',999)<2)
    result['status'] = 'IPC_PROBE_COMPLETE'
    print(json.dumps(result,sort_keys=True))
    return 0 if result['runtime_ipc_working'] else 2

if __name__ == '__main__':raise SystemExit(main())
