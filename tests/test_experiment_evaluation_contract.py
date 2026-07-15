from __future__ import annotations

import pytest

from src.experiment_evaluation_contract import (
    ContaminationSeverity,
    ExperimentEvaluationState,
    OutcomeMaturityState,
    build_experiment_evaluation_record,
    classify_experiment_evaluation_state,
    compute_evaluation_record_id,
)
from tests.experiment_evaluation_fixtures import BASE_TIME, base_evaluation_payload


def test_valid_record_is_validated_result_and_deterministic() -> None:
    payload = base_evaluation_payload()
    first = build_experiment_evaluation_record(
        payload,
        created_by="tester",
        source_module="tests.test_experiment_evaluation_contract",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    second = build_experiment_evaluation_record(
        payload,
        created_by="tester",
        source_module="tests.test_experiment_evaluation_contract",
        source_version="1.0",
        created_at=BASE_TIME,
    )

    assert first["evaluation_state"] == ExperimentEvaluationState.VALIDATED_RESULT.value
    assert first["evaluation_record_id"] == second["evaluation_record_id"]
    assert first["record_hash"] == second["record_hash"]
    assert compute_evaluation_record_id(first) == first["evaluation_record_id"]


@pytest.mark.parametrize(
    "payload,expected_state",
    [
        ({"assignment_id": ""}, ExperimentEvaluationState.NOT_READY.value),
        ({"total_exposure_count": 5}, ExperimentEvaluationState.INSUFFICIENT_EXPOSURE.value),
        ({"outcome_maturity_state": OutcomeMaturityState.IMMATURE.value}, ExperimentEvaluationState.IMMATURE_OUTCOME.value),
        ({"contamination_severity": ContaminationSeverity.LOW.value}, ExperimentEvaluationState.CONTAMINATED.value),
        ({"total_sample_size": 80, "control_metric_value": 0.1, "treatment_metric_value": 0.2}, ExperimentEvaluationState.DIRECTIONAL_ONLY.value),
        ({"total_sample_size": 80, "control_metric_value": 0.1, "treatment_metric_value": 0.1}, ExperimentEvaluationState.INCONCLUSIVE.value),
        ({"evidence_lineage_count": 1, "evidence_lineage_required_count": 2, "evidence_lineage_completeness": 0.5}, ExperimentEvaluationState.EVALUABLE.value),
    ],
)
def test_state_classification_variants(payload: dict[str, object], expected_state: str) -> None:
    if expected_state == ExperimentEvaluationState.NOT_READY.value:
        record = base_evaluation_payload(**payload)
        assert classify_experiment_evaluation_state(record)[0] == expected_state
        return

    record = build_experiment_evaluation_record(
        base_evaluation_payload(**payload),
        created_by="tester",
        source_module="tests.test_experiment_evaluation_contract",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    assert record["evaluation_state"] == expected_state
    assert classify_experiment_evaluation_state(record)[0] == expected_state


def test_explicit_state_mismatch_is_rejected() -> None:
    with pytest.raises(ValueError):
        build_experiment_evaluation_record(
            base_evaluation_payload(evaluation_state=ExperimentEvaluationState.NOT_READY.value),
            created_by="tester",
            source_module="tests.test_experiment_evaluation_contract",
            source_version="1.0",
            created_at=BASE_TIME,
        )
