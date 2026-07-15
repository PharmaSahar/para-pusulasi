from __future__ import annotations

import pytest

from src.causal_attribution_contract import (
    CausalAttributionState,
    build_causal_attribution_record,
    classify_causal_attribution_state,
    compute_attribution_event_id,
    compute_attribution_record_id,
    compute_record_hash,
)
from tests.causal_attribution_fixtures import BASE_TIME, base_attribution_payload


def test_canonical_record_creation_and_deterministic_identity() -> None:
    payload = base_attribution_payload()
    first = build_causal_attribution_record(
        payload,
        created_by="tester",
        source_module="tests.test_causal_attribution_contract",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    second = build_causal_attribution_record(
        payload,
        created_by="tester",
        source_module="tests.test_causal_attribution_contract",
        source_version="1.0",
        created_at=BASE_TIME,
    )

    assert first["attribution_state"] == CausalAttributionState.CAUSALLY_SUPPORTED.value
    assert first["attribution_record_id"] == second["attribution_record_id"]
    assert first["attribution_event_id"] == second["attribution_event_id"]
    assert first["record_hash"] == second["record_hash"]
    assert compute_attribution_record_id(first) == first["attribution_record_id"]
    assert compute_record_hash(first) == first["record_hash"]
    assert compute_attribution_event_id(first) == first["attribution_event_id"]


def test_required_field_validation_rejects_missing_experiment_id() -> None:
    with pytest.raises(ValueError, match="missing_field:experiment_id"):
        build_causal_attribution_record(
            base_attribution_payload(experiment_id=""),
            created_by="tester",
            source_module="tests.test_causal_attribution_contract",
            source_version="1.0",
            created_at=BASE_TIME,
        )


@pytest.mark.parametrize(
    "overrides,expected_state",
    [
        ({"invalidation_reasons": ["source_history_corrupted"]}, CausalAttributionState.INVALIDATED.value),
        ({"lineage_complete": False}, CausalAttributionState.INSUFFICIENT_LINEAGE.value),
        ({"control_group_present": False}, CausalAttributionState.INSUFFICIENT_CONTROL.value),
        ({"outcome_maturity_state": "immature"}, CausalAttributionState.IMMATURE_OUTCOME.value),
        ({"contamination_state": "LOW"}, CausalAttributionState.CONTAMINATED.value),
        ({"confounder_status": "UNRESOLVED", "unresolved_confounders": ["seasonality"]}, CausalAttributionState.CONFOUNDED.value),
        ({"sample_sufficiency": False}, CausalAttributionState.UNDERPOWERED.value),
        ({"randomized_assignment_proven": False, "assignment_method": "observational"}, CausalAttributionState.ASSOCIATIONAL_ONLY.value),
        ({"counterfactual_is_observed": False, "counterfactual_status": "UNAVAILABLE"}, CausalAttributionState.ATTRIBUTION_ELIGIBLE.value),
        ({"multiple_comparison_governed": False}, CausalAttributionState.CAUSALLY_INCONCLUSIVE.value),
    ],
)
def test_state_precedence_and_classification(overrides: dict[str, object], expected_state: str) -> None:
    record = build_causal_attribution_record(
        base_attribution_payload(**overrides),
        created_by="tester",
        source_module="tests.test_causal_attribution_contract",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    assert record["attribution_state"] == expected_state
    assert classify_causal_attribution_state(record)[0] == expected_state


def test_synthetic_counterfactual_blocks_supported_state() -> None:
    record = build_causal_attribution_record(
        base_attribution_payload(
            counterfactual_status="SYNTHETIC_OR_SIMULATED",
            counterfactual_is_synthetic=True,
        ),
        created_by="tester",
        source_module="tests.test_causal_attribution_contract",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    assert record["attribution_state"] == CausalAttributionState.CAUSALLY_INCONCLUSIVE.value


def test_effect_values_missing_prevents_causal_support() -> None:
    record = build_causal_attribution_record(
        base_attribution_payload(
            treatment_effect_absolute=None,
            treatment_effect_relative=None,
        ),
        created_by="tester",
        source_module="tests.test_causal_attribution_contract",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    assert record["attribution_state"] == CausalAttributionState.CAUSALLY_INCONCLUSIVE.value
