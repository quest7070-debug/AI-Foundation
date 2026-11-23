"""Delivery order, restart deduplication and host transaction ownership."""
import json
import os
from pathlib import Path
import subprocess
import sys

from ai_foundation.push_dispatch import PushDispatch


class Transport:
    def __init__(self):
        self.calls = []

    def deliver(self, payload):
        self.calls.append(payload)
        return {'sent': 1}


def payload(*subjects):
    return {'notices': [{'level': 4, 'kind': 'work', 'subject': x, 'status': 'FAILED'} for x in subjects]}


def test_recent_low_sort_key_survives_eviction_and_restart(tmp_path):
    state = tmp_path / 'seen.json'
    transport = Transport()
    for subject in ('z-old', 'y-old', 'a-new'):
        PushDispatch(transport, state, max_seen=2).dispatch(payload(subject))
    assert len(json.loads(state.read_text())) == 2
    assert PushDispatch(transport, state, max_seen=2).dispatch(payload('a-new'))['sent_notices'] == 0
    assert len(transport.calls) == 3
    assert PushDispatch(transport, state, max_seen=2).dispatch(payload('z-old'))['sent_notices'] == 1


def test_duplicate_projection_rows_send_once_and_failed_rows_can_retry(tmp_path):
    transport = Transport()
    dispatch = PushDispatch(transport, tmp_path / 'seen.json')
    assert dispatch.dispatch(payload('same', 'same')) == {'sent_notices': 1, 'failed_notices': 0}
    assert len(transport.calls) == 1


def test_legacy_seen_json_list_is_read_without_replaying(tmp_path):
    state = tmp_path / 'seen.json'
    state.write_text(json.dumps(['work:previous:FAILED']))
    transport = Transport()
    assert PushDispatch(transport, state).dispatch(payload('previous'))['sent_notices'] == 0
    assert not transport.calls


def test_send_holds_kernel_lock_against_an_independent_process(tmp_path):
    state = tmp_path / 'seen.json'

    class CheckedTransport(Transport):
        def deliver(self, payload):
            code = '''
import fcntl,os,sys
fd=os.open(sys.argv[1],os.O_RDWR)
try:
 fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
 print('UNLOCKED')
except BlockingIOError:
 print('BLOCKED')
finally:os.close(fd)
'''
            result = subprocess.run([sys.executable, '-c', code, str(state) + '.lock'],
                                    text=True, capture_output=True, timeout=10, check=True)
            assert result.stdout.strip() == 'BLOCKED'
            return super().deliver(payload)

    transport = CheckedTransport()
    assert PushDispatch(transport, state).dispatch(payload('one'))['sent_notices'] == 1
    assert len(transport.calls) == 1
    assert (state.stat().st_mode & 0o777) == 0o600
    assert (Path(str(state) + '.lock').stat().st_mode & 0o777) == 0o600


def test_successful_save_keeps_existing_state_until_atomic_replace(tmp_path, monkeypatch):
    state = tmp_path / 'seen.json'
    state.write_text('[]')
    real_replace = os.replace
    observed = []

    def replace(source, target):
        observed.append(state.read_text())
        return real_replace(source, target)

    monkeypatch.setattr(os, 'replace', replace)
    PushDispatch(Transport(), state).dispatch(payload('one'))
    assert observed == ['[]']
    assert not list(tmp_path.glob('.push-seen-*'))
