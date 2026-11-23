from pathlib import Path
import os, subprocess, pytest
ROOT=Path(__file__).parents[1]
THV=ROOT/'.tools/toolhive/thv'
SCRIPT=ROOT/'scripts/toolhive-filesystem.sh'

def test_toolhive_binary_is_not_tracked():
    cp=subprocess.run(['git','check-ignore',str(THV)],cwd=ROOT,capture_output=True,text=True)
    assert cp.returncode == 0

@pytest.mark.skipif(os.getenv('AI_FOUNDATION_TOOLHIVE_E2E') != '1' or not THV.exists(), reason='live ToolHive E2E is opt-in')
def test_toolhive_lifecycle_recreates_stopped_workload():
    env={**os.environ,'AI_FOUNDATION_THV':str(THV)}
    subprocess.run([str(SCRIPT),'stop'],cwd=ROOT,env=env,check=True,capture_output=True,text=True)
    subprocess.run([str(SCRIPT),'ensure'],cwd=ROOT,env=env,check=True,capture_output=True,text=True,timeout=60)
    cp=subprocess.run([str(SCRIPT),'status'],cwd=ROOT,env=env,check=True,capture_output=True,text=True)
    assert 'Status:' in cp.stdout and 'running' in cp.stdout

@pytest.mark.skipif(os.getenv('AI_FOUNDATION_TOOLHIVE_E2E') != '1' or not THV.exists(), reason='live ToolHive E2E is opt-in')
def test_toolhive_remove_then_ensure_recovers_and_serves_mcp():
    env={**os.environ,'AI_FOUNDATION_THV':str(THV)}
    subprocess.run([str(SCRIPT),'remove'],cwd=ROOT,env=env,check=True,capture_output=True,text=True)
    subprocess.run([str(SCRIPT),'ensure'],cwd=ROOT,env=env,check=True,capture_output=True,text=True,timeout=60)
    cp=subprocess.run([str(THV),'mcp','list','--server','ai-foundation-fs','--format','json'],cwd=ROOT,env=env,capture_output=True,text=True,timeout=30)
    assert cp.returncode == 0
    assert 'write_file' in cp.stdout

def test_toolhive_lifecycle_pins_expected_filesystem_digest():
    text=SCRIPT.read_text()
    assert 'sha256:720393842ef8b0f33713a42e2eebda51ff600756c19d53e1244645ec59496fef' in text
    assert 'filesystem image digest mismatch' in text
