from ai_foundation.storage_capacity_model import (
    PLANNING_SCENARIOS,
    bounded_capacity,
    bytes_per_operation,
    project_growth,
)
from ai_foundation.storage_admission import DEFAULT_MIN_FREE_BYTES
from ai_foundation.storage_lifecycle import RULES


def test_planning_scenarios_are_explicit_assumptions_not_runtime_observations():
    assert [(x.name, x.operations_per_day) for x in PLANNING_SCENARIOS] == [
        ("low", 100),
        ("nominal", 1_000),
        ("high", 10_000),
    ]


def test_accelerated_measurement_projects_month_year_three_year_growth():
    # Representative synthetic physical measurement coefficient.
    rows = project_growth(36_200_000, 100_000)
    assert rows[0].bytes_per_operation == 362.0
    assert rows[0].month_bytes == 362 * 100 * 30
    assert rows[0].year_bytes == 362 * 100 * 365
    assert rows[0].three_year_bytes == 362 * 100 * 365 * 3
    assert rows[2].three_year_bytes == 362 * 10_000 * 365 * 3


def test_measurement_validation_fails_closed():
    import pytest

    with pytest.raises(ValueError):
        bytes_per_operation(1, 0)
    with pytest.raises(ValueError):
        bytes_per_operation(-1, 1)


def test_bounded_surfaces_use_existing_owner_limits_not_fabricated_rates():
    trace = RULES["foundation-trace"]
    assert bounded_capacity(trace.max_bytes, trace.max_generations) == {
        "growth_model": "bounded",
        "max_bytes": 32 * 1024 * 1024,
        "max_generations": 4,
    }

    backup = RULES["foundation-backup"]
    assert bounded_capacity(
        max_generations=backup.max_generations
    )["max_generations"] == 3


def test_capacity_model_does_not_replace_storage_admission_reserve():
    # LT02 planning and LT11 mutation admission are deliberately separate.
    assert DEFAULT_MIN_FREE_BYTES == 2 * 1024**3
