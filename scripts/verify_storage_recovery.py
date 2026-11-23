#!/usr/bin/env python3
"""Non-destructive production storage-policy verification.

Uses the real filesystem observation and canonical policy class, but raises the
reserve above current free space instead of consuming disk. Writes only to a
private temporary SQLite database and removes it afterwards.
"""
import argparse, json, shutil, tempfile
from pathlib import Path
from ai_foundation.storage_admission import StorageAdmission, DEFAULT_MIN_FREE_BYTES, StorageCapacityError
from ai_foundation.task_intake import TaskIntake
from ai_foundation.long_term_health import check_long_term_health

def main():
 p=argparse.ArgumentParser();p.add_argument('--data-dir',required=True);a=p.parse_args()
 root=Path(a.data_dir).expanduser().resolve(); real=StorageAdmission(root,min_free_bytes=DEFAULT_MIN_FREE_BYTES)
 before=real.status()
 if before.free_bytes is None: raise SystemExit('storage observation unavailable')
 with tempfile.TemporaryDirectory(prefix='foundation-storage-verify-',dir=root) as td:
  td=Path(td); simulated_reserve=before.free_bytes+1
  blocked=StorageAdmission(root,min_free_bytes=simulated_reserve)
  intake=TaskIntake(td/'work.db',storage_admission=blocked)
  rejected=False
  try:intake.submit('storage recovery verification')
  except StorageCapacityError:rejected=True
  no_blocked_row=(intake.recent()==[])
  failed_signal=next(x for x in check_long_term_health(root,storage_admission=blocked).signals if x.name=='free-space')
  recovered=StorageAdmission(root,min_free_bytes=DEFAULT_MIN_FREE_BYTES)
  receipt=intake.__class__(td/'recovered.db',storage_admission=recovered).submit('storage recovery verification')
  healthy_signal=next(x for x in check_long_term_health(root,storage_admission=recovered).signals if x.name=='free-space')
  result={'real_free_bytes':before.free_bytes,'normal_reserve_bytes':DEFAULT_MIN_FREE_BYTES,'simulated_reserve_bytes':simulated_reserve,'blocked_write_rejected':rejected,'blocked_write_left_no_row':no_blocked_row,'blocked_health_ok':failed_signal.ok,'recovered_write_ok':receipt.text=='storage recovery verification','recovered_health_ok':healthy_signal.ok}
  print(json.dumps(result,separators=(',',':')))
  if not (rejected and no_blocked_row and not failed_signal.ok and result['recovered_write_ok'] and healthy_signal.ok):raise SystemExit(2)
if __name__=='__main__':main()
