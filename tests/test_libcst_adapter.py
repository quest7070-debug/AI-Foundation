from pathlib import Path

from ai_foundation.code_intelligence import (
    CodeIntelligenceKind,
    CodeIntelligenceQuery,
    CodeIntelligenceStatus,
    CodeIntelligenceSubjectKind,
)
from ai_foundation.libcst_adapter import LibCSTCodeIntelligence


def build_repo(tmp_path: Path) -> Path:
    source = tmp_path / "src" / "ai_foundation"
    source.mkdir(parents=True)

    (source / "example.py").write_text(
        "def example(value):\n"
        "    normalized = value.strip()\n"
        "    candidate = normalized\n"
        "    return candidate\n"
    )

    return tmp_path


def inspect(tmp_path, kind, subject="src/ai_foundation/example.py"):
    adapter = LibCSTCodeIntelligence(root=build_repo(tmp_path))

    return adapter.inspect(
        CodeIntelligenceQuery(
            kind=kind,
            subject=subject,
            subject_kind=CodeIntelligenceSubjectKind.FILE,
        )
    )


def test_scoped_variables_are_source_derived(tmp_path):
    result = inspect(
        tmp_path,
        CodeIntelligenceKind.SCOPED_VARIABLES,
    )

    assert result.status is CodeIntelligenceStatus.OK
    assert result.backend == "libcst"
    assert result.backend_version == "1.9.0"
    assert result.fresh is True
    assert result.index_revision

    targets = {relation.target for relation in result.relations}

    assert any("::FunctionScope::value@" in value for value in targets)
    assert any("::FunctionScope::normalized@" in value for value in targets)
    assert any("::FunctionScope::candidate@" in value for value in targets)


def test_reads_link_back_to_scoped_assignment(tmp_path):
    result = inspect(
        tmp_path,
        CodeIntelligenceKind.READS,
    )

    assert result.status is CodeIntelligenceStatus.OK

    reads = {
        (relation.target, relation.relation, relation.line)
        for relation in result.relations
    }

    assert any(
        "::FunctionScope::normalized@" in target
        and relation == "READ"
        and line == 3
        for target, relation, line in reads
    )

    assert any(
        "::FunctionScope::candidate@" in target
        and relation == "READ"
        and line == 4
        for target, relation, line in reads
    )


def test_writes_are_assignment_sites(tmp_path):
    result = inspect(
        tmp_path,
        CodeIntelligenceKind.WRITES,
    )

    writes = {
        (relation.target, relation.line)
        for relation in result.relations
    }

    assert any(
        "::FunctionScope::normalized@" in target
        and line == 2
        for target, line in writes
    )

    assert any(
        "::FunctionScope::candidate@" in target
        and line == 3
        for target, line in writes
    )


def test_repository_scope_is_supported(tmp_path):
    root = build_repo(tmp_path)

    second = root / "src" / "ai_foundation" / "second.py"
    second.write_text(
        "def second():\n"
        "    observed = 1\n"
        "    return observed\n"
    )

    adapter = LibCSTCodeIntelligence(root=root)

    result = adapter.inspect(
        CodeIntelligenceQuery(
            kind=CodeIntelligenceKind.SCOPED_VARIABLES,
            subject=".",
            subject_kind=CodeIntelligenceSubjectKind.FILE,
        )
    )

    assert result.status is CodeIntelligenceStatus.OK

    files = {relation.file for relation in result.relations}

    assert files == {
        "src/ai_foundation/example.py",
        "src/ai_foundation/second.py",
    }


def test_path_escape_fails_closed(tmp_path):
    root = build_repo(tmp_path)

    adapter = LibCSTCodeIntelligence(root=root)

    result = adapter.inspect(
        CodeIntelligenceQuery(
            kind=CodeIntelligenceKind.READS,
            subject="../outside.py",
            subject_kind=CodeIntelligenceSubjectKind.FILE,
        )
    )

    assert result.status is CodeIntelligenceStatus.UNAVAILABLE
    assert result.fresh is False
    assert "escapes" in result.uncertainty


