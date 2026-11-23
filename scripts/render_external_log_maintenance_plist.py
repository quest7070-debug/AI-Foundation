from pathlib import Path
import argparse

p=argparse.ArgumentParser()
p.add_argument('--repo-root', required=True)
p.add_argument('--config', required=True)
p.add_argument('--output', required=True)
a=p.parse_args()
root=Path(a.repo_root).resolve()
t=(root/'ops/launchd/dev.quest7070.ai-foundation.external-log-maintenance.plist').read_text()
t=t.replace('__REPO_ROOT__', str(root)).replace('__CONFIG_PATH__', str(Path(a.config).expanduser().resolve()))
Path(a.output).write_text(t)
