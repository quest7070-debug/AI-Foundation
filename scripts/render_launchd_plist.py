#!/usr/bin/env python3
from pathlib import Path
import argparse
p=argparse.ArgumentParser();p.add_argument('--template',required=True);p.add_argument('--repo-root',required=True);p.add_argument('--config',required=True);p.add_argument('--log-dir',required=True);p.add_argument('--output',required=True);a=p.parse_args()
t=Path(a.template).read_text(); values={'__REPO_ROOT__':str(Path(a.repo_root).resolve()),'__CONFIG_PATH__':str(Path(a.config).expanduser().resolve()),'__LOG_DIR__':str(Path(a.log_dir).expanduser().resolve())}
for key,value in values.items():t=t.replace(key,value)
Path(a.output).write_text(t)
