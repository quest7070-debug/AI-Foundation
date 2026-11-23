#!/usr/bin/env python3
"""One native KLM host tick, invoked by the existing macOS launchd scheduler."""
import argparse
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import time


def write_report(path, result):
    path = Path(path)
    if path.is_symlink() or path.parent.is_symlink():
        raise PermissionError('PRIVATE_REPORT_PATH_REQUIRED')
    fd, name = tempfile.mkstemp(prefix='.klm-report-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as handle:
            json.dump(result, handle, ensure_ascii=False)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def existing_work_db(foundation, root):
    """Match Foundation's configured data directory, including relative DB names."""
    data_root = Path(foundation.get('data_dir', root))
    if not data_root.is_absolute():
        data_root = Path(root) / data_root
    work_path = Path(foundation['work_db'])
    if not work_path.is_absolute():
        work_path = data_root / work_path
    if not work_path.is_file() or work_path.is_symlink():
        raise ValueError('EXISTING_WORK_DB_REQUIRED')
    return work_path.resolve(strict=True)


def owner_management_readonly_audit():
    """Model-free structural evidence; unavailable owner USB cannot block Drive."""
    try:
        from human_model_ledger_verify import verify
        summary = verify()["human_model_management"]
        if (summary["status"] not in {
                "STRUCTURE_OK_SOURCE_UNVERIFIED", "REVIEW_REQUIRED",
                "STRUCTURE_INVALID", "COVERAGE_INCOMPLETE",
                "INTEGRITY_FAILED", "SCHEMA_UNAVAILABLE", "AUDIT_UNAVAILABLE",
            } or summary.get("execution_authority") is not False):
            raise ValueError("UNTRUSTED_HUMAN_MODEL_AUDIT")
        return summary
    except Exception:
        return {"status": "HUMAN_MODEL_LEDGER_UNAVAILABLE",
                "execution_authority": False}


def run(config):
    from ai_foundation.macos_keychain import MacOSKeychain
    from ai_foundation.klm_drive_auth import ReadonlyGoogleToken
    from ai_foundation.klm_drive_work import read_development_state, IntakeQueue, SourceVerifiedRetryIntents, LegacyRehydrateQueue, IdleKlmWorker
    root = Path(config['foundation_root'])
    worker_root = root / 'local9b-autodev'
    sys.path.extend([str(worker_root), str(worker_root / 'modules')])
    import local9b_issue_bridge as bridge
    import local9b_task_selection as selection
    from ai_foundation.host_compute_lease import HostComputeLease, HostComputeBusy, HostComputeLeaseError
    # No GitHub ready-Issue scan when this tick only syncs Drive or audits.
    # The IdleKlmWorker itself invokes this observation twice on actual
    # model work, including immediately before its claim under the shared lease.
    development = {'observation': 'NOT_EVALUATED'}
    def observe():
        state = read_development_state(worker_root, bridge, selection)
        development.update(state.__dict__)
        development['observation'] = 'OBSERVED'
        return state
    token = ReadonlyGoogleToken(MacOSKeychain())
    # One owner-Keychain existence check, not two identical lookups per tick.
    auth_bound = token.available()
    result = {'observed_at': time.time(), 'development': development,
              'drive_auth': 'BOUND' if auth_bound else 'UNBOUND',
              'production_klm_accepted': False, 'inbox_writes': 0}
    foundation = json.loads((root / 'config.json').read_text())
    work_path = existing_work_db(foundation, root)
    if not auth_bound:
        return {**result, 'status': 'DRIVE_AUTH_REQUIRED'}

    from ai_foundation.durable_work import SQLiteWorkStore
    from ai_foundation.klm_drive_input import DriveState, ReadOnlyDriveAPI
    from ai_foundation.klm_drive_runtime import OwnerDriveHTTP, OwnerInboxHTTP
    from ai_foundation.klm_drive_cycle import NativeDriveCycle, NativeInboxReader
    from ai_foundation.klm_9b_handler import Existing9BKlmHandler
    from ai_foundation.knowledge_lifecycle import ReadonlyReceiptJournal
    from ai_foundation.klm_compute_admission import admit_local_9b
    from ai_foundation.klm_llmperks_source import (
        KlmLlmperksReader, FOLDER_ID as RESEARCH_FOLDER_ID,
        SOURCE_ID as RESEARCH_SOURCE_ID,
    )
    state = DriveState(SQLiteWorkStore(work_path))
    queue = IntakeQueue(state)
    inbox = NativeInboxReader(OwnerInboxHTTP(token))
    drive_transport = OwnerDriveHTTP(token)
    drive_api = ReadOnlyDriveAPI(drive_transport)
    research = (
        KlmLlmperksReader(
            drive_api, drive_transport.read_text_media,
            owner_scope=config['owner_scope'], allowed_roots=config['roots'])
        if RESEARCH_FOLDER_ID in config['roots'] else None
    )
    def read_source(pointer):
        if pointer.get('source_id') == RESEARCH_SOURCE_ID:
            if research is None:
                raise PermissionError('KLM_RESEARCH_ROOT_NOT_BOUND')
            return research.source(pointer)
        return inbox.source(pointer)
    retry_intent = SourceVerifiedRetryIntents(queue).tick(read_source)
    admission = {'state': 'NOT_EVALUATED'}
    def compute_idle():
        # Called only with the shared compute lease; a running CI job or a
        # resident Ollama model alone is not evidence of a busy inference slot.
        accepted, reason = admit_local_9b()
        admission.update(state='AVAILABLE' if accepted else 'DEFER', reason=reason)
        return accepted
    shared_lease = HostComputeLease()
    worker = IdleKlmWorker(queue, observe_dev=observe, lease=shared_lease,
                           compute_idle=compute_idle, busy_types=(HostComputeBusy, HostComputeLeaseError))
    cycle = NativeDriveCycle(
        state, roots=config['roots'], owner_scope=config['owner_scope'],
        drive=drive_api, inbox=inbox, research_reader=research)
    journal = ReadonlyReceiptJournal(work_path)
    handler = Existing9BKlmHandler(journal)
    outcome = cycle.tick(worker=worker, handler=handler, read_source=read_source)
    outcome['retry_intent'] = retry_intent
    if outcome.get('status') == 'CURRENT' and outcome.get('inference') == 'NO_INPUT':
        # At most ONE source-bound legacy review per existing 900-second due tick.
        # Separate Work identity; original VERIFIED receipts and atoms are never
        # overwritten. Same development priority, host lease and pinned 9B.
        legacy = IdleKlmWorker(
            LegacyRehydrateQueue(state), observe_dev=observe, lease=shared_lease,
            compute_idle=compute_idle, busy_types=(HostComputeBusy, HostComputeLeaseError))
        outcome['legacy_inference'] = legacy.tick(
            read_source=inbox.source, handler=handler)
    outcome['audits'] = journal.audit_due(state.work)
    outcome['human_model_management'] = owner_management_readonly_audit()
    # A fixed, non-private gate reason distinguishes resource pressure from
    # no work. Never publish model text, process identities or owner sources.
    outcome['compute_admission'] = admission
    return {**result, **outcome}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--config', required=True, type=Path)
    p.add_argument('--report', required=True, type=Path)
    args = p.parse_args()
    try:
        info = args.config.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise PermissionError('PRIVATE_HOST_CONFIG_REQUIRED')
        if info.st_size > 65536:
            raise ValueError('HOST_CONFIG_TOO_LARGE')
        config = json.loads(args.config.read_text())
        if set(config) != {'foundation_root', 'roots', 'owner_scope'}:
            raise ValueError('EXPLICIT_HOST_BINDING_REQUIRED')
        result = run(config)
    except Exception as exc:
        result = {'observed_at': time.time(), 'status': 'HOST_BINDING_BLOCKED',
                  'error_type': type(exc).__name__, 'production_klm_accepted': False}
    write_report(args.report, result)
    # Private report carries exact state. Quiet stdout for ordinary unattended waits.
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

