from pathlib import Path
import subprocess
import sys

from ai_foundation.capability_request import CapabilityRequest
from ai_foundation.code_intelligence import (
    CodeIntelligenceKind,
    CodeIntelligenceRelation,
    CodeIntelligenceResult,
    CodeIntelligenceStatus,
    CodeIntelligenceSubjectKind,
)
from ai_foundation.coding_adapter import build_coding_specialist
from ai_foundation.core import GuardState
from ai_foundation.development_context import (
    DevelopmentContextCompiler,
    DevelopmentRequest,
)
from ai_foundation.guard import GuardCore
from ai_foundation.safe_change import SafeChangeCoordinator
from ai_foundation.semantic_linker import (
    CanonicalReference,
    FoundationSemanticLinker,
    SemanticLink,
)


class RealFilePort:
    """Actual filesystem port used behind the real Guard path."""

    def execute(self, plan):
        Path(plan.target).write_text(plan.text)

    def observe(self, plan):
        return Path(plan.target).read_text()


class BoundRealPytest:
    """Physical pytest runner bound by the host to one isolated repo."""

    def __init__(self, repo):
        self.repo = Path(repo).resolve()

    def run_tests(self, target):
        candidate = (self.repo / target).resolve()

        try:
            candidate.relative_to(self.repo)
        except ValueError as exc:
            raise PermissionError(
                "test target escapes bound repository"
            ) from exc

        cp = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", str(self.repo)],
            cwd=str(self.repo),
            capture_output=True,
            text=True,
            timeout=120,
        )

        output = "\n".join(
            x.strip()
            for x in (cp.stdout, cp.stderr)
            if x and x.strip()
        )

        if cp.returncode != 0:
            raise RuntimeError(
                output or f"pytest exited {cp.returncode}"
            )

        return output



class DeterministicDevelopmentBackend:
    """Deterministic DI evidence for the isolated physical repository.

    This is intentionally not another authority layer.  It supplies only
    derived TESTS/IMPACT/DEPENDENCIES observations to the real
    DevelopmentContextCompiler.
    """

    def __init__(self):
        self.queries = []

    def inspect(self, query):
        self.queries.append(query)

        mapping = {
            CodeIntelligenceKind.TESTS: (
                CodeIntelligenceRelation(
                    target="tests/test_calc.py::test_add",
                    relation="TESTED_BY",
                    file="tests/test_calc.py",
                    line=4,
                ),
            ),
            CodeIntelligenceKind.IMPACT: (),
            CodeIntelligenceKind.DEPENDENCIES: (),
        }

        return CodeIntelligenceResult(
            kind=query.kind,
            subject=query.subject,
            status=CodeIntelligenceStatus.OK,
            relations=mapping.get(query.kind, ()),
            backend="deterministic-e2e",
            backend_version="1",
            index_revision="isolated-repo-revision-1",
            fresh=True,
            uncertainty="",
        )


def make_request():
    link = SemanticLink(
        canonical_reference=CanonicalReference(
            source_path="docs/CURRENT_STATE.md",
            locator="Safe Change Loop",
            claim_kind="IMPLEMENTATION_CONSTRAINT",
        ),
        code_subject="src/calc.py::add",
        subject_kind=CodeIntelligenceSubjectKind.SYMBOL,
        evidence_refs=("e2e:test_calc",),
        provenance="owner-verified-e2e",
    )

    return DevelopmentRequest(
        text="Repair the bounded add implementation",
        semantic_links=(link,),
    )


