from dataclasses import replace
import json

import pytest

from ai_foundation.code_intelligence import (
    CodeIntelligenceCompleteness, CodeIntelligenceKind,
    CodeIntelligenceRelation, CodeIntelligenceResult, CodeIntelligenceStatus,
    CodeIntelligenceSubjectKind,
)
from ai_foundation.explainability import ExplainabilityClosure, ExplainabilityGate
from ai_foundation.semantic_declarations import parse_semantic_declarations
from ai_foundation.semantic_linker import (
    FoundationSemanticLinker, SemanticClassification, SemanticCoverageRecord,
    SemanticCoverageResult,
)


SOURCE = "src/ai_foundation/example.py"
SUBJECT = SOURCE + "::FUNCTION::example@1:0"
CANON = "docs/owner.md"
EVIDENCE = "tests/test_example.py"


def declaration():
    return dict(
        source=SOURCE, subject=SUBJECT, subject_kind="SYMBOL", claim_kind="INVARIANT",
        purpose="Return the bounded input.", ownership="Example owner",
        rationale="NOT_APPLICABLE", failure_semantics="Failure is explicit.",
        side_effects="NONE", change_impact="Reverify the bounded result.",
        evidence=[EVIDENCE],
    )


def fence(data):
    return "```foundation-semantic\n" + json.dumps(data) + "\n```\n"


@pytest.fixture
def repo(tmp_path):
    for path, text in (
        (SOURCE, "def example(value):\n    return value\n"),
        (EVIDENCE, "def test_example():\n    assert True\n"),
        (CANON, "# Example obligation\nReturn the bounded input.\n" + fence(declaration())),
    ):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    return tmp_path


def inventory():
    return SemanticCoverageResult(
        status=CodeIntelligenceStatus.OK, fresh=True, index_revision="source-1",
        completeness=CodeIntelligenceCompleteness(1, 1), records=(
            SemanticCoverageRecord("MODULE", SOURCE, SOURCE, 1),
            SemanticCoverageRecord("FUNCTION", SUBJECT, SOURCE, 1),
        ),
    )


def parse(repo, *, coverage=None, paths=(CANON,)):
    return parse_semantic_declarations(repo, paths, coverage or inventory())


def test_explicit_fields_and_canonical_identity_are_preserved(repo):
    result = parse(repo)
    assert result == parse(repo)
    assert result.errors == ()
    link, = result.links
    assert link.code_subject == SUBJECT
    assert link.subject_kind is CodeIntelligenceSubjectKind.SYMBOL
    assert link.canonical_reference.source_path == CANON
    assert link.canonical_reference.locator == "L3-L5"
    assert link.canonical_reference.claim_kind == "INVARIANT"
    assert link.rationale == "NOT_APPLICABLE"
    assert link.side_effects == "NONE"
    assert link.evidence_refs == (EVIDENCE,)
    assert not result.authoritative


@pytest.mark.parametrize("field", tuple(declaration()))
def test_no_missing_field_is_inferred(repo, field):
    data = declaration()
    del data[field]
    (repo / CANON).write_text(fence(data))
    assert parse(repo).errors
    assert parse(repo).links == ()


@pytest.mark.parametrize("field,value", [
    ("purpose", ""), ("ownership", "   "), ("rationale", None),
    ("side_effects", False), ("subject_kind", "symbol"),
    ("source", "./" + SOURCE), ("source", "../example.py"),
    ("source", "example.py"), ("source", "/tmp/example.py"),
    ("subject", "example"), ("subject", SUBJECT + " "),
    ("subject_kind", "FILE"), ("claim_kind", " INVARIANT"),
    ("evidence", EVIDENCE), ("evidence", [1]),
    ("evidence", ["tests/absent.py"]), ("evidence", [EVIDENCE, EVIDENCE]),
])
def test_malformed_and_nonexact_identity_fail_closed(repo, field, value):
    data = declaration()
    data[field] = value
    (repo / CANON).write_text(fence(data))
    result = parse(repo)
    assert result.links == ()
    assert result.errors == parse(repo).errors
    assert result.errors


@pytest.mark.parametrize("body", [
    "not json", "[]", '{"source": "a", "source": "b"}',
])
def test_invalid_json_and_duplicate_keys_fail_closed(repo, body):
    (repo / CANON).write_text("```foundation-semantic\n" + body + "\n```\n")
    assert parse(repo).errors
    assert not parse(repo).links


@pytest.mark.parametrize("conflicting", [False, True])
def test_duplicate_obligations_across_canon_files_block_entire_batch(repo, conflicting):
    data = declaration()
    if conflicting:
        data["purpose"] = "Contradictory purpose"
    (repo / "docs/other.md").write_text(fence(data))
    result = parse(repo, paths=(CANON, "docs/other.md"))
    assert not result.links
    assert any("duplicate semantic obligation" in error for error in result.errors)


@pytest.mark.parametrize("separate_files", [False, True])
def test_duplicate_identity_with_different_claim_kind_blocks_entire_batch(repo, separate_files):
    other_claim = declaration()
    other_claim["claim_kind"] = "OTHER_INVARIANT"
    if separate_files:
        (repo / "docs/other.md").write_text(fence(other_claim))
        paths = (CANON, "docs/other.md")
    else:
        (repo / CANON).write_text(fence(declaration()) + fence(other_claim))
        paths = (CANON,)
    result = parse(repo, paths=paths)
    assert not result.links
    assert any("duplicate semantic obligation" in error for error in result.errors)


