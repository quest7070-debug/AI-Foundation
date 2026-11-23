import plistlib, subprocess
from pathlib import Path
ROOT=Path(__file__).parents[1]
NAMES=('dev.quest7070.ai-foundation.operator.plist','dev.quest7070.ai-foundation.chat-gateway.plist','dev.quest7070.ai-foundation.echo-gateway.plist')

def test_tracked_launchd_templates_do_not_embed_owner_home():
 for name in NAMES:
  text=(ROOT/'ops/launchd'/name).read_text()
  assert '/Users/yourname' not in text
  assert '__REPO_ROOT__' in text

def test_launchd_templates_render_for_arbitrary_root(tmp_path):
 repo=tmp_path/'checkout'; config=tmp_path/'state/config.json'; logs=tmp_path/'logs'; config.parent.mkdir(); config.write_text('{}')
 for name in NAMES:
  out=tmp_path/name
  subprocess.run([str(ROOT/'.venv/bin/python'),str(ROOT/'scripts/render_launchd_plist.py'),'--template',str(ROOT/'ops/launchd'/name),'--repo-root',str(repo),'--config',str(config),'--log-dir',str(logs),'--output',str(out)],check=True)
  text=out.read_text(); row=plistlib.loads(out.read_bytes())
  assert '__REPO_ROOT__' not in text and '__CONFIG_PATH__' not in text and '__LOG_DIR__' not in text
  assert str(repo.resolve()) in text
  assert row['ProgramArguments']