def test_unowned_query_kind_is_unavailable(tmp_path):
    root = build_repo(tmp_path)

    adapter = LibCSTCodeIntelligence(root=root)

    result = adapter.inspect(
        CodeIntelligenceQuery(
            kind=CodeIntelligenceKind.TESTS,
            subject="src/ai_foundation/example.py",
            subject_kind=CodeIntelligenceSubjectKind.FILE,
        )
    )

    assert result.status is CodeIntelligenceStatus.UNAVAILABLE
    assert "not implemented" in result.uncertainty


def test_repository_inventory_is_complete_and_semantically_classified(
    tmp_path,
):
    root = build_repo(tmp_path)

    source = root / "src" / "ai_foundation" / "inventory.py"

    source.write_text(
        "from typing import Protocol\n"
        "\n"
        "MODULE_CONST = 1\n"
        "module_state = 2\n"
        "\n"
        "class Port(Protocol):\n"
        "    def run(self): ...\n"
        "\n"
        "class Service:\n"
        "    CLASS_CONST = 3\n"
        "    state = 4\n"
        "\n"
        "    def method(self, value):\n"
        "        local = value\n"
        "        local = value + 1\n"
        "\n"
        "        def nested():\n"
        "            nested_local = local\n"
        "            return nested_local\n"
        "\n"
        "        return nested()\n"
    )

    adapter = LibCSTCodeIntelligence(root=root)

    result = adapter.inspect(
        CodeIntelligenceQuery(
            kind=CodeIntelligenceKind.INVENTORY,
            subject=".",
            subject_kind=CodeIntelligenceSubjectKind.FILE,
        )
    )

    assert result.status is CodeIntelligenceStatus.OK
    assert result.fresh is True
    assert result.completeness is not None
    assert result.completeness.complete is True
    assert result.completeness.expected_files == 2
    assert result.completeness.analyzed_files == 2
    assert result.completeness.failed_files == ()
    assert result.completeness.unresolved_observations == 0

    by_relation = {}

    for relation in result.relations:
        by_relation.setdefault(relation.relation, []).append(relation)

    assert len(by_relation["MODULE"]) == 2
    assert len(by_relation["CLASS"]) == 2
    assert len(by_relation["INTERFACE"]) == 1
    assert len(by_relation["METHOD"]) == 2

    # example() plus method-local nested().
    assert len(by_relation["FUNCTION"]) == 2

    assert len(by_relation["MODULE_CONSTANT"]) == 1
    assert len(by_relation["MODULE_VARIABLE"]) == 1
    assert len(by_relation["CLASS_CONSTANT"]) == 1
    assert len(by_relation["CLASS_STATE"]) == 1

    # Reassignment of local is one logical scoped variable.
    local_inventory = [
        item
        for item in by_relation["SCOPED_VARIABLE"]
        if "::local@" in item.target
    ]

    assert len(local_inventory) == 1


def test_repository_inventory_reports_partial_parse_without_silent_omission(
    tmp_path,
):
    root = build_repo(tmp_path)

    broken = root / "src" / "ai_foundation" / "broken.py"
    broken.write_text("def broken(:\n")

    adapter = LibCSTCodeIntelligence(root=root)

    result = adapter.inspect(
        CodeIntelligenceQuery(
            kind=CodeIntelligenceKind.INVENTORY,
            subject=".",
            subject_kind=CodeIntelligenceSubjectKind.FILE,
        )
    )

    assert result.status is CodeIntelligenceStatus.UNKNOWN
    assert result.fresh is True
    assert result.completeness is not None
    assert result.completeness.complete is False
    assert result.completeness.expected_files == 2
    assert result.completeness.analyzed_files == 1
    assert len(result.completeness.failed_files) == 1
    assert "broken.py" in result.completeness.failed_files[0]
    assert "incomplete" in result.uncertainty


