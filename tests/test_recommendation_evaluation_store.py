from __future__ import annotations

from pathlib import Path

import pytest

from src.recommendation_evaluation_store import (
    RecommendationEvaluationConflictError,
    RecommendationEvaluationCorruptionError,
    RecommendationEvaluationStore,
)


BASE_TIME = "2026-07-16T10:00:00+00:00"


def _payload() -> dict[str, object]:
    return {
        "evaluator_version": "a3.1",
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


def test_append_valid_record(tmp_path: Path) -> None:
    store = RecommendationEvaluationStore(evaluation_path=tmp_path / "recommendation_evaluation.jsonl")
    result = store.append_evaluation_event(
        _payload(),
        created_by="tester",
        source_module="tests.test_recommendation_evaluation_store",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    assert result.appended is True
    assert len(store.get_rows()) == 1


def test_exact_duplicate_is_idempotent(tmp_path: Path) -> None:
    store = RecommendationEvaluationStore(evaluation_path=tmp_path / "recommendation_evaluation.jsonl")
    first = store.append_evaluation_event(_payload(), created_by="tester", source_module="tests.store", source_version="1.0", created_at=BASE_TIME)
    second = store.append_evaluation_event(_payload(), created_by="tester", source_module="tests.store", source_version="1.0", created_at=BASE_TIME)
    assert first.appended is True
    assert second.appended is False
    assert second.duplicate is True
    assert second.reason == "exact_duplicate"


def test_conflicting_duplicate_rejected(tmp_path: Path) -> None:
    store = RecommendationEvaluationStore(evaluation_path=tmp_path / "recommendation_evaluation.jsonl")
    store.append_evaluation_event(_payload(), created_by="tester", source_module="tests.store", source_version="1.0", created_at=BASE_TIME)
    payload = _payload()
    payload["confidence_state"] = "INSUFFICIENT_SAMPLE"
    with pytest.raises(RecommendationEvaluationConflictError):
        result = store.append_evaluation_event(payload, created_by="tester", source_module="tests.store", source_version="1.0", created_at=BASE_TIME)
        if result.conflict:
            raise RecommendationEvaluationConflictError("conflicting_duplicate")


def test_replay_returns_original_deterministic_order(tmp_path: Path) -> None:
    store = RecommendationEvaluationStore(evaluation_path=tmp_path / "recommendation_evaluation.jsonl")
    payload_a = _payload()
    payload_a["recommendation_id"] = "rcr_a"
    payload_b = _payload()
    payload_b["recommendation_id"] = "rcr_b"
    store.append_evaluation_event(payload_b, created_by="tester", source_module="tests.store", source_version="1.0", created_at="2026-07-16T10:01:00+00:00")
    store.append_evaluation_event(payload_a, created_by="tester", source_module="tests.store", source_version="1.0", created_at=BASE_TIME)
    projection, _diagnostics = store.replay()
    assert list(projection["latest_by_recommendation_id"].keys()) == ["rcr_a", "rcr_b"]


def test_corrupt_jsonl_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "recommendation_evaluation.jsonl"
    path.write_text("{\"broken\"\n", encoding="utf-8")
    store = RecommendationEvaluationStore(evaluation_path=path)
    with pytest.raises(RecommendationEvaluationCorruptionError):
        store.get_rows()


def test_invalid_row_in_history_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "recommendation_evaluation.jsonl"
    path.write_text('{"evaluation_schema_version":"v1"}\n', encoding="utf-8")
    store = RecommendationEvaluationStore(evaluation_path=path)
    with pytest.raises(RecommendationEvaluationCorruptionError):
        store.replay()


def test_hash_chain_verifies_valid_history(tmp_path: Path) -> None:
    store = RecommendationEvaluationStore(evaluation_path=tmp_path / "recommendation_evaluation.jsonl")
    store.append_evaluation_event(_payload(), created_by="tester", source_module="tests.store", source_version="1.0", created_at=BASE_TIME)
    chain = store.verify_hash_chain()
    assert chain["valid"] is True


def test_hash_chain_detects_tampering(tmp_path: Path) -> None:
    path = tmp_path / "recommendation_evaluation.jsonl"
    store = RecommendationEvaluationStore(evaluation_path=path)
    store.append_evaluation_event(_payload(), created_by="tester", source_module="tests.store", source_version="1.0", created_at=BASE_TIME)
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("policy:v2.4", "policy:tampered"), encoding="utf-8")
    with pytest.raises(RecommendationEvaluationCorruptionError):
        store.get_rows()


def test_no_update_delete_api_exists(tmp_path: Path) -> None:
    store = RecommendationEvaluationStore(evaluation_path=tmp_path / "recommendation_evaluation.jsonl")
    assert not hasattr(store, "update")
    assert not hasattr(store, "delete")