import subprocess
from pathlib import Path


def test_project_declares_installable_src_package():
    text=Path("pyproject.toml").read_text()
    assert '[build-system]' in text
    assert 'build-backend = "hatchling.build"' in text
    assert 'packages = ["src/ai_foundation"]' in text


def test_operator_imports_from_synced_environment():
    completed=subprocess.run(
        [".venv/bin/python","-c","import ai_foundation; print(ai_foundation.__path__)"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
