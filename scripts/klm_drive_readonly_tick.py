#!/usr/bin/env python3
"""Replay an authorized read-only connector capture into existing Durable Work.

This does not install a 15-minute schedule or a model handler. For host integration,
use ReadOnlyDriveAPI(OwnerDriveHTTP(explicit_token_provider)) with the same scanner.
"""
import argparse
import json
from pathlib import Path
from ai_foundation.durable_work import SQLiteWorkStore
from ai_foundation.klm_drive_runtime import process_capture


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--capture',required=True,type=Path)
    p.add_argument('--work-db',required=True,type=Path)
    p.add_argument('--report',required=True,type=Path)
    args=p.parse_args()
    if args.capture.stat().st_size>4_000_000: raise ValueError('CAPTURE_TOO_LARGE')
    for path in (args.work_db,args.report):
        if path.is_symlink(): raise PermissionError('SYMLINK_PATH')
    result=process_capture(json.loads(args.capture.read_text()),SQLiteWorkStore(args.work_db))
    args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    args.report.chmod(0o600)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__': main()
