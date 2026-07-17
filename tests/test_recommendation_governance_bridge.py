from __future__ import annotations

from dataclasses import dataclass
import subprocess
import socket
from typing import Any

import pytest

from src.recommendation_governance_bridge import (
    RecommendationGovernanceBridge,
    RecommendationGovernanceBridgeError,
)
from tests.recommendation_fixtures import base_recommendation_payload


@dataclass(frozen=True, slots=True)
class _AppendResult:
    appended: bool
    duplicate: bool
    conflict: bool
    evaluation_id: str
    evaluation_event_id: str
    record_hash: str
    reason: str


@dataclass(frozen=True, slots=True)
class _EvaluationResult:
    evaluation_record: dict[str, Any]
    append_result: _AppendResult
    projection: dict[str, Any]
    audit_artifact: dict[str, Any]
    offline_only: bool
    advisory_only: bool


class _FakeEvaluator:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None, str]] = []

    def evaluate_recommendation(
        self,
        recommendation_id: str,
        *,
        created_at: str | None = None,
        final_status: str = "REPORTED",
    ) -> _EvaluationResult:
        self.calls.append((recommendation_id, created_at, final_status))
        return _EvaluationResult(
            evaluation_record={
                "evaluation_id": f"reid_{recommendation_id}",
                "recommendation_id": recommendation_id,
                "created_at": created_at or "2026-07-17T11:00:00+00:00",
                "final_status": final_status,
            },
            append_result=_AppendResult(
                appended=True,
                duplicate=False,
                conflict=False,
                evaluation_id=f"reid_{recommendation_id}",
                evaluation_event_id=f"ree_{recommendation_id}",
                record_hash=f"reh_{recommendation_id}",
                reason="appended",
            ),
            projection={
                "latest_by_recommendation_id": {
                    recommendation_id: {"evaluation_id": f"reid_{recommendation_id}"}
                }
            },
            audit_artifact={"overall_status": final_status, "recommendation_evaluator": "PASS"},
            offline_only=True,
            advisory_only=True,
        )


class _FailingEvaluator:
    def evaluate_recommendation(self, recommendation_id: str, *, created_at: str | None = None, final_status: str = "REPORTED") -> _EvaluationResult:
        raise RuntimeError(f"boom:{recommendation_id}")


def _record(record_id: str) -> dict[str, Any]:
    payload = base_recommendation_payload()
    payload["recommendation_record_id"] = record_id
    return payload


def test_normal_orchestration() -> None:
    evaluator = _FakeEvaluator()
    bridge = RecommendationGovernanceBridge(evaluator=evaluator)
    batch = bridge.evaluate_records([_record("rcr_002"), _record("rcr_001")], created_at="2026-07-17T12:00:00+00:00")
    assert [item.recommendation_record_id for item in batch.results] == ["rcr_001", "rcr_002"]
    assert batch.offline_only is True
    assert batch.advisory_only is True


def test_dependency_injection() -> None:
    evaluator = _FakeEvaluator()
    bridge = RecommendationGovernanceBridge(evaluator=evaluator)
    bridge.evaluate_records([_record("rcr_di")], final_status="VALIDATED")
    assert evaluator.calls == [("rcr_di", None, "VALIDATED")]


def test_evaluator_failure_propagation() -> None:
    bridge = RecommendationGovernanceBridge(evaluator=_FailingEvaluator())
    with pytest.raises(RuntimeError, match="boom:rcr_fail"):
        bridge.evaluate_records([_record("rcr_fail")])


def test_deterministic_replay() -> None:
    evaluator = _FakeEvaluator()
    bridge = RecommendationGovernanceBridge(evaluator=evaluator)
    first = bridge.evaluate_records([_record("rcr_001")], created_at="2026-07-17T13:00:00+00:00")
    second = bridge.evaluate_records([_record("rcr_001")], created_at="2026-07-17T13:00:00+00:00")
    assert first == second
    assert first.batch_fingerprint == second.batch_fingerprint


def test_immutable_results() -> None:
    bridge = RecommendationGovernanceBridge(evaluator=_FakeEvaluator())
    batch = bridge.evaluate_records([_record("rcr_immutable")])
    with pytest.raises(TypeError):
        batch.results[0].evaluation_record["evaluation_id"] = "tampered"


def test_repeated_execution_consistency() -> None:
    bridge = RecommendationGovernanceBridge(evaluator=_FakeEvaluator())
    a = bridge.evaluate_records([_record("rcr_repeat")], created_at="2026-07-17T14:00:00+00:00")
    b = bridge.evaluate_records([_record("rcr_repeat")], created_at="2026-07-17T14:00:00+00:00")
    assert a.results[0].append_result == b.results[0].append_result
    assert a.results[0].evaluation_record == b.results[0].evaluation_record


def test_offline_guarantee(monkeypatch: pytest.MonkeyPatch) -> None:
    def _deny_socket(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("network access is not allowed")

    monkeypatch.setattr(socket, "socket", _deny_socket)
    bridge = RecommendationGovernanceBridge(evaluator=_FakeEvaluator())
    batch = bridge.evaluate_records([_record("rcr_offline")])
    assert batch.offline_only is True


def test_no_scheduler_interaction(monkeypatch: pytest.MonkeyPatch) -> None:
    def _deny_subprocess(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("subprocess access is not allowed")

    monkeypatch.setattr(subprocess, "run", _deny_subprocess)
    bridge = RecommendationGovernanceBridge(evaluator=_FakeEvaluator())
    bridge.evaluate_records([_record("rcr_scheduler")])


def test_no_uploader_interaction(monkeypatch: pytest.MonkeyPatch) -> None:
    def _deny_subprocess(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("subprocess access is not allowed")

    monkeypatch.setattr(subprocess, "run", _deny_subprocess)
    bridge = RecommendationGovernanceBridge(evaluator=_FakeEvaluator())
    bridge.evaluate_records([_record("rcr_uploader")])


def test_no_deployment_interaction(monkeypatch: pytest.MonkeyPatch) -> None:
    def _deny_subprocess(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("subprocess access is not allowed")

    monkeypatch.setattr(subprocess, "run", _deny_subprocess)
    bridge = RecommendationGovernanceBridge(evaluator=_FakeEvaluator())
    bridge.evaluate_records([_record("rcr_deploy")])


def test_no_runtime_mutation() -> None:
    bridge = RecommendationGovernanceBridge(evaluator=_FakeEvaluator())
    original = _record("rcr_runtime")
    snapshot = dict(original)
    bridge.evaluate_records([original], created_at="2026-07-17T15:00:00+00:00")
    assert original == snapshot


def test_missing_recommendation_record_id_fails_closed() -> None:
    bridge = RecommendationGovernanceBridge(evaluator=_FakeEvaluator())
    with pytest.raises(RecommendationGovernanceBridgeError, match="missing_recommendation_record_id"):
        bridge.evaluate_records([{"recommendation_record_id": ""}])
