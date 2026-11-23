"""Host-bound CODE construction. Test execution is fixed by host policy, not model text."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
from .agent_tools import CapabilityAgentTools,GuardedToolGateway,ReadCapability,WriteCapability
from .coding import CodingSpecialist
from .core import CanonContract
from .capability_request import CapabilityRequest

@dataclass(frozen=True)
class PytestPort:
    repo_root: str
    timeout: int = 240

    def acceptance_path(self, target: str) -> Path:
        """Host-owned test selection: use a matching test module if present."""
        root=Path(self.repo_root).resolve()
        # A host-invoked empty target means repository-wide pytest discovery.
        # Keep this existing test-port contract; CODE/change uses a source path.
        if not target:
            return root
        source=(root/target).resolve()
        try:
            relative=source.relative_to(root)
        except ValueError as e:
            raise PermissionError("test target outside bound repository") from e
        tests=root/"tests"
        if not relative.parts or relative.parts[0] != "tests":
            if not tests.is_dir():
                raise PermissionError("NO_HOST_ACCEPTANCE_SUITE")
            matched=tests/("test_"+source.stem+".py")
            # Never follow an untrusted test symlink outside the repository.
            source=matched.resolve() if matched.is_file() else tests.resolve()
            try:
                source.relative_to(root)
            except ValueError as e:
                raise PermissionError("test target outside bound repository") from e
        return source

    def _run_pytest(self, target: str) -> tuple[int, str]:
        root=Path(self.repo_root).resolve()
        candidate=self.acceptance_path(target)
        pytest=root/".venv/bin/pytest"
        argv=[str(pytest)] if pytest.is_file() else [sys.executable,"-m","pytest"]
        cp=subprocess.run([*argv,"-q",str(candidate)],cwd=str(root),capture_output=True,text=True,timeout=self.timeout)
        # Keep bounded diagnostic output; no shell and no model-selected command.
        tail=(cp.stdout+"\n"+cp.stderr)[-8000:].strip()
        return cp.returncode, tail

    def run_tests(self,target:str)->str:
        code, tail = self._run_pytest(target)
        if code: raise RuntimeError("tests failed: "+tail)
        return tail

    def run_acceptance(self, target: str):
        """Exit-code-backed receipt for DevelopmentLoop, not inferred from stdout."""
        from .development_loop import TestAcceptanceReceipt
        code, tail = self._run_pytest(target)
        return TestAcceptanceReceipt(passed=(type(code) is int and code == 0), detail=tail)

def build_coding_specialist(request:CapabilityRequest,guard,port,run_id:str,*,reconciliation_registry=None,port_binding="",protected=None):
    if request.capability!="CODE": raise ValueError("CODE capability required")
    root=str(Path(request.repo_root).resolve())
    if protected is not None: protected.validate_scope(root,True)
    tools=CapabilityAgentTools(
        GuardedToolGateway(guard,CanonContract("foundation-code","code-v1"),port,reconciliation_registry,port_binding),
        run_id,"code-v1",ReadCapability(root),WriteCapability(root))
    # PytestPort maps authorized source paths to host-owned tests. The model
    # never receives a choice of test command, runner or external path.
    return CodingSpecialist(tools,PytestPort(root),protected)
