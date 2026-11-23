#!/usr/bin/env python3
"""Dedicated Hatchet worker using the same trusted capability composition as Operator."""
import argparse,os
from pathlib import Path
from ai_foundation.productization import load_config
from ai_foundation.store import SQLiteGuardStore
from ai_foundation.guard import GuardCore
from ai_foundation.storage_admission import StorageAdmission,DEFAULT_MIN_FREE_BYTES
from ai_foundation.reconciliation_registry import SQLiteReconciliationRegistry
from ai_foundation.native_credentials import MacOSNativeCredentialStore
from ai_foundation.capability_composition import build_capability_composition
from ai_foundation.long_running_runtime import build_long_running_runtime

def main():
 p=argparse.ArgumentParser();p.add_argument('--config',required=True);a=p.parse_args()
 c=load_config(a.config);root=Path(c.data_dir);root.mkdir(parents=True,exist_ok=True)
 admission=StorageAdmission(root,min_free_bytes=int(os.getenv('AI_FOUNDATION_MIN_WRITE_FREE_BYTES',str(DEFAULT_MIN_FREE_BYTES))))
 gs=SQLiteGuardStore(root/c.guard_db,storage_admission=admission);guard=GuardCore(gs.runtime_state(),store=gs)
 reconciliation=SQLiteReconciliationRegistry(root/c.reconciliation_db,storage_admission=admission)
 from ai_foundation.inference_composition import build_inference_composition
 inference=build_inference_composition(root=root,config=c,guard=guard,storage_admission=admission)
 composition=build_capability_composition(repo_base=Path(__file__).parents[1],data_root=root,config=c,inference=inference.service,guard=guard,reconciliation_registry=reconciliation)
 runtime=build_long_running_runtime(root,composition.executor,MacOSNativeCredentialStore())
 runtime.worker.start()
if __name__=='__main__':main()
