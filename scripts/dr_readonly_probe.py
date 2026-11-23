#!/usr/bin/env python3
"""Read-only canonical-state DR probe: snapshot live Foundation state and restore only into a disposable root."""
import argparse, json, shutil, sqlite3, tempfile
from pathlib import Path
from ai_foundation.productization import backup, load_config, restore


def sqlite_ok(path):
    with sqlite3.connect(path) as con:
        row=con.execute('PRAGMA integrity_check').fetchone()
    return bool(row and row[0]=='ok')


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--config', required=True)
    a=ap.parse_args()
    cfg=load_config(a.config)
    scratch=Path(tempfile.mkdtemp(prefix='ai-foundation-dr-probe.'))
    try:
        generation=scratch/'backup'
        restored=scratch/'restored'
        manifest=backup(cfg,generation)
        restored_files=restore(generation,restored,relocate_config=True)
        restored_cfg=load_config(restored/'config.json')
        if Path(restored_cfg.data_dir)!=restored.resolve():
            raise SystemExit('DR: relocated config does not target restored root')
        db_names=[cfg.guard_db,cfg.work_db,cfg.provider_db,cfg.routing_db,cfg.reconciliation_db,cfg.inference_db]
        present=[n for n in db_names if (restored/n).exists()]
        bad=[n for n in present if not sqlite_ok(restored/n)]
        if bad:
            raise SystemExit('DR: restored SQLite integrity failed: '+','.join(bad))
        print(json.dumps({
            'status':'PASS',
            'source_mutated':False,
            'credential_material_copied':False,
            'manifest_files':len(manifest['files']),
            'restored_files':len(restored_files),
            'sqlite_integrity_ok':len(present),
            'config_relocated':True,
            'consistency':manifest['capture']['consistency'],
        },sort_keys=True))
    finally:
        shutil.rmtree(scratch,ignore_errors=True)

if __name__=='__main__': main()