def test_repository_inventory_is_deterministic_for_same_source_snapshot(
    tmp_path,
):
    root = build_repo(tmp_path)

    source = root / "src" / "ai_foundation" / "deterministic.py"

    source.write_text(
        "CONST = 1\n"
        "\n"
        "class Service:\n"
        "    STATE = 2\n"
        "\n"
        "    def run(self, value):\n"
        "        observed = value\n"
        "        return observed\n"
    )

    adapter = LibCSTCodeIntelligence(root=root)

    query = CodeIntelligenceQuery(
        kind=CodeIntelligenceKind.INVENTORY,
        subject=".",
        subject_kind=CodeIntelligenceSubjectKind.FILE,
    )

    first = adapter.inspect(query)
    second = adapter.inspect(query)

    assert first.status is CodeIntelligenceStatus.OK
    assert second.status is CodeIntelligenceStatus.OK

    assert first.index_revision == second.index_revision
    assert first.relations == second.relations
    assert first.completeness == second.completeness

    assert first.completeness is not None
    assert first.completeness.complete is True

def test_read_write_results_publish_completeness_and_scope_boundary(
    tmp_path,
):
    root = build_repo(tmp_path)
    adapter = LibCSTCodeIntelligence(root=root)

    expectations = (
        (
            CodeIntelligenceKind.READS,
            "attribute/subscript target semantics",
        ),
        (
            CodeIntelligenceKind.WRITES,
            "attribute/subscript mutation targets",
        ),
    )

    for kind, boundary in expectations:
        result = adapter.inspect(
            CodeIntelligenceQuery(
                kind=kind,
                subject=".",
                subject_kind=CodeIntelligenceSubjectKind.FILE,
            )
        )

        assert result.status is CodeIntelligenceStatus.OK
        assert result.fresh is True
        assert result.completeness is not None
        assert result.completeness.complete is True
        assert result.completeness.expected_files == 1
        assert result.completeness.analyzed_files == 1
        assert result.completeness.failed_files == ()
        assert result.completeness.unresolved_observations == 0
        assert boundary in result.uncertainty
        assert "remain UNKNOWN" in result.uncertainty


def test_repository_inventory_includes_python_stub_files(tmp_path):
    root = build_repo(tmp_path)
    stub = root / "src" / "ai_foundation" / "contracts.pyi"
    stub.write_text(
        "from typing import Protocol\n"
        "\n"
        "class Store(Protocol):\n"
        "    def read(self, key: str) -> str: ...\n"
    )
    adapter = LibCSTCodeIntelligence(root=root)

    result = adapter.inspect(CodeIntelligenceQuery(
        kind=CodeIntelligenceKind.INVENTORY,
        subject=".",
        subject_kind=CodeIntelligenceSubjectKind.FILE,
    ))

    assert result.status is CodeIntelligenceStatus.OK
    assert result.completeness is not None
    assert result.completeness.complete is True
    assert result.completeness.expected_files == 2
    assert result.completeness.analyzed_files == 2
    assert any(
        relation.file.endswith("contracts.pyi")
        and relation.relation == "MODULE"
        for relation in result.relations
    )
    assert any(
        relation.file.endswith("contracts.pyi")
        and relation.relation == "METHOD"
        for relation in result.relations
    )


def test_repository_inventory_is_complete_when_no_python_source_exists(tmp_path):
    root = tmp_path / "repo"
    (root / "src" / "ai_foundation").mkdir(parents=True)
    result = LibCSTCodeIntelligence(root=root).inspect(CodeIntelligenceQuery(
        kind=CodeIntelligenceKind.INVENTORY,
        subject=".",
        subject_kind=CodeIntelligenceSubjectKind.FILE,
    ))

    assert result.status is CodeIntelligenceStatus.OK
    assert result.fresh is True
    assert result.completeness is not None
    assert result.completeness.complete is True
    assert result.completeness.expected_files == 0
    assert result.completeness.analyzed_files == 0
    assert result.relations == ()
