from dataclasses import dataclass

from ai_foundation.coding import CodingResult
from ai_foundation.development_context import DevelopmentContext, DevelopmentRequest
from ai_foundation.safe_change import SafeChangeCoordinator


def context(
    *,
    fresh=True,
    uncertainties=(),
    code_subjects=("src/ai_foundation/example.py::Example",),
):
    return DevelopmentContext(
        request="change example",
        canonical_references=(),
        code_subjects=code_subjects,
        affected_tests=("tests/test_example.py",),
        impacts=(),
        dependencies=(),
        evidence_refs=("test:test_example",),
        index_revisions=("revision-1",),
        fresh=fresh,
        uncertainties=uncertainties,
        authoritative=False,
    )


@dataclass
class Compiler:
    value: DevelopmentContext
    calls: int = 0

    def compile(self, request):
        self.calls += 1
        return self.value


@dataclass
class Specialist:
    result: CodingResult
    calls: int = 0
    seen: tuple | None = None

    def apply_verified_change(self, target, content):
        self.calls += 1
        self.seen = (target, content)
        return self.result


def request():
    # Coordinator treats the compiler as the authority for derived context;
    # these unit tests intentionally isolate orchestration from linker details.
    return DevelopmentRequest("change example", ())


def test_verified_context_delegates_once_to_existing_specialist():
    c = Compiler(context())
    s = Specialist(CodingResult("old", "before=pass; after=pass", "VERIFIED_COMPLETE"))

    result = SafeChangeCoordinator(c, s).apply(
        request(),
        "src/ai_foundation/example.py",
        "new",
    )

    assert result.status == "VERIFIED"
    assert result.mutated
    assert c.calls == 1
    assert s.calls == 1
    assert s.seen == ("src/ai_foundation/example.py", "new")


def test_stale_context_fails_closed_before_write():
    c = Compiler(context(fresh=False))
    s = Specialist(CodingResult("old", "unused", "VERIFIED_COMPLETE"))

    result = SafeChangeCoordinator(c, s).apply(
        request(),
        "src/ai_foundation/example.py",
        "new",
    )

    assert result.status == "BLOCKED"
    assert result.reason == "development context is stale"
    assert not result.mutated
    assert s.calls == 0


def test_uncertain_context_fails_closed_before_write():
    c = Compiler(context(uncertainties=("backend unavailable",)))
    s = Specialist(CodingResult("old", "unused", "VERIFIED_COMPLETE"))

    result = SafeChangeCoordinator(c, s).apply(
        request(),
        "src/ai_foundation/example.py",
        "new",
    )

    assert result.status == "BLOCKED"
    assert "uncertainty" in result.reason
    assert s.calls == 0


def test_unbounded_target_fails_closed_before_write():
    c = Compiler(context())
    s = Specialist(CodingResult("old", "unused", "VERIFIED_COMPLETE"))

    result = SafeChangeCoordinator(c, s).apply(
        request(),
        "src/ai_foundation/other.py",
        "new",
    )

    assert result.status == "BLOCKED"
    assert result.reason == "target is not bounded by development context"
    assert s.calls == 0


def test_file_subject_without_symbol_can_bound_target():
    c = Compiler(context(code_subjects=("src/ai_foundation/example.py",)))
    s = Specialist(CodingResult("old", "before=pass; after=pass", "VERIFIED_COMPLETE"))

    result = SafeChangeCoordinator(c, s).apply(
        request(),
        "./src/ai_foundation/example.py",
        "new",
    )

    assert result.status == "VERIFIED"
    assert s.calls == 1


def test_uncertain_effect_is_not_reported_as_success():
    c = Compiler(context())
    s = Specialist(
        CodingResult(
            "old",
            "before=pass; after=NOT_RUN: effect=UNCERTAIN_RECONCILE_REQUIRED",
            "UNCERTAIN_RECONCILE_REQUIRED",
        )
    )

    result = SafeChangeCoordinator(c, s).apply(
        request(),
        "src/ai_foundation/example.py",
        "new",
    )

    assert result.status == "UNCERTAIN"
    assert result.mutated
    assert "UNCERTAIN_RECONCILE_REQUIRED" in result.reason


def test_post_change_test_failure_is_failed_not_verified():
    c = Compiler(context())
    s = Specialist(
        CodingResult(
            "old",
            "before=pass; after=FAILED: tests failed",
            "VERIFIED_COMPLETE",
        )
    )

    result = SafeChangeCoordinator(c, s).apply(
        request(),
        "src/ai_foundation/example.py",
        "new",
    )

    assert result.status == "FAILED"
    assert result.mutated


def test_empty_target_is_rejected_before_context_or_write():
    c = Compiler(context())
    s = Specialist(CodingResult("old", "unused", "VERIFIED_COMPLETE"))

    try:
        SafeChangeCoordinator(c, s).apply(request(), " ", "new")
    except ValueError as exc:
        assert "target" in str(exc)
    else:
        raise AssertionError("empty target was accepted")

    assert c.calls == 0
    assert s.calls == 0
