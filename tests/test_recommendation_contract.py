from __future__ import annotations

import pytest

from src.recommendation_contract import (
    RecommendationState,
    build_recommendation_record,
    classify_recommendation_state,
    validate_recommendation_row,
)
from tests.recommendation_fixtures import BASE_TIME, base_recommendation_payload


def _build(payload: dict[str, object], *, created_at: str = BASE_TIME) -> dict[str, object]:
    return build_recommendation_record(
        payload,
        created_by="tester",
        source_module="tests.test_recommendation_contract",
        source_version="1.0",
        created_at=created_at,
    )


def test_build_recommendation_record_is_deterministic() -> None:
    first = _build(base_recommendation_payload())
    second = _build(base_recommendation_payload())
    assert first == second
    assert first["recommendation_record_id"].startswith("rcr_")
    assert first["record_hash"].startswith("rch_")
    assert first["recommendation_event_id"].startswith("rce_")
    assert first["recommendation_state"] == RecommendationState.ADVISORY_RECOMMENDATION.value
    assert first["human_review_required"] is True


def test_missing_required_text_field_raises() -> None:
    payload = base_recommendation_payload()
    del payload["decision_id"]
    with pytest.raises(ValueError, match="missing_field:decision_id"):
        _build(payload)


def test_runtime_action_key_is_rejected() -> None:
    payload = base_recommendation_payload()
    payload["advisory_recommendation"] = {
        "title_variant": "Option C",
        "execute": "publish",
    }
    with pytest.raises(ValueError, match="runtime_action_key"):
        _build(payload)


def test_runtime_action_value_is_rejected() -> None:
    payload = base_recommendation_payload()
    payload["advisory_recommendation"] = {
        "action": "deploy",
        "reasoning": "forbidden",
    }
    with pytest.raises(ValueError, match="runtime_action_value"):
        _build(payload)


def test_associational_only_maps_to_associational_state() -> None:
    payload = base_recommendation_payload()
    payload["attribution_state"] = "ASSOCIATIONAL_ONLY"
    payload["advisory_recommendation"] = None
    row = _build(payload)
    assert row["recommendation_state"] == RecommendationState.ASSOCIATIONAL_ONLY.value


def test_policy_blocked_is_fail_closed() -> None:
    payload = base_recommendation_payload()
    payload["recommendation_policy_status"] = "BLOCKED"
    payload["advisory_recommendation"] = None
    row = _build(payload)
    assert row["recommendation_state"] == RecommendationState.POLICY_BLOCKED.value


def test_supplied_state_mismatch_is_rejected() -> None:
    payload = base_recommendation_payload()
    row = _build(payload)
    row["recommendation_state"] = RecommendationState.RECOMMENDATION_ELIGIBLE.value
    with pytest.raises(ValueError, match="invalid_field:recommendation_state"):
        validate_recommendation_row(row)


def test_classifier_invalidates_synthetic_evidence() -> None:
    payload = base_recommendation_payload()
    payload["evidence_is_synthetic"] = True
    payload["advisory_recommendation"] = None
    state, reason = classify_recommendation_state(_build(payload))
    assert state == RecommendationState.INVALIDATED.value
    assert reason == "synthetic_evidence"
