from __future__ import annotations

from src.recommendation_evaluation_contract import build_recommendation_evaluation_record
from src.recommendation_evaluation_projection import build_recommendation_evaluation_projection_from_rows


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


def _row(payload: dict[str, object], *, created_at: str) -> dict[str, object]:
    row = build_recommendation_evaluation_record(payload, evaluator_version="a3.1", created_at=created_at)
    row["evaluation_event_id"] = f"evt_{created_at}"
    row["record_hash"] = f"hash_{created_at}"
    row["created_by"] = "tester"
    row["source_module"] = "tests.test_recommendation_evaluation_projection"
    row["source_version"] = "1.0"
    return row


def test_state_counts_are_correct() -> None:
    good = _row(_payload(), created_at=BASE_TIME)
    blocked_payload = _payload()
    blocked_payload["confidence_state"] = "INSUFFICIENT_SAMPLE"
    blocked = _row(blocked_payload, created_at="2026-07-16T10:01:00+00:00")
    projection = build_recommendation_evaluation_projection_from_rows([blocked, good])
    assert projection["counts_by_evaluation_state"]["advisory_pass"] == 1
    assert projection["counts_by_evaluation_state"]["blocked"] == 1


def test_advisory_result_counts_are_correct() -> None:
    good = _row(_payload(), created_at=BASE_TIME)
    fail_payload = _payload()
    fail_payload["evidence_summary"] = {
        "recommendation_eligible": False,
        "policy_state": "ALLOW",
        "synthetic_evidence": False,
        "contamination_state": "NONE",
        "outcome_maturity_state": "mature",
        "unresolved_evidence": False,
    }
    fail = _row(fail_payload, created_at="2026-07-16T10:01:00+00:00")
    projection = build_recommendation_evaluation_projection_from_rows([good, fail])
    assert projection["counts_by_advisory_result"]["pass"] == 1
    assert projection["counts_by_advisory_result"]["fail"] == 1


def test_blocking_reason_counts_are_correct() -> None:
    blocked_payload = _payload()
    blocked_payload["confidence_state"] = "INSUFFICIENT_SAMPLE"
    blocked_payload["attribution_state"] = "ASSOCIATIONAL_ONLY"
    row = _row(blocked_payload, created_at=BASE_TIME)
    projection = build_recommendation_evaluation_projection_from_rows([row])
    assert projection["counts_by_blocking_reason"]["confidence_not_supported"] == 1
    assert projection["counts_by_blocking_reason"]["attribution_not_supported"] == 1


def test_latest_by_recommendation_is_deterministic() -> None:
    first = _row(_payload(), created_at=BASE_TIME)
    second_payload = _payload()
    second_payload["evidence_summary"] = {
        "recommendation_eligible": False,
        "policy_state": "ALLOW",
        "synthetic_evidence": False,
        "contamination_state": "NONE",
        "outcome_maturity_state": "mature",
        "unresolved_evidence": False,
    }
    second = _row(second_payload, created_at="2026-07-16T10:05:00+00:00")
    projection = build_recommendation_evaluation_projection_from_rows([second, first])
    assert projection["latest_by_recommendation_id"]["rcr_001"]["advisory_result"] == "fail"


def test_latest_valid_by_recommendation_excludes_blocked() -> None:
    blocked_payload = _payload()
    blocked_payload["confidence_state"] = "INSUFFICIENT_SAMPLE"
    blocked = _row(blocked_payload, created_at="2026-07-16T10:05:00+00:00")
    good = _row(_payload(), created_at=BASE_TIME)
    projection = build_recommendation_evaluation_projection_from_rows([blocked, good])
    assert projection["latest_valid_by_recommendation_id"]["rcr_001"]["evaluation_state"] == "advisory_pass"


def test_projection_fingerprint_is_deterministic() -> None:
    row = _row(_payload(), created_at=BASE_TIME)
    first = build_recommendation_evaluation_projection_from_rows([row])
    second = build_recommendation_evaluation_projection_from_rows([row])
    assert first["projection_fingerprint"] == second["projection_fingerprint"]
    assert first["projection_hash"] == second["projection_hash"]


def test_row_order_behavior_follows_append_replay_semantics() -> None:
    row_a = _row(_payload(), created_at="2026-07-16T10:02:00+00:00")
    payload_b = _payload()
    payload_b["recommendation_id"] = "rcr_002"
    row_b = _row(payload_b, created_at=BASE_TIME)
    projection = build_recommendation_evaluation_projection_from_rows([row_a, row_b])
    assert list(projection["latest_by_recommendation_id"].keys()) == ["rcr_002", "rcr_001"]