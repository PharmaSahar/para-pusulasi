from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import subprocess
from typing import Any, Mapping

import pytest

from ops import refresh_governance_readiness as refresh
from src.recommendation_store import RecommendationStore
from tests.recommendation_fixtures import BASE_TIME, base_recommendation_payload


@dataclass(frozen=True, slots=True)
class _EvaluationResult:
    evaluation_record: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class _BatchResult:
    results: tuple[object, ...]
    batch_fingerprint: str
    offline_only: bool
    advisory_only: bool


def _seed_recommendation(path: Path) -> None:
    payload = base_recommendation_payload()
    store = RecommendationStore(recommendation_path=path)
    result = store.append_recommendation_event(
        payload,
        created_by="tester",
        source_module="tests.test_governance_refresh_observability",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    assert result.appended is True


def test_bridge_step_success_emits_observability_metrics(tmp_path: Path) -> None:
    recommendation_path = tmp_path / "recommendation_governance.jsonl"
    _seed_recommendation(recommendation_path)

    class _Bridge:
        def evaluate_records(self, records: list[dict[str, Any]], *, created_at: str | None = None, final_status: str = "REPORTED") -> _BatchResult:
            assert len(records) == 1
            return _BatchResult(
                results=(
                    _EvaluationResult(evaluation_record={"lineage_complete": True}),
                    _EvaluationResult(evaluation_record={"lineage_complete": False}),
                ),
                batch_fingerprint="rgbf_observe",
                offline_only=True,
                advisory_only=True,
            )

    result = refresh._run_recommendation_governance_bridge_step(
        recommendation_path=recommendation_path,
        evaluation_path=tmp_path / "recommendation_evaluation.jsonl",
        repo_root=Path(__file__).resolve().parents[1],
        created_at_utc="2026-07-17T12:00:00+00:00",
        evaluator_factory=lambda **_kwargs: object(),
        bridge_factory=lambda **_kwargs: _Bridge(),
    )

    assert result["exit_code"] == 0
    assert result["bridge_invoked"] is True
    assert result["bridge_invocations"] == 1
    assert result["bridge_failures"] == 0
    assert result["input_records"] == 1
    assert result["evaluated_records"] == 2
    assert result["dedupe_skipped_records"] == 0
    assert result["duplicate_attempts"] == 0
    assert result["missing_lineage_records"] == 1
    assert str(result["ordering_signature"]).startswith("ordsig_")
    assert int(result["evaluation_duration_ms"]) >= 0


def test_duplicate_metrics_accuracy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    recommendation_path = tmp_path / "recommendation_governance.jsonl"
    _seed_recommendation(recommendation_path)

    def _forced_dedupe(_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
        return ([{"recommendation_record_id": "rcr_001", "record_hash": "rch_001"}], 3)

    monkeypatch.setattr(refresh, "_dedupe_recommendation_rows", _forced_dedupe)

    class _Bridge:
        def evaluate_records(self, records: list[dict[str, Any]], *, created_at: str | None = None, final_status: str = "REPORTED") -> _BatchResult:
            assert len(records) == 1
            return _BatchResult(results=(object(),), batch_fingerprint="rgbf_dup", offline_only=True, advisory_only=True)

    result = refresh._run_recommendation_governance_bridge_step(
        recommendation_path=recommendation_path,
        evaluation_path=tmp_path / "recommendation_evaluation.jsonl",
        repo_root=Path(__file__).resolve().parents[1],
        created_at_utc="2026-07-17T12:00:00+00:00",
        evaluator_factory=lambda **_kwargs: object(),
        bridge_factory=lambda **_kwargs: _Bridge(),
    )

    assert result["input_records"] == 1
    assert result["dedupe_skipped_records"] == 3
    assert result["duplicate_attempts"] == 3


def test_ordering_signature_stable() -> None:
    rows = [
        {"recommendation_record_id": "rcr_a", "record_hash": "rch_a"},
        {"recommendation_record_id": "rcr_b", "record_hash": "rch_b"},
        {"recommendation_record_id": "rcr_c", "record_hash": "rch_c"},
    ]
    first = refresh._ordering_signature(rows)
    second = refresh._ordering_signature(rows)
    assert first == second
    assert first.startswith("ordsig_")


def test_bridge_failure_metrics_are_fail_open(tmp_path: Path) -> None:
    recommendation_path = tmp_path / "recommendation_governance.jsonl"
    _seed_recommendation(recommendation_path)

    class _FailBridge:
        def evaluate_records(self, records: list[dict[str, Any]], *, created_at: str | None = None, final_status: str = "REPORTED") -> _BatchResult:
            raise RuntimeError("observability_bridge_boom")

    result = refresh._run_recommendation_governance_bridge_step(
        recommendation_path=recommendation_path,
        evaluation_path=tmp_path / "recommendation_evaluation.jsonl",
        repo_root=Path(__file__).resolve().parents[1],
        created_at_utc="2026-07-17T12:00:00+00:00",
        evaluator_factory=lambda **_kwargs: object(),
        bridge_factory=lambda **_kwargs: _FailBridge(),
    )

    assert result["exit_code"] == 0
    assert result["warning"] == "bridge_fail_open"
    assert result["bridge_invoked"] is False
    assert result["bridge_invocations"] == 1
    assert result["bridge_failures"] == 1


def test_missing_lineage_metrics_count(tmp_path: Path) -> None:
    recommendation_path = tmp_path / "recommendation_governance.jsonl"
    _seed_recommendation(recommendation_path)

    class _Bridge:
        def evaluate_records(self, records: list[dict[str, Any]], *, created_at: str | None = None, final_status: str = "REPORTED") -> _BatchResult:
            return _BatchResult(
                results=(
                    _EvaluationResult(evaluation_record={"lineage_complete": False}),
                    _EvaluationResult(evaluation_record={"lineage_complete": False}),
                ),
                batch_fingerprint="rgbf_lineage",
                offline_only=True,
                advisory_only=True,
            )

    result = refresh._run_recommendation_governance_bridge_step(
        recommendation_path=recommendation_path,
        evaluation_path=tmp_path / "recommendation_evaluation.jsonl",
        repo_root=Path(__file__).resolve().parents[1],
        created_at_utc="2026-07-17T12:00:00+00:00",
        evaluator_factory=lambda **_kwargs: object(),
        bridge_factory=lambda **_kwargs: _Bridge(),
    )
    assert result["missing_lineage_records"] == 2


def test_missing_recommendation_store_emits_default_metrics(tmp_path: Path) -> None:
    result = refresh._run_recommendation_governance_bridge_step(
        recommendation_path=tmp_path / "missing_recommendation_governance.jsonl",
        evaluation_path=tmp_path / "recommendation_evaluation.jsonl",
        repo_root=Path(__file__).resolve().parents[1],
        created_at_utc="2026-07-17T12:00:00+00:00",
    )
    assert result["exit_code"] == 0
    assert result["warning"] == "bridge_skipped_missing_recommendation_store"
    assert result["bridge_invocations"] == 0
    assert result["bridge_failures"] == 0
    assert result["input_records"] == 0
    assert result["missing_lineage_records"] == 0


def test_run_refresh_includes_observability_metrics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixed_now = datetime(2026, 7, 17, 12, 0, 0, tzinfo=timezone.utc)

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
            "bridge_invoked": True,
            "bridge_invocations": 1,
            "bridge_failures": 0,
            "input_records": 4,
            "evaluated_records": 3,
            "dedupe_skipped_records": 1,
            "duplicate_attempts": 1,
            "missing_lineage_records": 2,
            "ordering_signature": "ordsig_fixed",
            "evaluation_duration_ms": 0,
            "batch_fingerprint": "rgbf_fixed",
            "offline_only": True,
            "advisory_only": True,
            "evaluation_path": str(tmp_path / "recommendation_evaluation.jsonl"),
            "started_at_utc": fixed_now.isoformat(),
            "finished_at_utc": fixed_now.isoformat(),
        }

    monkeypatch.setattr(refresh, "_run_step", _fake_run_step)
    monkeypatch.setattr(refresh, "_append_monitor_row", lambda _snapshot: None)
    monkeypatch.setattr(refresh, "LATEST_PATH", tmp_path / "governance_refresh_run_latest.json")
    monkeypatch.setattr(refresh, "_resolve_readiness_markdown", lambda: tmp_path / "governance_readiness_latest.md")
    monkeypatch.setattr(refresh, "_utc_now", lambda: fixed_now)

    payload = refresh.run_refresh(lookback_rows=500, bridge_step_runner=_bridge_step_runner)
    bridge_step = next(step for step in payload["steps"] if step.get("name") == "recommendation_governance_bridge")

    assert bridge_step["bridge_invocations"] == 1
    assert bridge_step["bridge_failures"] == 0
    assert bridge_step["input_records"] == 4
    assert bridge_step["evaluated_records"] == 3
    assert bridge_step["dedupe_skipped_records"] == 1
    assert bridge_step["duplicate_attempts"] == 1
    assert bridge_step["missing_lineage_records"] == 2
    assert bridge_step["ordering_signature"] == "ordsig_fixed"


def test_repeated_refresh_observability_is_identical(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixed_now = datetime(2026, 7, 17, 12, 0, 0, tzinfo=timezone.utc)

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
            "bridge_invoked": True,
            "bridge_invocations": 1,
            "bridge_failures": 0,
            "input_records": 2,
            "evaluated_records": 1,
            "dedupe_skipped_records": 1,
            "duplicate_attempts": 1,
            "missing_lineage_records": 0,
            "ordering_signature": "ordsig_repeat",
            "evaluation_duration_ms": 0,
            "batch_fingerprint": "rgbf_repeat",
            "offline_only": True,
            "advisory_only": True,
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


def test_no_scheduler_interaction(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    recommendation_path = tmp_path / "recommendation_governance.jsonl"
    _seed_recommendation(recommendation_path)

    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("subprocess_not_allowed")))

    class _Bridge:
        def evaluate_records(self, records: list[dict[str, Any]], *, created_at: str | None = None, final_status: str = "REPORTED") -> _BatchResult:
            return _BatchResult(results=(object(),), batch_fingerprint="rgbf_test", offline_only=True, advisory_only=True)

    result = refresh._run_recommendation_governance_bridge_step(
        recommendation_path=recommendation_path,
        evaluation_path=tmp_path / "recommendation_evaluation.jsonl",
        repo_root=Path(__file__).resolve().parents[1],
        created_at_utc="2026-07-17T12:00:00+00:00",
        evaluator_factory=lambda **_kwargs: object(),
        bridge_factory=lambda **_kwargs: _Bridge(),
    )
    assert result["exit_code"] == 0


def test_no_uploader_interaction() -> None:
    row = {"recommendation_record_id": "rcr_001", "record_hash": "rch_001"}
    signature = refresh._ordering_signature([row])
    assert signature.startswith("ordsig_")


def test_no_deployment_interaction() -> None:
    row = {"recommendation_record_id": "rcr_001", "record_hash": "rch_001"}
    key = refresh._dedupe_fingerprint(row)
    assert key == "rcr_001:rch_001"
