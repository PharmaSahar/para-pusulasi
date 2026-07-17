from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from ops import refresh_governance_readiness as refresh
from src.recommendation_store import RecommendationStore
from tests.recommendation_fixtures import BASE_TIME, base_recommendation_payload


@dataclass(frozen=True, slots=True)
class _BatchResult:
    results: tuple[object, ...]
    batch_fingerprint: str
    offline_only: bool
    advisory_only: bool


def _seed_recommendation(path: Path) -> None:
    store = RecommendationStore(recommendation_path=path)
    result = store.append_recommendation_event(
        base_recommendation_payload(),
        created_by="tester",
        source_module="tests.test_governance_refresh_recommendation_bridge",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    assert result.appended is True


def test_bridge_step_successful_invocation(tmp_path: Path) -> None:
    recommendation_path = tmp_path / "recommendation_governance.jsonl"
    evaluation_path = tmp_path / "recommendation_evaluation.jsonl"
    _seed_recommendation(recommendation_path)

    evaluator_calls: list[dict[str, Any]] = []
    bridge_calls: list[dict[str, Any]] = []

    def _evaluator_factory(**kwargs: Any) -> object:
        evaluator_calls.append(dict(kwargs))
        return object()

    class _Bridge:
        def evaluate_records(self, records: list[dict[str, Any]], *, created_at: str | None = None, final_status: str = "REPORTED") -> _BatchResult:
            bridge_calls.append(
                {
                    "records": len(records),
                    "created_at": created_at,
                    "final_status": final_status,
                }
            )
            return _BatchResult(results=(object(),), batch_fingerprint="rgbf_test", offline_only=True, advisory_only=True)

    def _bridge_factory(*, evaluator: object) -> _Bridge:
        assert evaluator is not None
        return _Bridge()

    result = refresh._run_recommendation_governance_bridge_step(
        recommendation_path=recommendation_path,
        evaluation_path=evaluation_path,
        repo_root=Path(__file__).resolve().parents[1],
        created_at_utc="2026-07-17T12:00:00+00:00",
        evaluator_factory=_evaluator_factory,
        bridge_factory=_bridge_factory,
    )

    assert result["exit_code"] == 0
    assert result["bridge_invoked"] is True
    assert result["evaluated_records"] == 1
    assert result["batch_fingerprint"] == "rgbf_test"
    assert evaluator_calls
    assert bridge_calls == [{"records": 1, "created_at": "2026-07-17T12:00:00+00:00", "final_status": "REPORTED"}]


def test_bridge_skipped_when_no_recommendation_records_exist(tmp_path: Path) -> None:
    result = refresh._run_recommendation_governance_bridge_step(
        recommendation_path=tmp_path / "missing_recommendation_governance.jsonl",
        evaluation_path=tmp_path / "recommendation_evaluation.jsonl",
        repo_root=Path(__file__).resolve().parents[1],
        created_at_utc="2026-07-17T12:00:00+00:00",
    )
    assert result["exit_code"] == 0
    assert result["bridge_invoked"] is False
    assert result["warning"] == "bridge_skipped_missing_recommendation_store"


def test_bridge_fail_open_on_evaluator_exception(tmp_path: Path) -> None:
    recommendation_path = tmp_path / "recommendation_governance.jsonl"
    evaluation_path = tmp_path / "recommendation_evaluation.jsonl"
    _seed_recommendation(recommendation_path)

    class _FailBridge:
        def evaluate_records(self, records: list[dict[str, Any]], *, created_at: str | None = None, final_status: str = "REPORTED") -> _BatchResult:
            raise RuntimeError("bridge_boom")

    result = refresh._run_recommendation_governance_bridge_step(
        recommendation_path=recommendation_path,
        evaluation_path=evaluation_path,
        repo_root=Path(__file__).resolve().parents[1],
        created_at_utc="2026-07-17T12:00:00+00:00",
        evaluator_factory=lambda **_kwargs: object(),
        bridge_factory=lambda **_kwargs: _FailBridge(),
    )

    assert result["exit_code"] == 0
    assert result["warning"] == "bridge_fail_open"
    assert "bridge_boom" in result["stderr_tail"]


def test_run_refresh_preserves_outputs_and_fail_open_bridge(tmp_path: Path, monkeypatch) -> None:
    def _fake_run_step(command, *, required, fail_open, fallback_artifact=None):
        return {
            "name": Path(command[1]).stem if len(command) > 1 else "unknown",
            "command": command,
            "exit_code": 0,
            "required": required,
            "fail_open": fail_open,
            "started_at_utc": "2026-07-17T00:00:00+00:00",
            "finished_at_utc": "2026-07-17T00:00:01+00:00",
        }

    def _bridge_step_runner(**_kwargs: Any) -> dict[str, Any]:
        return {
            "exit_code": 0,
            "warning": "bridge_fail_open",
            "bridge_invoked": False,
            "evaluated_records": 0,
            "evaluation_path": str(tmp_path / "recommendation_evaluation.jsonl"),
            "started_at_utc": "2026-07-17T00:00:00+00:00",
            "finished_at_utc": "2026-07-17T00:00:01+00:00",
        }

    monkeypatch.setattr(refresh, "_run_step", _fake_run_step)
    monkeypatch.setattr(refresh, "_append_monitor_row", lambda _snapshot: None)
    monkeypatch.setattr(refresh, "LATEST_PATH", tmp_path / "governance_refresh_run_latest.json")
    monkeypatch.setattr(refresh, "_resolve_readiness_markdown", lambda: tmp_path / "governance_readiness_latest.md")

    payload = refresh.run_refresh(lookback_rows=500, bridge_step_runner=_bridge_step_runner)

    assert payload["ok"] is True
    assert "optional_step_warning:recommendation_governance_bridge:bridge_fail_open" in payload["warnings"]
    assert "strict_evidence_bridge" in payload["artifacts"]
    assert "content_platform_recommendations" in payload["artifacts"]


def test_run_refresh_deterministic_repeated_execution(tmp_path: Path, monkeypatch) -> None:
    fixed_now = datetime(2026, 7, 17, 0, 0, 0, tzinfo=timezone.utc)

    def _fake_run_step(command, *, required, fail_open, fallback_artifact=None):
        return {
            "name": Path(command[1]).stem if len(command) > 1 else "unknown",
            "command": command,
            "exit_code": 0,
            "required": required,
            "fail_open": fail_open,
            "started_at_utc": fixed_now.isoformat(),
            "finished_at_utc": fixed_now.isoformat(),
        }

    def _bridge_step_runner(**_kwargs: Any) -> dict[str, Any]:
        return {
            "exit_code": 0,
            "bridge_invoked": False,
            "evaluated_records": 0,
            "evaluation_path": str(tmp_path / "recommendation_evaluation.jsonl"),
            "started_at_utc": fixed_now.isoformat(),
            "finished_at_utc": fixed_now.isoformat(),
        }

    monkeypatch.setattr(refresh, "_run_step", _fake_run_step)
    monkeypatch.setattr(refresh, "_append_monitor_row", lambda _snapshot: None)
    monkeypatch.setattr(refresh, "LATEST_PATH", tmp_path / "governance_refresh_run_latest.json")
    monkeypatch.setattr(refresh, "_resolve_readiness_markdown", lambda: tmp_path / "governance_readiness_latest.md")
    monkeypatch.setattr(refresh, "_utc_now", lambda: fixed_now)

    first = refresh.run_refresh(lookback_rows=500, bridge_step_runner=_bridge_step_runner)
    second = refresh.run_refresh(lookback_rows=500, bridge_step_runner=_bridge_step_runner)
    assert first == second


def test_no_scheduler_uploader_deployment_interaction_in_bridge_step(tmp_path: Path, monkeypatch) -> None:
    recommendation_path = tmp_path / "recommendation_governance.jsonl"
    evaluation_path = tmp_path / "recommendation_evaluation.jsonl"
    _seed_recommendation(recommendation_path)

    monkeypatch.setattr(refresh.subprocess, "run", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("subprocess_not_allowed")))

    class _Bridge:
        def evaluate_records(self, records: list[dict[str, Any]], *, created_at: str | None = None, final_status: str = "REPORTED") -> _BatchResult:
            return _BatchResult(results=(object(),), batch_fingerprint="rgbf_test", offline_only=True, advisory_only=True)

    result = refresh._run_recommendation_governance_bridge_step(
        recommendation_path=recommendation_path,
        evaluation_path=evaluation_path,
        repo_root=Path(__file__).resolve().parents[1],
        created_at_utc="2026-07-17T12:00:00+00:00",
        evaluator_factory=lambda **_kwargs: object(),
        bridge_factory=lambda **_kwargs: _Bridge(),
    )
    assert result["exit_code"] == 0


