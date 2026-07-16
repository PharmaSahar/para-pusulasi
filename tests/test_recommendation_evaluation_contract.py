from __future__ import annotations

import pytest

from src.recommendation_evaluation_contract import (
    RECOMMENDATION_EVALUATION_SCHEMA_VERSION,
    RecommendationAdvisoryResult,
    RecommendationEvaluationState,
    build_recommendation_evaluation_record,
    validate_recommendation_evaluation_row,
)


BASE_TIME = "2026-07-16T10:00:00+00:00"


def _payload() -> dict[str, object]:
    return {
        "recommendation_id": "rcr_001",
        "recommendation_schema_version": "v1",
        "decision_id": "dec_001",
        "learning_record_id": "lr_001",
        "outcome_record_id": "otr_001",
        "confidence_id": "scid_001",
        "attribution_record_id": "car_001",
        "experiment_id": "exp_001",
        "lifecycle_id": "life_001",
        "policy_id": "policy:v2.4",
        "model_id": "model:v3.2",
        "prompt_id": "prompt:v1.7",
        "confidence_state": "STATISTICALLY_SUPPORTED",
        "attribution_state": "CAUSALLY_SUPPORTED",
        "lineage_complete": True,
        "human_review_required": True,
        "evidence_summary": {
            "recommendation_eligible": True,
            "policy_state": "ALLOW",
            "synthetic_evidence": False,
            "contamination_state": "NONE",
            "outcome_maturity_state": "mature",
            "unresolved_evidence": False,
        },
    }


def _build(payload: dict[str, object], *, created_at: str = BASE_TIME) -> dict[str, object]:
    return build_recommendation_evaluation_record(
        payload,
        evaluator_version="a3.1",
        created_at=created_at,
    )


def test_deterministic_record_creation_for_identical_input() -> None:
    first = _build(_payload())
    second = _build(_payload())
    assert first == second
    assert first["evaluation_schema_version"] == RECOMMENDATION_EVALUATION_SCHEMA_VERSION
    assert first["evaluation_state"] == RecommendationEvaluationState.ADVISORY_PASS.value
    assert first["advisory_result"] == RecommendationAdvisoryResult.PASS.value


def test_different_material_input_changes_fingerprint() -> None:
    first = _build(_payload())
    modified = _payload()
    modified["model_id"] = "model:v3.3"
    second = _build(modified)
    assert first["input_fingerprint"] != second["input_fingerprint"]
    assert first["evaluation_id"] != second["evaluation_id"]


def test_missing_required_reference_blocks() -> None:
    payload = _payload()
    payload["decision_id"] = ""
    with pytest.raises(ValueError, match="missing_field:decision_id"):
        _build(payload)


def test_missing_policy_lineage_blocks() -> None:
    payload = _payload()
    payload["policy_id"] = ""
    with pytest.raises(ValueError, match="missing_field:policy_id"):
        _build(payload)


def test_invalid_state_result_combination_rejected() -> None:
    row = _build(_payload())
    row["evaluation_state"] = RecommendationEvaluationState.BLOCKED.value
    with pytest.raises(ValueError, match="invalid_field:evaluation_state"):
        validate_recommendation_evaluation_row(row)


def test_blocked_record_requires_blocking_reasons() -> None:
    payload = _payload()
    payload["confidence_state"] = "INSUFFICIENT_SAMPLE"
    row = _build(payload)
    assert row["evaluation_state"] == RecommendationEvaluationState.BLOCKED.value
    assert row["blocking_reasons"]


def test_advisory_pass_requires_complete_lineage() -> None:
    payload = _payload()
    payload["lineage_complete"] = False
    row = _build(payload)
    assert row["evaluation_state"] == RecommendationEvaluationState.BLOCKED.value
    assert "incomplete_lineage" in row["blocking_reasons"]


def test_human_review_required_false_rejected() -> None:
    payload = _payload()
    payload["human_review_required"] = False
    with pytest.raises(ValueError, match="invalid_field:human_review_required"):
        _build(payload)


def test_runtime_action_field_rejected() -> None:
    payload = _payload()
    payload["evidence_summary"] = {
        "recommendation_eligible": True,
        "policy_state": "ALLOW",
        "outcome_maturity_state": "mature",
        "action": "deploy",
    }
    with pytest.raises(ValueError, match="runtime_action_value"):
        _build(payload)


def test_unsupported_schema_version_rejected() -> None:
    payload = _payload()
    payload["evaluation_schema_version"] = "v2"
    with pytest.raises(ValueError, match="invalid_field:evaluation_schema_version"):
        _build(payload)


def test_blocking_reason_order_is_deterministic() -> None:
    payload = _payload()
    payload["lineage_complete"] = False
    payload["confidence_state"] = "INSUFFICIENT_SAMPLE"
    payload["attribution_state"] = "ASSOCIATIONAL_ONLY"
    payload["evidence_summary"] = {
        "recommendation_eligible": True,
        "policy_state": "BLOCKED",
        "synthetic_evidence": True,
        "contamination_state": "HIGH",
        "outcome_maturity_state": "immature",
        "unresolved_evidence": True,
    }
    row = _build(payload)
    assert row["blocking_reasons"] == (
        "synthetic_evidence",
        "contaminated_evidence",
        "immature_evidence",
        "unresolved_evidence",
        "incomplete_lineage",
        "policy_blocked",
        "confidence_not_supported",
        "attribution_not_supported",
    )


def test_identity_fingerprint_tampering_rejected() -> None:
    row = _build(_payload())
    row["input_fingerprint"] = "reif_tampered"
    with pytest.raises(ValueError, match="invalid_field:input_fingerprint"):
        validate_recommendation_evaluation_row(row)