def test_source_file_and_subject_must_match_same_inventory_record(repo):
    other = "src/ai_foundation/other.py"
    (repo / other).write_text("pass\n")
    data = declaration()
    data["source"] = other
    (repo / CANON).write_text(fence(data))
    assert parse(repo).errors


@pytest.mark.parametrize("coverage", [
    replace(inventory(), fresh=False),
    replace(inventory(), completeness=None),
    replace(inventory(), completeness=CodeIntelligenceCompleteness(2, 1)),
    replace(inventory(), status=CodeIntelligenceStatus.UNAVAILABLE),
])
def test_stale_or_incomplete_inventory_blocks_declarations(repo, coverage):
    assert parse(repo, coverage=coverage).errors
    assert not parse(repo, coverage=coverage).links


def test_plain_paths_prose_and_nested_examples_never_mint_semantics(repo):
    (repo / CANON).write_text(
        f"# Ownership\nPurpose of `{SOURCE}` is obvious.\n"
        + "````markdown\n" + fence(declaration()) + "````\n"
        + "```json\n" + json.dumps(declaration()) + "\n```\n"
    )
    assert parse(repo).errors == ()
    assert parse(repo).links == ()
    assert parse(repo, paths=()).links == ()


def test_unclosed_or_invalid_fence_blocks(repo):
    (repo / CANON).write_text(fence(declaration()).removesuffix("```\n"))
    assert "unclosed" in parse(repo).errors[0]
    (repo / CANON).write_text(fence(declaration()).replace("foundation-semantic", "foundation-semantic json"))
    assert parse(repo).errors


def test_missing_or_escaping_canon_is_blocked(repo, tmp_path):
    assert parse(repo, paths=("docs/missing.md",)).errors
    outside = tmp_path.parent / (tmp_path.name + "-outside.md")
    outside.write_text(fence(declaration()))
    (repo / "docs/escape.md").symlink_to(outside)
    assert parse(repo, paths=("docs/escape.md",)).errors


def test_file_identity_and_empty_evidence_are_explicitly_supported(repo):
    data = declaration()
    data.update(subject=SOURCE, subject_kind="FILE", evidence=[])
    (repo / CANON).write_text(fence(data).replace("```", "~~~"))
    result = parse(repo)
    assert result.errors == ()
    assert result.links[0].evidence_refs == ()


class Backend:
    def __init__(self, *, tests=True, fresh=True):
        self.tests = tests
        self.fresh = fresh

    def inspect(self, query):
        relations = ()
        completeness = None
        if query.kind is CodeIntelligenceKind.INVENTORY:
            relations = tuple(CodeIntelligenceRelation(
                item.code_subject, item.inventory_kind, item.file, item.line,
            ) for item in inventory().records)
            completeness = inventory().completeness
        elif query.kind is CodeIntelligenceKind.TESTS and self.tests:
            relations = (CodeIntelligenceRelation(EVIDENCE, "TESTED_BY", EVIDENCE, 1),)
        return CodeIntelligenceResult(
            kind=query.kind, subject=query.subject, status=CodeIntelligenceStatus.OK,
            relations=relations, backend="fixture", backend_version="1",
            index_revision="revision-1", fresh=self.fresh, completeness=completeness,
        )


def engine(**kwargs):
    return ExplainabilityClosure(FoundationSemanticLinker(Backend(**kwargs)))


def rebuild(repo, closure):
    return closure.rebuild_repository_with_canon(repo, canonical_paths=(CANON,))


def test_existing_explainability_preflight_and_drift_receive_parser_evidence(repo):
    closure = engine()
    before = rebuild(repo, closure)
    assert before.traces[0].classification is SemanticClassification.MAPPED
    assert closure.repository_preflight(before, (SUBJECT,)).gate is ExplainabilityGate.READY
    (repo / EVIDENCE).write_text("# changed independent evidence\n")
    after = rebuild(repo, closure)
    assert before.revision != after.revision
    (repo / CANON).write_text("# Obligation removed\n")
    removed = rebuild(repo, closure)
    assert closure.repository_preflight(removed, (SUBJECT,)).gate is ExplainabilityGate.BLOCKED
    assert closure.drift_check(before, removed, (SUBJECT,)).gate is ExplainabilityGate.BLOCKED


@pytest.mark.parametrize("kwargs", [{"tests": False}, {"fresh": False}])
def test_declaration_alone_cannot_map_or_pass_preflight(repo, kwargs):
    closure = engine(**kwargs)
    snapshot = rebuild(repo, closure)
    assert all(t.classification is not SemanticClassification.MAPPED for t in snapshot.traces)
    assert closure.repository_preflight(snapshot, (SUBJECT,)).gate is ExplainabilityGate.BLOCKED


def test_parser_errors_are_preserved_in_snapshot_and_block_preflight(repo):
    (repo / CANON).write_text(fence(declaration()) + fence({}))
    closure = engine()
    snapshot = rebuild(repo, closure)
    assert snapshot.conflicts
    assert not snapshot.fresh
    assert not snapshot.traces
    assert closure.repository_preflight(snapshot, (SUBJECT,)).gate is ExplainabilityGate.BLOCKED


def test_real_libcst_inventory_provides_exact_identity_without_semantic_inference(repo):
    from ai_foundation.libcst_adapter import LibCSTCodeIntelligence

    coverage = FoundationSemanticLinker(LibCSTCodeIntelligence(root=repo)).repository_coverage()
    result = parse(repo, coverage=coverage)
    assert result.errors == ()
    assert result.links[0].code_subject == SUBJECT
