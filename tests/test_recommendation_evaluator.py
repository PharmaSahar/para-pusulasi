from __future__ import annotations

import socket
import subprocess
from pathlib import Path
from typing import Any

import pytest

from src.causal_attribution_contract import build_causal_attribution_record
from src.causal_attribution_store import CausalAttributionStore
from src.decision_contract import build_decision_record
from src.decision_memory import DecisionMemoryStore
from src.recommendation_evaluation_store import RecommendationEvaluationStore
from src.recommendation_evaluator import RecommendationEvaluator, RecommendationEvaluatorError
from src.recommendation_store import RecommendationStore
from src.statistical_confidence_contract import build_statistical_confidence_record
from src.statistical_confidence_store import StatisticalConfidenceCorruptionError
from src.statistical_confidence_store import StatisticalConfidenceStore
from tests.causal_attribution_fixtures import base_attribution_payload
from tests.decision_memory_fixtures import build_decision_payload
from tests.recommendation_fixtures import base_recommendation_payload
from tests.statistical_confidence_fixtures import base_confidence_payload


BASE_TIME = "2026-07-17T09:00:00+00:00"


def _audit_stub(**kwargs: Any) -> dict[str, Any]:
    return {
        "artifact_hash": "audit_stub",
        "overall_status": kwargs.get("final_status", "REPORTED"),
        "recommendation_evaluator": kwargs.get("test_results", {}).get("recommendation_evaluator"),
    }


