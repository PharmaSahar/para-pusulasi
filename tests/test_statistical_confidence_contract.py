from __future__ import annotations

import pytest

from src.statistical_confidence_contract import (
    StatisticalConfidenceState,
    build_statistical_confidence_record,
    classify_statistical_confidence_state,
    compute_confidence_id,
)
from tests.statistical_confidence_fixtures import BASE_TIME, base_confidence_payload


def test_valid_confidence_record_is_supported_and_deterministic() -> None:
    payload = base_confidence_payload()
    first = build_statistical_confidence_record(
        payload,
        created_by="tester",
        source_module="tests.test_statistical_confidence_contract",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    second = build_statistical_confidence_record(
        payload,
        created_by="tester",
        source_module="tests.test_statistical_confidence_contract",
        source_version="1.0",
        created_at=BASE_TIME,
    )

    assert first["confidence_state"] == StatisticalConfidenceState.STATISTICALLY_SUPPORTED.value
    assert first["confidence_id"] == second["confidence_id"]
    assert first["record_hash"] == second["record_hash"]
    assert compute_confidence_id(first) == first["confidence_id"]


@pytest.mark.parametrize(
    "payload,expected_state",
    [
        ({"sample_size": 10, "treatment_size": 5, "control_size": 5}, StatisticalConfidenceState.INSUFFICIENT_SAMPLE.value),
        ({"maturity_state": "immature"}, StatisticalConfidenceState.IMMATURE_WINDOW.value),
        ({"contamination_state": "HIGH"}, StatisticalConfidenceState.CONTAMINATED.value),
        ({"minimum_power_required": 0.95, "effect_size_absolute": 0.02, "effect_size_relative": 0.02}, StatisticalConfidenceState.UNDERPOWERED.value),
        ({"sample_size": 1000, "treatment_size": 500, "control_size": 500, "effect_size_absolute": 0.01, "effect_size_relative": 0.01}, StatisticalConfidenceState.DIRECTIONAL_SIGNAL.value),
        ({"effect_size_absolute": 0.0, "effect_size_relative": 0.0}, StatisticalConfidenceState.STATISTICALLY_INCONCLUSIVE.value),
        ({"confidence_inputs": {"comparison_family": "", "correction_method": ""}}, StatisticalConfidenceState.INVALIDATED.value),
    ],
)
def test_state_classification_variants(payload: dict[str, object], expected_state: str) -> None:
    if expected_state == StatisticalConfidenceState.NOT_ASSESSED.value:
        record = base_confidence_payload(**payload)
        assert classify_statistical_confidence_state(record)[0] == expected_state
        return

    record = build_statistical_confidence_record(
        base_confidence_payload(**payload),
        created_by="tester",
        source_module="tests.test_statistical_confidence_contract",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    assert record["confidence_state"] == expected_state
    assert classify_statistical_confidence_state(record)[0] == expected_state


def test_missing_comparison_controls_are_rejected() -> None:
    record = build_statistical_confidence_record(
        base_confidence_payload(confidence_inputs={"comparison_family": "experiment_primary"}),
        created_by="tester",
        source_module="tests.test_statistical_confidence_contract",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    assert record["confidence_state"] == StatisticalConfidenceState.INVALIDATED.value
