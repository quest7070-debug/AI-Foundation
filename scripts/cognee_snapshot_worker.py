"""Private subprocess worker. No stdout except one bounded result JSON.

Parent must enforce OS isolation and provide a preinstalled local model. Cognee
configuration is process-local; this file never runs inside the Operator process.
"""
import argparse
import asyncio
import contextlib
import json
import os
from pathlib import Path
import sys
import traceback
import faulthandler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'experiments/human_model'))
import cognee_memory as memory


async def run(args, payload):
    workspace = args.workspace.resolve(strict=True)
    os.environ['HUMAN_MODEL_WORKER_PHASE_FILE'] = str(workspace/'worker-phases.jsonl')
    memory.phase('worker.configure.start')
    memory.configure(workspace, args.model)
    memory.phase('worker.configure.complete')
    _, inference_port = memory.inference_route(args.model)
    # Defense in depth. Host Seatbelt remains the native-library network boundary.
    def audit(event, values):
        if event == 'socket.connect' and isinstance(values[1], tuple):
            if values[1][0] != '127.0.0.1' or values[1][1] != inference_port:
                raise PermissionError('only existing local inference is allowed')
    sys.addaudithook(audit)
    if args.operation == 'async-probe':
        import socket, time
        started = time.monotonic(); pair_ok = False; pair_errno = None
        try:
            left, right = socket.socketpair()
            try:
                left.setblocking(False); right.setblocking(False)
                left.send(b'x'); pair_ok = right.recv(1) == b'x'
            finally: left.close(); right.close()
        except OSError as exc: pair_errno = exc.errno
        thread_ok = False
        try: thread_ok = await asyncio.wait_for(asyncio.to_thread(lambda: True), 3)
        except TimeoutError: pass
        return {'socketpair_ok':pair_ok,'socketpair_errno':pair_errno,
                'thread_loop_ok':thread_ok,'seconds':round(time.monotonic()-started,3)}
    if args.operation == 'build':
        return await memory.build(payload['snapshot'], workspace)
    return await memory.search(payload['snapshot'], workspace, payload['query'])


def main():
    p = argparse.ArgumentParser()
    p.add_argument('operation', choices=['build', 'search', 'async-probe'])
    p.add_argument('--workspace', type=Path, required=True)
    p.add_argument('--model', required=True)
    args = p.parse_args()
    os.umask(0o077)
    # Error output can include model/source content; retain it only in this
    # private workspace, never relay exception messages to CI or chat.
    with (args.workspace/'worker-private.log').open('a') as log:
        try:
            raw = sys.stdin.buffer.read(40000)
            if len(raw) >= 40000: raise ValueError('worker input too large')
            with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                faulthandler.dump_traceback_later(90, file=log)
                try:
                    result = asyncio.run(run(args, json.loads(raw)))
                finally:
                    faulthandler.cancel_dump_traceback_later()
            output = json.dumps(result, ensure_ascii=False)
            if len(output.encode()) > 60000: raise ValueError('worker output too large')
            print(output); return 0
        except Exception as exc:
            traceback.print_exc(file=log)
            print(json.dumps({'status': 'BLOCKED', 'error_type': type(exc).__name__})); return 2


if __name__ == '__main__': raise SystemExit(main())