def test_safe_change_real_guard_real_file_real_pytest(tmp_path):
    repo = tmp_path / "isolated-repo"
    src = repo / "src"
    tests = repo / "tests"

    src.mkdir(parents=True)
    tests.mkdir()

    target = src / "calc.py"

    # Valid initial state so CodingSpecialist's mandatory pre-test passes.
    target.write_text(
        "def add(a, b):\n"
        "    return a + b\n"
    )

    (tests / "test_calc.py").write_text(
        "from src.calc import add\n\n"
        "def test_add():\n"
        "    assert add(2, 3) == 5\n"
    )

    backend = DeterministicDevelopmentBackend()
    compiler = DevelopmentContextCompiler(
        FoundationSemanticLinker(backend),
        backend,
    )

    specialist = build_coding_specialist(
        CapabilityRequest(
            "CODE",
            repo_root=str(repo),
        ),
        GuardCore(GuardState()),
        RealFilePort(),
        "safe-change-e2e",
    )

    specialist.tests = BoundRealPytest(repo)

    coordinator = SafeChangeCoordinator(
        compiler,
        specialist,
    )

    replacement = (
        "def add(a, b):\n"
        "    # Equivalent implementation applied through Safe Change.\n"
        "    return b + a\n"
    )

    result = coordinator.apply(
        make_request(),
        "src/calc.py",
        replacement,
    )

    assert result.status == "VERIFIED"
    assert result.mutated is True
    assert result.coding_result is not None
    assert result.coding_result.write_result == "VERIFIED_COMPLETE"

    # Independent physical readback.
    assert target.read_text() == replacement

    # Prove the real compiler observed all required evidence classes.
    assert [q.kind for q in backend.queries] == [
        CodeIntelligenceKind.TESTS,
        CodeIntelligenceKind.IMPACT,
        CodeIntelligenceKind.DEPENDENCIES,
    ]

    assert result.context.fresh is True
    assert result.context.uncertainties == ()
    assert result.context.code_subjects == ("src/calc.py::add",)

    assert [x.target for x in result.context.affected_tests] == [
        "tests/test_calc.py::test_add"
    ]

    # CodingSpecialist actually ran pytest before and after the write.
    assert "before=" in result.coding_result.test_result
    assert "after=" in result.coding_result.test_result
    assert "passed" in result.coding_result.test_result


def test_safe_change_real_path_blocks_context_target_mismatch(tmp_path):
    repo = tmp_path / "isolated-repo"
    src = repo / "src"
    tests = repo / "tests"

    src.mkdir(parents=True)
    tests.mkdir()

    target = src / "calc.py"
    other = src / "other.py"

    target.write_text("def add(a, b):\n    return a + b\n")
    other.write_text("VALUE = 'original'\n")

    (tests / "test_calc.py").write_text(
        "from src.calc import add\n\n"
        "def test_add():\n"
        "    assert add(2, 3) == 5\n"
    )

    backend = DeterministicDevelopmentBackend()

    coordinator = SafeChangeCoordinator(
        DevelopmentContextCompiler(
            FoundationSemanticLinker(backend),
            backend,
        ),
        build_coding_specialist(
            CapabilityRequest(
                "CODE",
                repo_root=str(repo),
            ),
            GuardCore(GuardState()),
            RealFilePort(),
            "safe-change-e2e-block",
        ),
    )

    result = coordinator.apply(
        make_request(),
        "src/other.py",
        "VALUE = 'mutated'\n",
    )

    assert result.status == "BLOCKED"
    assert result.mutated is False
    assert other.read_text() == "VALUE = 'original'\n"


def test_safe_change_real_guard_still_rejects_repo_escape(tmp_path):
    repo = tmp_path / "isolated-repo"
    src = repo / "src"
    tests = repo / "tests"

    src.mkdir(parents=True)
    tests.mkdir()

    (src / "calc.py").write_text(
        "def add(a, b):\n"
        "    return a + b\n"
    )

    (tests / "test_calc.py").write_text(
        "from src.calc import add\n\n"
        "def test_add():\n"
        "    assert add(2, 3) == 5\n"
    )

    backend = DeterministicDevelopmentBackend()

    specialist = build_coding_specialist(
        CapabilityRequest(
            "CODE",
            repo_root=str(repo),
        ),
        GuardCore(GuardState()),
        RealFilePort(),
        "safe-change-e2e-escape",
    )

    # Directly exercise the same specialist boundary used by Safe Change:
    # SafeChangeCoordinator does not replace filesystem authorization.
    try:
        specialist.apply_verified_change(
            "../escape.py",
            "BAD = True\n",
        )
    except PermissionError:
        pass
    else:
        raise AssertionError("real CODE boundary allowed repository escape")

    assert not (tmp_path / "escape.py").exists()