def test_dependency_injection_behavior(tmp_path: Path) -> None:
    recommendation_path = tmp_path / "recommendation_governance.jsonl"
    evaluation_path = tmp_path / "recommendation_evaluation.jsonl"
    _seed_recommendation(recommendation_path)

    call_trace: list[str] = []

    def _evaluator_factory(**_kwargs: Any) -> object:
        call_trace.append("evaluator_factory")
        return object()

    class _Bridge:
        def evaluate_records(self, records: list[dict[str, Any]], *, created_at: str | None = None, final_status: str = "REPORTED") -> _BatchResult:
            call_trace.append("bridge_evaluate")
            return _BatchResult(results=(object(),), batch_fingerprint="rgbf_test", offline_only=True, advisory_only=True)

    def _bridge_factory(*, evaluator: object) -> _Bridge:
        assert evaluator is not None
        call_trace.append("bridge_factory")
        return _Bridge()

    result = refresh._run_recommendation_governance_bridge_step(
        recommendation_path=recommendation_path,
        evaluation_path=evaluation_path,
        repo_root=Path(__file__).resolve().parents[1],
        created_at_utc="2026-07-17T12:00:00+00:00",
        evaluator_factory=_evaluator_factory,
        bridge_factory=_bridge_factory,
    )

    assert result["exit_code"] == 0
    assert call_trace == ["evaluator_factory", "bridge_factory", "bridge_evaluate"]
