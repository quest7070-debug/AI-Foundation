import os
from pathlib import Path

def test_toolhive_bootstrap_is_directly_executable_and_pinned():
 p=Path("scripts/bootstrap-toolhive.sh")
 assert os.access(p,os.X_OK)
 t=p.read_text()
 assert "EXPECTED_VERSION=\"0.49.0\"" in t
 assert "EXPECTED_SHA256=" in t
 assert "darwin/arm64" in t
