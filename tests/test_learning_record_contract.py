from __future__ import annotations

import json

import pytest

from src.learning_record_contract import (
    LearningMaturityState,
    build_learning_record,
    compute_learning_event_id,
    compute_learning_record_id,
    compute_record_hash,
    validate_learning_record_row,
    validate_maturity_transition,
)
from tests.learning_record_fixtures import BASE_TIME, base_learning_payload


def test_learning_record_is_deterministic() -> None:
    payload = base_learning_payload()
    first = build_learning_record(
        payload,
        created_by="tester",
        source_module="tests.test_learning_record_contract",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    second = build_learning_record(
        payload,
        created_by="tester",
        source_module="tests.test_learning_record_contract",
        source_version="1.0",
        created_at=BASE_TIME,
    )

    assert first == second
    assert first["learning_record_id"] == compute_learning_record_id(first)
    assert first["record_hash"] == compute_record_hash(first)
    assert first["learning_event_id"] == compute_learning_event_id(first)
    assert list(json.loads(json.dumps(first, sort_keys=True)).keys()) == sorted(first.keys())


def test_zero_values_remain_distinct_from_unknown() -> None:
    record = build_learning_record(
        base_learning_payload(impressions=0, ctr_ratio=0.0, comments=0, unknown_reasons=[]),
        created_by="tester",
        source_module="tests.test_learning_record_contract",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    assert record["impressions"] == 0
    assert record["ctr_ratio"] == 0.0
    assert record["comments"] == 0

    unknown = build_learning_record(
        base_learning_payload(impressions=None, ctr_ratio=None, comments=None, unknown_reasons=["missing_analytics"]),
        created_by="tester",
        source_module="tests.test_learning_record_contract",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    assert unknown["impressions"] is None
    assert unknown["ctr_ratio"] is None
    assert unknown["comments"] is None


def test_forbidden_fields_are_rejected() -> None:
    with pytest.raises(ValueError, match="forbidden_field:revenue"):
        build_learning_record(
            base_learning_payload(revenue=100.0),
            created_by="tester",
            source_module="tests.test_learning_record_contract",
            source_version="1.0",
            created_at=BASE_TIME,
        )

    with pytest.raises(ValueError, match="forbidden_field:confidence"):
        build_learning_record(
            base_learning_payload(confidence=0.8),
            created_by="tester",
            source_module="tests.test_learning_record_contract",
            source_version="1.0",
            created_at=BASE_TIME,
        )


def test_maturity_transition_contract() -> None:
    assert validate_maturity_transition(LearningMaturityState.UNKNOWN.value, LearningMaturityState.IMMATURE.value)
    assert validate_maturity_transition(LearningMaturityState.PARTIALLY_OBSERVED.value, LearningMaturityState.MATURE.value)
    assert not validate_maturity_transition(LearningMaturityState.ARCHIVED.value, LearningMaturityState.IMMATURE.value)


def test_validate_row_recomputes_hash_fields() -> None:
    row = build_learning_record(
        base_learning_payload(),
        created_by="tester",
        source_module="tests.test_learning_record_contract",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    row["record_hash"] = "bad_hash"
    normalized = validate_learning_record_row(row)
    assert normalized["record_hash"].startswith("lrh_")
    assert normalized["learning_event_id"].startswith("lre_")
