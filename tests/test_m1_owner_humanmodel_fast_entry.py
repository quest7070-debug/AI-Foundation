"""No model/private data: selected Python comes only from trusted Operator."""
import os
from pathlib import Path
import plistlib
from scripts import m1_owner_humanmodel_fast_entry as x


def test_operator_python_not_inferred_from_path_or_issue(tmp_path, monkeypatch):
    root = tmp_path / "user"
    launch = root / "Library/LaunchAgents"
    launch.mkdir(parents=True)
    monkeypatch.setattr(x.Path, "home", lambda: root)
    monkeypatch.setattr(x.readiness, "installed_paths", lambda: (root / "launch.py", root))
    target = tmp_path / "python3.12"
    target.write_text("#!/bin/sh\n")
    target.chmod(0o700)
    for candidate in ("/bin/sh", "python3.12", "/tmp/other"):
        (launch / "dev.quest7070.ai-foundation.operator.plist").write_bytes(
            plistlib.dumps({"ProgramArguments": [candidate, "source.py", "--config", "cfg.json"]}))
        assert x.installed_python() is None
