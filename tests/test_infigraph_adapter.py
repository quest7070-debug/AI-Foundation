from __future__ import annotations

import subprocess
from pathlib import Path

from ai_foundation.code_intelligence import (
    CodeIntelligenceKind,
    CodeIntelligenceQuery,
    CodeIntelligenceStatus,
    CodeIntelligenceSubjectKind,
)
from ai_foundation.infigraph_adapter import InfigraphCodeIntelligence


SUBJECT = "src/ai_foundation/compute_routing.py::ComputeRouter::choose"


class Runner:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def completed(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(
        args=["infigraph"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def adapter(runner):
    return InfigraphCodeIntelligence(
        executable=Path("/opt/test/infigraph"),
        root=Path("/repo"),
        runner=runner,
        timeout_seconds=7.0,
    )


def test_references_resolves_subject_then_returns_locations():
    runner = Runner(
        [
            completed("infigraph 3.2.16\n"),
            completed(
                "(label:Symbol, 0:1, "
                "{id:src/ai_foundation/compute_routing.py::"
                "ComputeRouter::choose,name:choose})\n"
            ),
            completed(
                "References to "
                "'src/ai_foundation/compute_routing.py::ComputeRouter::choose' "
                "(2 total):\n\n"
                "  tests/test_compute_routing.py:41"
                "     in test_vision_selects_explicit_local_candidate\n"
                "  scripts/local_inventory_lifecycle_sweep.py:23"
                "     in main\n"
            ),
        ]
    )

    result = adapter(runner).inspect(
        CodeIntelligenceQuery(
            CodeIntelligenceKind.REFERENCES,
            SUBJECT,
            CodeIntelligenceSubjectKind.SYMBOL,
        )
    )

    assert result.status is CodeIntelligenceStatus.OK
    assert result.backend == "infigraph"
    assert result.backend_version == "3.2.16"
    assert result.fresh is False
    assert "freshness" in result.uncertainty.lower()

    assert [
        (r.file, r.line, r.relation)
        for r in result.relations
    ] == [
        ("tests/test_compute_routing.py", 41, "REFERENCE"),
        ("scripts/local_inventory_lifecycle_sweep.py", 23, "REFERENCE"),
    ]

    assert result.relations[0].target == (
        "tests/test_compute_routing.py"
        "::test_vision_selects_explicit_local_candidate"
    )
    assert result.relations[1].target == (
        "scripts/local_inventory_lifecycle_sweep.py::main"
    )

    assert runner.calls[0][0] == [
        "/opt/test/infigraph",
        "--version",
    ]
    assert runner.calls[1][0][1] == "query"
    assert runner.calls[2][0] == [
        "/opt/test/infigraph",
        "find-refs",
        SUBJECT,
    ]

    for _, kwargs in runner.calls:
        assert kwargs["cwd"] == Path("/repo")
        assert kwargs["timeout"] == 7.0
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        assert kwargs["check"] is False


def test_known_subject_with_no_references_is_ok_empty():
    runner = Runner(
        [
            completed("infigraph 3.2.16\n"),
            completed("(label:Symbol, 0:1, {id:src/x.py::f,name:f})\n"),
            completed("No references found for 'src/x.py::f'\n"),
        ]
    )

    result = adapter(runner).inspect(
        CodeIntelligenceQuery(
            CodeIntelligenceKind.REFERENCES,
            "src/x.py::f",
            CodeIntelligenceSubjectKind.SYMBOL,
        )
    )

    assert result.status is CodeIntelligenceStatus.OK
    assert result.relations == ()


def test_missing_subject_is_unknown_without_find_refs():
    runner = Runner(
        [
            completed("infigraph 3.2.16\n"),
            completed("(no results)\n"),
        ]
    )

    result = adapter(runner).inspect(
        CodeIntelligenceQuery(
            CodeIntelligenceKind.REFERENCES,
            "src/missing.py::Missing::run",
            CodeIntelligenceSubjectKind.SYMBOL,
        )
    )

    assert result.status is CodeIntelligenceStatus.UNKNOWN
    assert result.relations == ()
    assert "not present" in result.uncertainty
    assert len(runner.calls) == 2


def test_backend_process_failure_is_unavailable():
    runner = Runner(
        [
            completed("infigraph 3.2.16\n"),
            completed(stderr="graph unavailable\n", returncode=2),
        ]
    )

    result = adapter(runner).inspect(
        CodeIntelligenceQuery(
            CodeIntelligenceKind.REFERENCES,
            SUBJECT,
            CodeIntelligenceSubjectKind.SYMBOL,
        )
    )

    assert result.status is CodeIntelligenceStatus.UNAVAILABLE
    assert result.relations == ()
    assert "graph unavailable" in result.uncertainty


def test_timeout_is_unavailable():
    runner = Runner(
        [
            completed("infigraph 3.2.16\n"),
            subprocess.TimeoutExpired(
                cmd=["infigraph", "query"],
                timeout=7,
            ),
        ]
    )

    result = adapter(runner).inspect(
        CodeIntelligenceQuery(
            CodeIntelligenceKind.REFERENCES,
            SUBJECT,
            CodeIntelligenceSubjectKind.SYMBOL,
        )
    )

    assert result.status is CodeIntelligenceStatus.UNAVAILABLE
    assert "timed out" in result.uncertainty


def test_unsupported_backend_version_fails_closed():
    runner = Runner(
        [
            completed("infigraph 3.3.0\n"),
        ]
    )

    result = adapter(runner).inspect(
        CodeIntelligenceQuery(
            CodeIntelligenceKind.REFERENCES,
            SUBJECT,
            CodeIntelligenceSubjectKind.SYMBOL,
        )
    )

    assert result.status is CodeIntelligenceStatus.UNAVAILABLE
    assert result.backend_version == "3.3.0"
    assert "unsupported" in result.uncertainty
    assert len(runner.calls) == 1


def test_malformed_reference_output_fails_closed():
    runner = Runner(
        [
            completed("infigraph 3.2.16\n"),
            completed("(label:Symbol, 0:1, {id:src/x.py::f,name:f})\n"),
            completed(
                "References to 'src/x.py::f' (1 total):\n\n"
                "  THIS IS NOT A REFERENCE LOCATION\n"
            ),
        ]
    )

    result = adapter(runner).inspect(
        CodeIntelligenceQuery(
            CodeIntelligenceKind.REFERENCES,
            "src/x.py::f",
            CodeIntelligenceSubjectKind.SYMBOL,
        )
    )

    assert result.status is CodeIntelligenceStatus.UNAVAILABLE
    assert result.relations == ()
    assert "parse" in result.uncertainty.lower()


def test_adapter_declares_exact_supported_query_kinds():
    assert InfigraphCodeIntelligence.SUPPORTED_KINDS == frozenset(
        {
            CodeIntelligenceKind.REFERENCES,
            CodeIntelligenceKind.IMPACT,
            CodeIntelligenceKind.TESTS,
            CodeIntelligenceKind.DEPENDENCIES,
            CodeIntelligenceKind.CALLS,
            CodeIntelligenceKind.INVENTORY,
        }
    )

    assert (
        set(CodeIntelligenceKind)
        - InfigraphCodeIntelligence.SUPPORTED_KINDS
    ) == {
        CodeIntelligenceKind.SCOPED_VARIABLES,
        CodeIntelligenceKind.READS,
        CodeIntelligenceKind.WRITES,
    }


def test_adapter_rejects_scoped_name_kinds_before_backend_execution():
    runner = Runner([])
    instance = adapter(runner)

    for kind in (
        CodeIntelligenceKind.SCOPED_VARIABLES,
        CodeIntelligenceKind.READS,
        CodeIntelligenceKind.WRITES,
    ):
        result = instance.inspect(
            CodeIntelligenceQuery(
                kind,
                "src/ai_foundation/example.py",
                CodeIntelligenceSubjectKind.FILE,
            )
        )

        assert result.status is CodeIntelligenceStatus.UNAVAILABLE
        assert result.relations == ()
        assert "not implemented" in result.uncertainty

    assert runner.calls == []

def test_impact_returns_backend_impact_without_inventing_locations():
    runner = Runner(
        [
            completed("infigraph 3.2.16\n"),
            completed(
                "(label:Symbol, 0:1, "
                "{id:src/ai_foundation/compute_routing.py::"
                "ComputeRouter::choose,name:choose})\n"
            ),
            completed(
                "Symbols affected by changes to "
                "'src/ai_foundation/compute_routing.py::"
                "ComputeRouter::choose' (depth=3):\n\n"
                "      Test test_local_required_never_falls_to_cloud "
                "tests/test_compute_routing.py\n"
                "  Function main "
                "scripts/local_inventory_lifecycle_sweep.py\n"
            ),
        ]
    )

    result = adapter(runner).inspect(
        CodeIntelligenceQuery(
            CodeIntelligenceKind.IMPACT,
            SUBJECT,
            CodeIntelligenceSubjectKind.SYMBOL,
        )
    )

    assert result.status is CodeIntelligenceStatus.OK
    assert result.fresh is False

    assert [
        (r.target, r.relation, r.file, r.line)
        for r in result.relations
    ] == [
        (
            "tests/test_compute_routing.py"
            "::test_local_required_never_falls_to_cloud",
            "IMPACT",
            "tests/test_compute_routing.py",
            None,
        ),
        (
            "scripts/local_inventory_lifecycle_sweep.py::main",
            "IMPACT",
            "scripts/local_inventory_lifecycle_sweep.py",
            None,
        ),
    ]

    assert runner.calls[2][0] == [
        "/opt/test/infigraph",
        "impact",
        "--depth",
        "3",
        SUBJECT,
    ]


def test_known_subject_with_no_impact_is_ok_empty():
    runner = Runner(
        [
            completed("infigraph 3.2.16\n"),
            completed("(label:Symbol, 0:1, {id:src/x.py::f,name:f})\n"),
            completed(
                "No symbols affected by changes to 'src/x.py::f'\n"
            ),
        ]
    )

    result = adapter(runner).inspect(
        CodeIntelligenceQuery(
            CodeIntelligenceKind.IMPACT,
            "src/x.py::f",
            CodeIntelligenceSubjectKind.SYMBOL,
        )
    )

    assert result.status is CodeIntelligenceStatus.OK
    assert result.relations == ()


def test_malformed_impact_output_fails_closed():
    runner = Runner(
        [
            completed("infigraph 3.2.16\n"),
            completed("(label:Symbol, 0:1, {id:src/x.py::f,name:f})\n"),
            completed(
                "Symbols affected by changes to "
                "'src/x.py::f' (depth=3):\n\n"
                "  THIS CANNOT BE NORMALIZED\n"
            ),
        ]
    )

    result = adapter(runner).inspect(
        CodeIntelligenceQuery(
            CodeIntelligenceKind.IMPACT,
            "src/x.py::f",
            CodeIntelligenceSubjectKind.SYMBOL,
        )
    )

    assert result.status is CodeIntelligenceStatus.UNAVAILABLE
    assert result.relations == ()
    assert "parse" in result.uncertainty.lower()


def test_reference_rejects_file_subject_without_backend_call():
    runner = Runner([])

    result = adapter(runner).inspect(
        CodeIntelligenceQuery(
            CodeIntelligenceKind.REFERENCES,
            "src/ai_foundation/compute_routing.py",
            CodeIntelligenceSubjectKind.FILE,
        )
    )

    assert result.status is CodeIntelligenceStatus.UNAVAILABLE
    assert result.relations == ()
    assert "SYMBOL" in result.uncertainty
    assert runner.calls == []


def test_dependencies_require_file_subject_without_backend_call():
    runner = Runner([])

    result = adapter(runner).inspect(
        CodeIntelligenceQuery(
            CodeIntelligenceKind.DEPENDENCIES,
            SUBJECT,
            CodeIntelligenceSubjectKind.SYMBOL,
        )
    )

    assert result.status is CodeIntelligenceStatus.UNAVAILABLE
    assert result.relations == ()
    assert "FILE" in result.uncertainty
    assert runner.calls == []


def test_dependencies_preserve_import_direction():
    subject = "src/ai_foundation/compute_routing.py"

    runner = Runner(
        [
            completed("infigraph 3.2.16\n"),
            completed(
                "Symbols in src/ai_foundation/compute_routing.py:\n"
                "     Class ComputeRoute L4-8\n"
            ),
            completed(
                "File dependencies for "
                "'src/ai_foundation/compute_routing.py':\n\n"
                "  Imports (1):\n"
                "    → src/ai_foundation/routing_capabilities.py\n\n"
                "  Imported by (2):\n"
                "    ← tests/test_compute_routing.py\n"
                "    ← src/ai_foundation/inference_composition.py\n"
            ),
        ]
    )

    result = adapter(runner).inspect(
        CodeIntelligenceQuery(
            CodeIntelligenceKind.DEPENDENCIES,
            subject,
            CodeIntelligenceSubjectKind.FILE,
        )
    )

    assert result.status is CodeIntelligenceStatus.OK
    assert result.fresh is False

    assert [
        (r.target, r.relation, r.file, r.line)
        for r in result.relations
    ] == [
        (
            "src/ai_foundation/routing_capabilities.py",
            "IMPORTS",
            "src/ai_foundation/routing_capabilities.py",
            None,
        ),
        (
            "tests/test_compute_routing.py",
            "IMPORTED_BY",
            "tests/test_compute_routing.py",
            None,
        ),
        (
            "src/ai_foundation/inference_composition.py",
            "IMPORTED_BY",
            "src/ai_foundation/inference_composition.py",
            None,
        ),
    ]

    assert runner.calls[1][0] == [
        "/opt/test/infigraph",
        "symbols",
        subject,
    ]

    assert runner.calls[2][0] == [
        "/opt/test/infigraph",
        "file-deps",
        subject,
    ]


def test_missing_dependency_file_is_unknown_before_file_deps():
    subject = "src/ai_foundation/__missing__.py"

    runner = Runner(
        [
            completed("infigraph 3.2.16\n"),
            completed(
                "No symbols found for "
                "'src/ai_foundation/__missing__.py'. "
                "Run 'infigraph index' first.\n"
            ),
        ]
    )

    result = adapter(runner).inspect(
        CodeIntelligenceQuery(
            CodeIntelligenceKind.DEPENDENCIES,
            subject,
            CodeIntelligenceSubjectKind.FILE,
        )
    )

    assert result.status is CodeIntelligenceStatus.UNKNOWN
    assert result.relations == ()
    assert "not present" in result.uncertainty
    assert len(runner.calls) == 2


def test_known_file_with_zero_dependencies_is_ok_empty():
    subject = "src/example.py"

    runner = Runner(
        [
            completed("infigraph 3.2.16\n"),
            completed(
                "Symbols in src/example.py:\n"
                "     Class Example L1-2\n"
            ),
            completed(
                "File dependencies for 'src/example.py':\n\n"
                "  Imports (0):\n"
                "    (none)\n\n"
                "  Imported by (0):\n"
                "    (none)\n"
            ),
        ]
    )

    result = adapter(runner).inspect(
        CodeIntelligenceQuery(
            CodeIntelligenceKind.DEPENDENCIES,
            subject,
            CodeIntelligenceSubjectKind.FILE,
        )
    )

    assert result.status is CodeIntelligenceStatus.OK
    assert result.relations == ()


def test_malformed_dependency_output_fails_closed():
    subject = "src/example.py"

    runner = Runner(
        [
            completed("infigraph 3.2.16\n"),
            completed(
                "Symbols in src/example.py:\n"
                "     Class Example L1-2\n"
            ),
            completed(
                "File dependencies for 'src/example.py':\n\n"
                "  Imports (1):\n"
                "    THIS IS NOT A DEPENDENCY\n\n"
                "  Imported by (0):\n"
                "    (none)\n"
            ),
        ]
    )

    result = adapter(runner).inspect(
        CodeIntelligenceQuery(
            CodeIntelligenceKind.DEPENDENCIES,
            subject,
            CodeIntelligenceSubjectKind.FILE,
        )
    )

    assert result.status is CodeIntelligenceStatus.UNAVAILABLE
    assert result.relations == ()
    assert "parse" in result.uncertainty.lower()


def test_tests_returns_direct_tested_by_relations_with_locations():
    from ai_foundation.code_intelligence import (
        CodeIntelligenceKind,
        CodeIntelligenceQuery,
        CodeIntelligenceStatus,
        CodeIntelligenceSubjectKind,
    )

    runner = Runner(
        [
            completed(stdout="infigraph 3.2.16\n"),
            completed(
                stdout=(
                    "(label:Symbol, 0:1, "
                    "{id:src/example.py::Example::run,name:run})\n"
                )
            ),
            completed(
                stdout=(
                    "tests/test_example.py::test_run | "
                    "tests/test_example.py | 12 | 18\n"
                    "tests/test_other.py::test_other | "
                    "tests/test_other.py | 31 | 35\n"
                )
            ),
        ]
    )
    subject = adapter(runner)

    result = subject.inspect(
        CodeIntelligenceQuery(
            CodeIntelligenceKind.TESTS,
            "src/example.py::Example::run",
            CodeIntelligenceSubjectKind.SYMBOL,
        )
    )

    assert result.status is CodeIntelligenceStatus.OK
    assert [
        (r.relation, r.target, r.file, r.line)
        for r in result.relations
    ] == [
        (
            "TESTED_BY",
            "tests/test_example.py::test_run",
            "tests/test_example.py",
            12,
        ),
        (
            "TESTED_BY",
            "tests/test_other.py::test_other",
            "tests/test_other.py",
            31,
        ),
    ]


def test_known_symbol_with_no_tested_by_edges_is_ok_empty():
    from ai_foundation.code_intelligence import (
        CodeIntelligenceKind,
        CodeIntelligenceQuery,
        CodeIntelligenceStatus,
        CodeIntelligenceSubjectKind,
    )

    runner = Runner(
        [
            completed(stdout="infigraph 3.2.16\n"),
            completed(
                stdout=(
                    "(label:Symbol, 0:1, "
                    "{id:src/example.py::Example::run,name:run})\n"
                )
            ),
            completed(stdout="(no results)\n"),
        ]
    )
    subject = adapter(runner)

    result = subject.inspect(
        CodeIntelligenceQuery(
            CodeIntelligenceKind.TESTS,
            "src/example.py::Example::run",
            CodeIntelligenceSubjectKind.SYMBOL,
        )
    )

    assert result.status is CodeIntelligenceStatus.OK
    assert result.relations == ()


def test_tests_requires_symbol_subject_before_backend_call():
    from ai_foundation.code_intelligence import (
        CodeIntelligenceKind,
        CodeIntelligenceQuery,
        CodeIntelligenceStatus,
        CodeIntelligenceSubjectKind,
    )

    runner = Runner([])
    subject = adapter(runner)

    result = subject.inspect(
        CodeIntelligenceQuery(
            CodeIntelligenceKind.TESTS,
            "src/example.py",
            CodeIntelligenceSubjectKind.FILE,
        )
    )

    assert result.status is CodeIntelligenceStatus.UNAVAILABLE
    assert result.relations == ()
    assert runner.calls == []


def test_malformed_tested_by_projection_fails_closed():
    from ai_foundation.code_intelligence import (
        CodeIntelligenceKind,
        CodeIntelligenceQuery,
        CodeIntelligenceStatus,
        CodeIntelligenceSubjectKind,
    )

    runner = Runner(
        [
            completed(stdout="infigraph 3.2.16\n"),
            completed(
                stdout=(
                    "(label:Symbol, 0:1, "
                    "{id:src/example.py::Example::run,name:run})\n"
                )
            ),
            completed(
                stdout=(
                    "tests/test_example.py::test_run | "
                    "tests/test_example.py | not-a-line | 18\n"
                )
            ),
        ]
    )
    subject = adapter(runner)

    result = subject.inspect(
        CodeIntelligenceQuery(
            CodeIntelligenceKind.TESTS,
            "src/example.py::Example::run",
            CodeIntelligenceSubjectKind.SYMBOL,
        )
    )

    assert result.status is CodeIntelligenceStatus.UNAVAILABLE
    assert result.relations == ()
    assert "parse" in result.uncertainty.lower()


def test_refresh_establishes_fresh_receipt_only_when_source_identity_is_stable(tmp_path):
    from ai_foundation.infigraph_adapter import InfigraphCodeIntelligence

    identities = iter(("source-a", "source-a"))

    def runner(args, **kwargs):
        command = list(args)
        if command[-1] == "--version":
            return completed(stdout="infigraph 3.2.16\n")
        if "index" in command:
            assert command[-2:] == ["--full", "--no-embed"]
            return completed(stdout="")
        raise AssertionError(command)

    backend = InfigraphCodeIntelligence(
        executable="infigraph",
        root=tmp_path,
        runner=runner,
        source_identity=lambda: next(identities),
    )

    receipt = backend.refresh()

    assert receipt.index_revision == "source-a"
    assert receipt.fresh is True


def test_refresh_rejects_receipt_when_source_changes_during_index(tmp_path):
    from ai_foundation.infigraph_adapter import InfigraphCodeIntelligence

    identities = iter(("source-before", "source-after"))

    def runner(args, **kwargs):
        command = list(args)
        if command[-1] == "--version":
            return completed(stdout="infigraph 3.2.16\n")
        if "index" in command:
            return completed(stdout="")
        raise AssertionError(command)

    backend = InfigraphCodeIntelligence(
        executable="infigraph",
        root=tmp_path,
        runner=runner,
        source_identity=lambda: next(identities),
    )

    receipt = backend.refresh()

    assert receipt.index_revision == ""
    assert receipt.fresh is False
    assert "changed during explicit refresh" in receipt.uncertainty


def test_inspect_is_fresh_only_while_current_source_matches_refresh_receipt(tmp_path):
    from ai_foundation.code_intelligence import (
        CodeIntelligenceKind,
        CodeIntelligenceQuery,
        CodeIntelligenceStatus,
        CodeIntelligenceSubjectKind,
    )
    from ai_foundation.infigraph_adapter import InfigraphCodeIntelligence

    current = {"identity": "source-a"}

    def identity():
        return current["identity"]

    def runner(args, **kwargs):
        command = list(args)

        if command[-1] == "--version":
            return completed(stdout="infigraph 3.2.16\n")

        if "index" in command:
            return completed(stdout="")

        if "query" in command:
            return completed(
                stdout=(
                    "(label:Symbol, 0:1, "
                    "{id:src/ai_foundation/compute_routing.py::"
                    "ComputeRouter::choose,name:choose})\n"
                )
            )

        if "find-refs" in command:
            return completed(
                stdout=(
                    "References to "
                    "'src/ai_foundation/compute_routing.py::"
                    "ComputeRouter::choose' (1 total):\n\n"
                    "  tests/test_compute_routing.py:7"
                    "     in test_route\n"
                )
            )

        raise AssertionError(command)

    backend = InfigraphCodeIntelligence(
        executable="infigraph",
        root=tmp_path,
        runner=runner,
        source_identity=identity,
    )

    receipt = backend.refresh()
    assert receipt.fresh is True

    query = CodeIntelligenceQuery(
        CodeIntelligenceKind.REFERENCES,
        "src/ai_foundation/compute_routing.py::ComputeRouter::choose",
        CodeIntelligenceSubjectKind.SYMBOL,
    )

    fresh_result = backend.inspect(query)

    assert fresh_result.status is CodeIntelligenceStatus.OK
    assert fresh_result.fresh is True
    assert fresh_result.index_revision == "source-a"

    current["identity"] = "source-b"

    stale_result = backend.inspect(query)

    assert stale_result.status is CodeIntelligenceStatus.OK
    assert stale_result.fresh is False
    assert stale_result.index_revision == "source-a"
    assert "source identity no longer matches explicit refresh" in stale_result.uncertainty


def test_failed_explicit_index_does_not_establish_fresh_receipt(tmp_path):
    from subprocess import CompletedProcess

    from ai_foundation.infigraph_adapter import InfigraphCodeIntelligence

    def runner(args, **kwargs):
        command = list(args)

        if command[-1] == "--version":
            return completed(stdout="infigraph 3.2.16\n")

        if "index" in command:
            return CompletedProcess(command, 1, stdout="", stderr="index failed")

        raise AssertionError(command)

    backend = InfigraphCodeIntelligence(
        executable="infigraph",
        root=tmp_path,
        runner=runner,
        source_identity=lambda: "source-a",
    )

    receipt = backend.refresh()

    assert receipt.index_revision == ""
    assert receipt.fresh is False
    assert "explicit refresh failed" in receipt.uncertainty


def test_git_source_identity_excludes_infigraph_backend_state_but_keeps_untracked_source(
    tmp_path,
):
    import subprocess

    from ai_foundation.infigraph_adapter import InfigraphCodeIntelligence

    subprocess.run(
        ["git", "init", "-q"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Identity Test"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "identity@invalid.local"],
        cwd=tmp_path,
        check=True,
    )

    source = tmp_path / "source.py"
    source.write_text("VALUE = 1\n")

    subprocess.run(
        ["git", "add", "source.py"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-qm", "baseline"],
        cwd=tmp_path,
        check=True,
    )

    backend = InfigraphCodeIntelligence(
        executable="infigraph",
        root=tmp_path,
    )

    baseline = backend.source_identity()

    state_dir = tmp_path / ".infigraph"
    state_dir.mkdir()
    (state_dir / "graph.db").write_bytes(b"backend-state-one")

    with_backend_state = backend.source_identity()

    (state_dir / "graph.db").write_bytes(b"backend-state-two")
    with_changed_backend_state = backend.source_identity()

    assert with_backend_state == baseline
    assert with_changed_backend_state == baseline

    untracked_source = tmp_path / "new-source.py"
    untracked_source.write_text("NEW_VALUE = 2\n")

    with_untracked_source = backend.source_identity()

    assert with_untracked_source != baseline

def test_every_infigraph_subprocess_disables_implicit_watcher(tmp_path, monkeypatch):
    from ai_foundation.infigraph_adapter import InfigraphCodeIntelligence

    monkeypatch.setenv("FOUNDATION_PARENT_ENV_PROBE", "preserved")

    calls = []

    def runner(args, **kwargs):
        calls.append((list(args), kwargs))
        return completed(stdout="infigraph 3.2.16\n")

    backend = InfigraphCodeIntelligence(
        executable="infigraph",
        root=tmp_path,
        runner=runner,
        source_identity=lambda: "source-a",
    )

    process = backend._run("--version")

    assert process.returncode == 0
    assert len(calls) == 1

    command, kwargs = calls[0]

    assert command == ["infigraph", "--version"]
    assert kwargs["env"]["INFIGRAPH_NO_WATCH"] == "1"
    assert kwargs["env"]["FOUNDATION_PARENT_ENV_PROBE"] == "preserved"
def test_calls_require_symbol_subject_without_backend_call():
    runner = Runner([])

    result = adapter(runner).inspect(
        CodeIntelligenceQuery(
            CodeIntelligenceKind.CALLS,
            "src/ai_foundation/safe_change.py",
            CodeIntelligenceSubjectKind.FILE,
        )
    )

    assert result.status is CodeIntelligenceStatus.UNAVAILABLE
    assert "SYMBOL" in result.uncertainty
    assert runner.calls == []


def test_calls_return_physically_observed_resolved_callees():
    subject = (
        "src/ai_foundation/safe_change.py"
        "::SafeChangeCoordinator::apply"
    )

    runner = Runner(
        [
            completed("infigraph 3.2.16\n"),
            completed(
                "(label:Symbol, 0:1, "
                "{id:src/ai_foundation/safe_change.py"
                "::SafeChangeCoordinator::apply,name:apply})\n"
            ),
            completed(
                "src/ai_foundation/development_context.py"
                "::DevelopmentContextCompiler::compile"
                " | src/ai_foundation/development_context.py | 60 | 189\n"
                "src/ai_foundation/coding.py"
                "::CodingSpecialist::apply_verified_change"
                " | src/ai_foundation/coding.py | 23 | 47\n"
                "src/ai_foundation/safe_change.py"
                "::SafeChangeCoordinator::_target_is_bounded"
                " | src/ai_foundation/safe_change.py | 129 | 144\n"
            ),
        ]
    )

    result = adapter(runner).inspect(
        CodeIntelligenceQuery(
            CodeIntelligenceKind.CALLS,
            subject,
            CodeIntelligenceSubjectKind.SYMBOL,
        )
    )

    assert result.status is CodeIntelligenceStatus.OK

    assert [
        (
            relation.target,
            relation.relation,
            relation.file,
            relation.line,
        )
        for relation in result.relations
    ] == [
        (
            "src/ai_foundation/development_context.py"
            "::DevelopmentContextCompiler::compile",
            "CALLS",
            "src/ai_foundation/development_context.py",
            60,
        ),
        (
            "src/ai_foundation/coding.py"
            "::CodingSpecialist::apply_verified_change",
            "CALLS",
            "src/ai_foundation/coding.py",
            23,
        ),
        (
            "src/ai_foundation/safe_change.py"
            "::SafeChangeCoordinator::_target_is_bounded",
            "CALLS",
            "src/ai_foundation/safe_change.py",
            129,
        ),
    ]

    assert "remain UNKNOWN" in result.uncertainty

    assert runner.calls[2][0] == [
        "/opt/test/infigraph",
        "query",
        (
            "MATCH (n)-[:CALLS]->(t) "
            "WHERE n.id = "
            "'src/ai_foundation/safe_change.py"
            "::SafeChangeCoordinator::apply' "
            "RETURN t.id,t.file,t.start_line,t.end_line"
        ),
    ]


def test_known_subject_with_no_resolved_calls_is_empty_but_not_complete():
    subject = "src/x.py::f"

    runner = Runner(
        [
            completed("infigraph 3.2.16\n"),
            completed(
                "(label:Symbol, 0:1, "
                "{id:src/x.py::f,name:f})\n"
            ),
            completed("(no results)\n"),
        ]
    )

    result = adapter(runner).inspect(
        CodeIntelligenceQuery(
            CodeIntelligenceKind.CALLS,
            subject,
            CodeIntelligenceSubjectKind.SYMBOL,
        )
    )

    assert result.status is CodeIntelligenceStatus.OK
    assert result.relations == ()
    assert "remain UNKNOWN" in result.uncertainty


def test_malformed_calls_output_fails_closed():
    subject = "src/x.py::f"

    runner = Runner(
        [
            completed("infigraph 3.2.16\n"),
            completed(
                "(label:Symbol, 0:1, "
                "{id:src/x.py::f,name:f})\n"
            ),
            completed(
                "src/y.py::g | src/y.py | not-a-line | 20\n"
            ),
        ]
    )

    result = adapter(runner).inspect(
        CodeIntelligenceQuery(
            CodeIntelligenceKind.CALLS,
            subject,
            CodeIntelligenceSubjectKind.SYMBOL,
        )
    )

    assert result.status is CodeIntelligenceStatus.UNAVAILABLE
    assert result.relations == ()
    assert "parse" in result.uncertainty.lower()


def test_inventory_covers_multiple_languages_and_marks_unindexed_native_artifacts():
    runner = Runner([
        completed("infigraph 3.2.16\n"),
        completed(
            "Available languages:\n"
            "  Python (.py, .pyi) [tree-sitter]\n"
            "  TypeScript (.ts, .tsx) [tree-sitter]\n"
            "  Shell (.sh, .bash) [tree-sitter]\n"
        ),
        completed(
            "src/a.py | Python | 1\n"
            "src/a.ts | TypeScript | 1\n"
            "scripts/check.sh | Shell | 1\n"
            "config/settings.json | JSON | 0\n"
        ),
        completed(
            "src/a.py::main | Function | src/a.py | 1\n"
            "src/a.ts::start | Function | src/a.ts | 2\n"
            "scripts/check.sh::main | Function | scripts/check.sh | 1\n"
        ),
    ])
    source_paths = (
        "src/a.py",
        "src/a.ts",
        "scripts/check.sh",
        "config/settings.json",
        "native/libfoundation.dylib",
        "src/native/unknown.something",
        "docs/architecture.md",
    )
    backend = InfigraphCodeIntelligence(
        executable=Path("/opt/test/infigraph"),
        root=Path("/repo"),
        runner=runner,
        source_identity=lambda: "revision",
        source_files=lambda: source_paths,
    )
    backend._refresh_revision = "revision"

    result = backend.inspect(CodeIntelligenceQuery(
        CodeIntelligenceKind.INVENTORY,
        ".",
        CodeIntelligenceSubjectKind.FILE,
    ))

    assert result.status is CodeIntelligenceStatus.UNKNOWN
    assert result.fresh is True
    assert result.completeness.expected_files == 6
    assert result.completeness.analyzed_files == 4
    assert result.completeness.failed_files == (
        "native/libfoundation.dylib",
        "src/native/unknown.something",
    )
    assert result.completeness.unresolved_observations == 2
    # MODULE denotes a path represented by the backend index; unindexed
    # artifacts remain FILE + UNINDEXED_FILE evidence, not fabricated modules.
    assert {item.file for item in result.relations if item.relation == "MODULE"} == {
        "src/a.py", "src/a.ts", "scripts/check.sh", "config/settings.json",
    }
    assert {item.file for item in result.relations if item.relation == "UNINDEXED_FILE"} == {
        "native/libfoundation.dylib", "src/native/unknown.something",
    }
    assert {item.file for item in result.relations if item.relation == "FUNCTION"} == {
        "src/a.py", "src/a.ts", "scripts/check.sh",
    }
    assert "2 relevant repository files" in result.uncertainty
    assert runner.calls[1][0] == ["/opt/test/infigraph", "languages"]
    assert runner.calls[2][0] == [
        "/opt/test/infigraph",
        "query",
        "MATCH (f:File) RETURN f.path,f.language,f.symbol_count",
    ]
    assert runner.calls[3][0] == [
        "/opt/test/infigraph",
        "query",
        "MATCH (s:Symbol) RETURN s.id,s.kind,s.file,s.start_line",
    ]


def test_inventory_preserves_symbol_id_with_separator_from_frozen_478():
    """Infigraph IDs may contain ' | '; parse the last three columns only."""
    runner = Runner([
        completed("infigraph 3.2.16\n"),
        completed("Available languages:\n  Python (.py) [tree-sitter]\n"),
        completed("src/a.py | Python | 1\n"),
        completed("src/a.py::foo | quoted | Function | src/a.py | 7\n"),
    ])
    backend = InfigraphCodeIntelligence(
        executable=Path("/opt/test/infigraph"),
        root=Path("/repo"),
        runner=runner,
        source_identity=lambda: "revision",
        source_files=lambda: ("src/a.py",),
    )
    backend._refresh_revision = "revision"
    result = backend.inspect(CodeIntelligenceQuery(
        CodeIntelligenceKind.INVENTORY, ".", CodeIntelligenceSubjectKind.FILE,
    ))
    assert result.status is CodeIntelligenceStatus.OK
    assert result.completeness.expected_files == 1
    assert result.completeness.analyzed_files == 1
    assert any(
        item.target == "src/a.py::foo | quoted" and item.file == "src/a.py"
        for item in result.relations if item.relation == "FUNCTION"
    )


def test_inventory_malformed_rows_report_structure_without_source_disclosure():
    sample = (
        "symbol-A | FUNCTION | source/a.py | 7\n"
        "symbol-A | METHOD | source/a.py | 8\n"
        "bad | value | count\n"
        "symbol-C | CLASS | ../private.txt | bad\n"
    )
    assert InfigraphCodeIntelligence._parse_symbol_inventory(sample) is None
    reason = InfigraphCodeIntelligence._symbol_inventory_failure_reason(sample)
    for expected in ("column_mismatch=1", "invalid_path=1",
                     "invalid_line=1", "duplicate_id=1"):
        assert expected in reason
    for private in ("source/a.py", "private.txt", "symbol-A"):
        assert private not in reason


def test_inventory_rejects_malformed_symbol_rows_without_partial_success():
    runner = Runner([
        completed("infigraph 3.2.16\n"),
        completed(
            "Available languages:\n"
            "  Python (.py) [tree-sitter]\n"
        ),
        completed("src/a.py | Python | 1\n"),
        completed("src/a.py::main | Function | src/a.py | not-a-line\n"),
    ])
    backend = InfigraphCodeIntelligence(
        executable=Path("/opt/test/infigraph"),
        root=Path("/repo"),
        runner=runner,
        source_identity=lambda: "revision",
        source_files=lambda: ("src/a.py",),
    )
    backend._refresh_revision = "revision"

    result = backend.inspect(CodeIntelligenceQuery(
        CodeIntelligenceKind.INVENTORY,
        ".",
        CodeIntelligenceSubjectKind.FILE,
    ))

    assert result.status is CodeIntelligenceStatus.UNAVAILABLE
    assert result.relations == ()
    assert "parse" in result.uncertainty.lower()


def test_inventory_requires_repository_root_file_subject():
    runner = Runner([])
    result = adapter(runner).inspect(CodeIntelligenceQuery(
        CodeIntelligenceKind.INVENTORY,
        "src/a.py",
        CodeIntelligenceSubjectKind.FILE,
    ))
    assert result.status is CodeIntelligenceStatus.UNAVAILABLE
    assert runner.calls == []


def test_inventory_includes_common_dependency_manifest_variants():
    runner = Runner([
        completed("infigraph 3.2.16\n"),
        completed("Available languages:\n  Python (.py) [tree-sitter]\n"),
        completed(
            "src/a.py | Python | 0\n"
            "requirements-dev.txt | Text | 0\n"
            "constraints.txt | Text | 0\n"
        ),
        completed(""),
    ])
    source_paths = ("src/a.py", "requirements-dev.txt", "constraints.txt")
    backend = InfigraphCodeIntelligence(
        executable=Path("/opt/test/infigraph"),
        root=Path("/repo"),
        runner=runner,
        source_identity=lambda: "revision",
        source_files=lambda: source_paths,
    )
    backend._refresh_revision = "revision"

    result = backend.inspect(CodeIntelligenceQuery(
        CodeIntelligenceKind.INVENTORY,
        ".",
        CodeIntelligenceSubjectKind.FILE,
    ))

    assert result.status is CodeIntelligenceStatus.OK
    assert result.completeness.expected_files == 3
    assert result.completeness.analyzed_files == 3
    assert result.completeness.failed_files == ()