def _seed_graph(
    tmp_path: Path,
    *,
    recommendation_overrides: dict[str, Any] | None = None,
    audit_builder: Any = _audit_stub,
) -> tuple[RecommendationEvaluator, str, RecommendationEvaluationStore]:
    recommendation_store = RecommendationStore(recommendation_path=tmp_path / "recommendation_governance.jsonl")
    confidence_store = StatisticalConfidenceStore(confidence_path=tmp_path / "statistical_confidence.jsonl")
    attribution_store = CausalAttributionStore(attribution_path=tmp_path / "causal_attribution.jsonl")
    decision_store = DecisionMemoryStore(memory_path=tmp_path / "decision_memory.jsonl")
    evaluation_store = RecommendationEvaluationStore(evaluation_path=tmp_path / "recommendation_evaluation.jsonl")

    decision_record = build_decision_record(
        build_decision_payload(),
        created_by="tester",
        source_module="tests.test_recommendation_evaluator",
        source_version="1.0",
        created_at=BASE_TIME,
        decision_timestamp=BASE_TIME,
    )
    decision_store.append_decision(
        decision_record,
        created_by="tester",
        source_module="tests.test_recommendation_evaluator",
        source_version="1.0",
        created_at=BASE_TIME,
        decision_timestamp=BASE_TIME,
    )

    confidence_record = build_statistical_confidence_record(
        base_confidence_payload(
            experiment_id="exp_001",
            evaluation_id="evr_001",
        ),
        created_by="tester",
        source_module="tests.test_recommendation_evaluator",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    confidence_store.append_confidence_event(
        confidence_record,
        created_by="tester",
        source_module="tests.test_recommendation_evaluator",
        source_version="1.0",
        created_at=BASE_TIME,
    )

    attribution_record = build_causal_attribution_record(
        base_attribution_payload(
            experiment_id="exp_001",
            evaluation_id="evr_001",
            confidence_id=confidence_record["confidence_id"],
            decision_id=decision_record["decision_id"],
            learning_record_id="lr_001",
            outcome_record_id="otr_001",
        ),
        created_by="tester",
        source_module="tests.test_recommendation_evaluator",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    attribution_store.append_attribution_event(
        attribution_record,
        created_by="tester",
        source_module="tests.test_recommendation_evaluator",
        source_version="1.0",
        created_at=BASE_TIME,
    )

    recommendation_payload = base_recommendation_payload()
    recommendation_payload.update(
        {
            "decision_id": decision_record["decision_id"],
            "confidence_id": confidence_record["confidence_id"],
            "attribution_record_id": attribution_record["attribution_record_id"],
            "learning_record_id": "lr_001",
            "outcome_record_id": "otr_001",
        }
    )
    if recommendation_overrides:
        recommendation_payload.update(recommendation_overrides)

    append_result = recommendation_store.append_recommendation_event(
        recommendation_payload,
        created_by="tester",
        source_module="tests.test_recommendation_evaluator",
        source_version="1.0",
        created_at=BASE_TIME,
    )

    evaluator = RecommendationEvaluator(
        recommendation_store=recommendation_store,
        confidence_store=confidence_store,
        attribution_store=attribution_store,
        decision_memory_store=decision_store,
        evaluation_store=evaluation_store,
        repo_root=Path(__file__).resolve().parents[1],
        created_by="tester",
        source_module="tests.test_recommendation_evaluator",
        source_version="a3.2",
        audit_builder=audit_builder,
    )
    return evaluator, append_result.recommendation_record_id, evaluation_store


def test_successful_orchestration(tmp_path: Path) -> None:
    evaluator, recommendation_id, _store = _seed_graph(tmp_path)
    result = evaluator.evaluate_recommendation(recommendation_id, created_at=BASE_TIME)
    assert result.append_result.appended is True
    assert result.evaluation_record["recommendation_id"] == recommendation_id
    assert result.evaluation_record["human_review_required"] is True
    assert result.offline_only is True
    assert result.advisory_only is True


def test_missing_recommendation_fails_closed(tmp_path: Path) -> None:
    evaluator, _recommendation_id, _store = _seed_graph(tmp_path)
    with pytest.raises(RecommendationEvaluatorError, match="missing_recommendation"):
        evaluator.evaluate_recommendation("rcr_missing", created_at=BASE_TIME)


def test_missing_confidence_fails_closed(tmp_path: Path) -> None:
    evaluator, recommendation_id, _store = _seed_graph(tmp_path, recommendation_overrides={"confidence_id": "scid_missing"})
    with pytest.raises(RecommendationEvaluatorError, match="missing_confidence"):
        evaluator.evaluate_recommendation(recommendation_id, created_at=BASE_TIME)


def test_missing_attribution_fails_closed(tmp_path: Path) -> None:
    evaluator, recommendation_id, _store = _seed_graph(
        tmp_path,
        recommendation_overrides={"attribution_record_id": "car_missing"},
    )
    with pytest.raises(RecommendationEvaluatorError, match="missing_attribution"):
        evaluator.evaluate_recommendation(recommendation_id, created_at=BASE_TIME)


def test_missing_decision_memory_fails_closed(tmp_path: Path) -> None:
    evaluator, recommendation_id, _store = _seed_graph(
        tmp_path,
        recommendation_overrides={"decision_id": "dec_missing"},
    )
    with pytest.raises(RecommendationEvaluatorError, match="missing_decision_memory"):
        evaluator.evaluate_recommendation(recommendation_id, created_at=BASE_TIME)


def test_invalid_schema_fails_closed(tmp_path: Path) -> None:
    evaluator, recommendation_id, _store = _seed_graph(tmp_path)
    confidence_path = tmp_path / "statistical_confidence.jsonl"
    text = confidence_path.read_text(encoding="utf-8")
    confidence_path.write_text(text.replace('"schema_version":"v1"', '"schema_version":"v2"', 1), encoding="utf-8")
    with pytest.raises(StatisticalConfidenceCorruptionError):
        evaluator.evaluate_recommendation(recommendation_id, created_at=BASE_TIME)


def test_blocked_lineage_yields_blocked_evaluation(tmp_path: Path) -> None:
    evaluator, recommendation_id, _store = _seed_graph(tmp_path, recommendation_overrides={"lineage_complete": False})
    result = evaluator.evaluate_recommendation(recommendation_id, created_at=BASE_TIME)
    assert result.evaluation_record["evaluation_state"] == "blocked"
    assert "incomplete_lineage" in result.evaluation_record["blocking_reasons"]


def test_deterministic_replay(tmp_path: Path) -> None:
    evaluator, recommendation_id, store = _seed_graph(tmp_path)
    evaluator.evaluate_recommendation(recommendation_id, created_at=BASE_TIME)
    first_projection, first_diag = store.replay()
    second_projection, second_diag = store.replay()
    assert first_projection == second_projection
    assert first_diag == second_diag


def test_append_only_guarantee(tmp_path: Path) -> None:
    evaluator, recommendation_id, store = _seed_graph(tmp_path)
    first = evaluator.evaluate_recommendation(recommendation_id, created_at=BASE_TIME)
    second = evaluator.evaluate_recommendation(recommendation_id, created_at=BASE_TIME)
    assert first.append_result.appended is True
    assert second.append_result.appended is False
    assert second.append_result.duplicate is True
    assert len(store.get_rows()) == 1


def test_audit_invocation(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []

    def _capture_audit(**kwargs: Any) -> dict[str, Any]:
        calls.append(dict(kwargs))
        return {"artifact_hash": "audit_capture", "overall_status": kwargs.get("final_status", "REPORTED")}

    evaluator, recommendation_id, _store = _seed_graph(tmp_path, audit_builder=_capture_audit)
    evaluator.evaluate_recommendation(recommendation_id, created_at=BASE_TIME)
    assert len(calls) == 1
    assert calls[0]["test_results"]["recommendation_evaluator"] == "PASS"


def test_projection_refresh(tmp_path: Path) -> None:
    evaluator, recommendation_id, _store = _seed_graph(tmp_path)
    result = evaluator.evaluate_recommendation(recommendation_id, created_at=BASE_TIME)
    assert recommendation_id in result.projection["latest_by_recommendation_id"]


def test_repeated_evaluation_determinism(tmp_path: Path) -> None:
    evaluator, recommendation_id, _store = _seed_graph(tmp_path)
    first = evaluator.evaluate_recommendation(recommendation_id, created_at=BASE_TIME)
    second = evaluator.evaluate_recommendation(recommendation_id, created_at=BASE_TIME)
    assert first.evaluation_record["evaluation_id"] == second.evaluation_record["evaluation_id"]
    assert first.evaluation_record["evaluation_fingerprint"] == second.evaluation_record["evaluation_fingerprint"]


def test_offline_guarantee(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evaluator, recommendation_id, _store = _seed_graph(tmp_path)

    def _deny_socket(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("network access is not allowed")

    monkeypatch.setattr(socket, "socket", _deny_socket)
    result = evaluator.evaluate_recommendation(recommendation_id, created_at=BASE_TIME)
    assert result.offline_only is True


def test_no_runtime_mutation(tmp_path: Path) -> None:
    evaluator, recommendation_id, _store = _seed_graph(tmp_path)
    result = evaluator.evaluate_recommendation(recommendation_id, created_at=BASE_TIME)
    evidence_summary = result.evaluation_record["evidence_summary"]
    forbidden = {"deploy", "restart", "upload", "schedule", "apply", "execute", "mutate"}
    assert all(key not in evidence_summary for key in forbidden)


def test_no_deployment_interaction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evaluator, recommendation_id, _store = _seed_graph(tmp_path)

    def _deny_subprocess(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("subprocess access is not expected in evaluator")

    monkeypatch.setattr(subprocess, "run", _deny_subprocess)
    result = evaluator.evaluate_recommendation(recommendation_id, created_at=BASE_TIME)
    assert result.evaluation_record["human_review_required"] is True
