"""Thin Safe Change composition for bounded Foundation self-development.

This module deliberately owns no filesystem authority, Guard authority,
test runner, rollback engine, graph, or canonical truth.

It composes:
Development Intelligence -> existing CodingSpecialist.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .coding import CodingResult
from .development_context import (
    DevelopmentContext,
    DevelopmentRequest,
)


class ContextCompiler(Protocol):
    def compile(self, request: DevelopmentRequest) -> DevelopmentContext: ...


class ChangeSpecialist(Protocol):
    def apply_verified_change(self, target: str, content: str) -> CodingResult: ...


@dataclass(frozen=True)
class SafeChangeResult:
    """Observed result of one bounded Safe Change attempt.

    VERIFIED means only that the guarded code effect and configured tests
    reached their verified result. It is not delivery, permanent-improvement
    handoff, cleanup completion, or task closeout; P09 assesses those
    separately from owner-issued evidence.
    """

    context: DevelopmentContext
    target: str
    status: str
    coding_result: CodingResult | None = None
    reason: str | None = None

    @property
    def mutated(self) -> bool:
        return self.coding_result is not None


@dataclass
class SafeChangeCoordinator:
    """Fail-closed composition of Development Intelligence and CODE.

    Authority remains entirely in the host-bound CodingSpecialist and its
    Guarded tools.  This coordinator only decides whether the derived
    development context is safe enough to hand off to that existing path.
    """

    compiler: ContextCompiler
    specialist: ChangeSpecialist

    def apply(
        self,
        request: DevelopmentRequest,
        target: str,
        content: str,
    ) -> SafeChangeResult:
        if not target or not target.strip():
            raise ValueError("safe change target is required")

        context = self.compiler.compile(request)

        if not context.fresh:
            return SafeChangeResult(
                context=context,
                target=target,
                status="BLOCKED",
                reason="development context is stale",
            )

        if context.uncertainties:
            return SafeChangeResult(
                context=context,
                target=target,
                status="BLOCKED",
                reason="development context contains uncertainty",
            )

        if not self._target_is_bounded(context, target):
            return SafeChangeResult(
                context=context,
                target=target,
                status="BLOCKED",
                reason="target is not bounded by development context",
            )

        result = self.specialist.apply_verified_change(target, content)

        if result.write_result != "VERIFIED_COMPLETE":
            return SafeChangeResult(
                context=context,
                target=target,
                status="UNCERTAIN",
                coding_result=result,
                reason=f"effect={result.write_result}",
            )

        if "after=FAILED:" in result.test_result:
            return SafeChangeResult(
                context=context,
                target=target,
                status="FAILED",
                coding_result=result,
                reason=result.test_result,
            )

        if "after=NOT_RUN:" in result.test_result:
            return SafeChangeResult(
                context=context,
                target=target,
                status="UNCERTAIN",
                coding_result=result,
                reason=result.test_result,
            )

        return SafeChangeResult(
            context=context,
            target=target,
            status="VERIFIED",
            coding_result=result,
        )

    @staticmethod
    def _target_is_bounded(context: DevelopmentContext, target: str) -> bool:
        """Require DI to identify the requested file/symbol before mutation.

        A code subject may be either a file or ``file::symbol``.  Filesystem
        authorization is intentionally NOT performed here; the existing
        CodingSpecialist/CapabilityAgentTools boundary remains authoritative.
        """

        normalized = target.strip().lstrip("./")

        for subject in context.code_subjects:
            candidate = subject.split("::", 1)[0].strip().lstrip("./")
            if candidate == normalized:
                return True

        return False
