"""Deterministic long-term storage capacity planning.

This module is policy/evidence projection only.  It does not delete data,
grant storage authority, or infer real production workload rates.

Scenario operation rates are explicit planning assumptions.  They are never
reported as observed production usage.
"""
from __future__ import annotations

from dataclasses import dataclass


DAYS_PER_MONTH = 30
DAYS_PER_YEAR = 365
DAYS_PER_THREE_YEARS = 3 * DAYS_PER_YEAR


@dataclass(frozen=True)
class CapacityScenario:
    name: str
    operations_per_day: int


@dataclass(frozen=True)
class CapacityProjection:
    scenario: str
    operations_per_day: int
    bytes_per_operation: float
    month_bytes: int
    year_bytes: int
    three_year_bytes: int


# Deliberately broad planning envelopes, not observed production rates.
PLANNING_SCENARIOS = (
    CapacityScenario("low", 100),
    CapacityScenario("nominal", 1_000),
    CapacityScenario("high", 10_000),
)


def bytes_per_operation(measured_bytes: int, measured_operations: int) -> float:
    if measured_bytes < 0:
        raise ValueError("measured_bytes must be non-negative")
    if measured_operations <= 0:
        raise ValueError("measured_operations must be positive")
    return measured_bytes / measured_operations


def project_growth(
    measured_bytes: int,
    measured_operations: int,
    scenarios=PLANNING_SCENARIOS,
) -> tuple[CapacityProjection, ...]:
    coefficient = bytes_per_operation(measured_bytes, measured_operations)
    out = []
    for scenario in scenarios:
        if scenario.operations_per_day < 0:
            raise ValueError("operations_per_day must be non-negative")
        daily = coefficient * scenario.operations_per_day
        out.append(
            CapacityProjection(
                scenario=scenario.name,
                operations_per_day=scenario.operations_per_day,
                bytes_per_operation=coefficient,
                month_bytes=round(daily * DAYS_PER_MONTH),
                year_bytes=round(daily * DAYS_PER_YEAR),
                three_year_bytes=round(daily * DAYS_PER_THREE_YEARS),
            )
        )
    return tuple(out)


def bounded_capacity(max_bytes: int | None = None, max_generations: int | None = None):
    """Describe an already-bounded surface without inventing bytes/op growth."""
    if max_bytes is None and max_generations is None:
        raise ValueError("at least one bound is required")
    if max_bytes is not None and max_bytes < 0:
        raise ValueError("max_bytes must be non-negative")
    if max_generations is not None and max_generations < 1:
        raise ValueError("max_generations must be positive")
    return {
        "growth_model": "bounded",
        "max_bytes": max_bytes,
        "max_generations": max_generations,
    }
