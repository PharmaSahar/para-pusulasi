from __future__ import annotations

import json

import pytest

from src.outcome_maturity_contract import (
    ObservationWindowType,
    OutcomeMaturityState,
    build_kpi_category_map,
    build_outcome_maturity_record,
    compute_outcome_event_id,
    compute_outcome_record_id,
    compute_record_hash,
    validate_maturity_transition,
    validate_outcome_maturity_row,
)
from tests.outcome_maturity_fixtures import BASE_TIME, base_outcome_payload


def test_outcome_record_is_deterministic() -> None:
    payload = base_outcome_payload()
    first = build_outcome_maturity_record(
        payload,
        created_by="tester",
        source_module="tests.test_outcome_maturity_contract",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    second = build_outcome_maturity_record(
        payload,
        created_by="tester",
        source_module="tests.test_outcome_maturity_contract",
        source_version="1.0",
        created_at=BASE_TIME,
    )

    assert first == second
    assert first["outcome_record_id"] == compute_outcome_record_id(first)
    assert first["record_hash"] == compute_record_hash(first)
    assert first["outcome_event_id"] == compute_outcome_event_id(first)
    assert list(json.loads(json.dumps(first, sort_keys=True)).keys()) == sorted(first.keys())


def test_observation_window_is_mandatory() -> None:
    with pytest.raises(ValueError, match="missing_field:observation_window_type|invalid_field:observation_window_type"):
        build_outcome_maturity_record(
            base_outcome_payload(observation_window_type=""),
            created_by="tester",
            source_module="tests.test_outcome_maturity_contract",
            source_version="1.0",
            created_at=BASE_TIME,
        )

    with pytest.raises(ValueError, match="invalid_field:observation_window_type"):
        build_outcome_maturity_record(
            base_outcome_payload(observation_window_type="CUSTOM"),
            created_by="tester",
            source_module="tests.test_outcome_maturity_contract",
            source_version="1.0",
            created_at=BASE_TIME,
        )


def test_kpi_categories_are_deterministic_metadata() -> None:
    record = build_outcome_maturity_record(
        base_outcome_payload(),
        created_by="tester",
        source_module="tests.test_outcome_maturity_contract",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    assert record["kpi_categories"] == build_kpi_category_map()
    assert record["kpi_categories"]["exposure"] == ("impressions", "ctr_ratio")
    assert record["kpi_categories"]["engagement"][0] == "watch_time_hours"
    assert record["kpi_categories"]["community"][2] == "comments"


def test_zero_values_remain_distinct_from_unknown() -> None:
    record = build_outcome_maturity_record(
        base_outcome_payload(impressions=0, ctr_ratio=0.0, comments=0, unknown_reasons=[]),
        created_by="tester",
        source_module="tests.test_outcome_maturity_contract",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    assert record["impressions"] == 0
    assert record["ctr_ratio"] == 0.0
    assert record["comments"] == 0

    unknown = build_outcome_maturity_record(
        base_outcome_payload(impressions=None, ctr_ratio=None, comments=None, unknown_reasons=["missing_analytics"]),
        created_by="tester",
        source_module="tests.test_outcome_maturity_contract",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    assert unknown["impressions"] is None
    assert unknown["ctr_ratio"] is None
    assert unknown["comments"] is None


def test_forbidden_fields_are_rejected() -> None:
    with pytest.raises(ValueError, match="forbidden_field:revenue"):
        build_outcome_maturity_record(
            base_outcome_payload(revenue=100.0),
            created_by="tester",
            source_module="tests.test_outcome_maturity_contract",
            source_version="1.0",
            created_at=BASE_TIME,
        )

    with pytest.raises(ValueError, match="forbidden_field:confidence"):
        build_outcome_maturity_record(
            base_outcome_payload(confidence=0.8),
            created_by="tester",
            source_module="tests.test_outcome_maturity_contract",
            source_version="1.0",
            created_at=BASE_TIME,
        )


def test_maturity_transition_contract() -> None:
    assert validate_maturity_transition(OutcomeMaturityState.UNKNOWN.value, OutcomeMaturityState.IMMATURE.value)
    assert validate_maturity_transition(OutcomeMaturityState.PARTIALLY_OBSERVED.value, OutcomeMaturityState.MATURE.value)
    assert not validate_maturity_transition(OutcomeMaturityState.ARCHIVED.value, OutcomeMaturityState.IMMATURE.value)


def test_validate_row_recomputes_hash_fields() -> None:
    row = build_outcome_maturity_record(
        base_outcome_payload(observation_window_type=ObservationWindowType.ONE_HOUR.value),
        created_by="tester",
        source_module="tests.test_outcome_maturity_contract",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    row["record_hash"] = "bad_hash"
    normalized = validate_outcome_maturity_row(row)
    assert normalized["record_hash"].startswith("oth_")
    assert normalized["outcome_event_id"].startswith("ote_")
