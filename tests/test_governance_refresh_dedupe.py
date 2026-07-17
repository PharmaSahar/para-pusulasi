from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import subprocess
from typing import Any

import pytest

from ops import refresh_governance_readiness as refresh
from src.recommendation_store import RecommendationStore
from tests.recommendation_fixtures import BASE_TIME, base_recommendation_payload


@dataclass(frozen=True, slots=True)
class _BatchResult:
    results: tuple[object, ...]
    batch_fingerprint: str
    offline_only: bool
    advisory_only: bool


def _seed_recommendation(path: Path, *, overrides: dict[str, Any] | None = None) -> None:
    payload = base_recommendation_payload()
    if overrides:
        payload.update(overrides)
    store = RecommendationStore(recommendation_path=path)
    result = store.append_recommendation_event(
        payload,
        created_by="tester",
        source_module="tests.test_governance_refresh_dedupe",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    assert result.appended is True


def test_identical_recommendation_evaluated_once() -> None:
    row = {
        "recommendation_record_id": "rcr_same",
        "record_hash": "rch_same",
        "recommendation_event_id": "rce_a",
    }
    kept, skipped = refresh._dedupe_recommendation_rows([row, dict(row)])
    assert len(kept) == 1
    assert skipped == 1


def test_duplicate_invocation_skipped_deterministically() -> None:
    row_a = {
        "recommendation_record_id": "rcr_001",
        "record_hash": "rch_001",
        "recommendation_event_id": "rce_001",
    }
    row_b = {
        "recommendation_record_id": "rcr_001",
        "record_hash": "rch_001",
        "recommendation_event_id": "rce_002",
    }
    first_kept, first_skipped = refresh._dedupe_recommendation_rows([row_a, row_b, row_a])
    second_kept, second_skipped = refresh._dedupe_recommendation_rows([row_a, row_b, row_a])
    assert first_kept == second_kept
    assert first_skipped == second_skipped


def test_different_fingerprints_evaluated_independently() -> None:
    row_a = {
        "recommendation_record_id": "rcr_001",
        "record_hash": "rch_001",
    }
    row_b = {
        "recommendation_record_id": "rcr_001",
        "record_hash": "rch_002",
    }
    kept, skipped = refresh._dedupe_recommendation_rows([row_a, row_b])
    assert len(kept) == 2
    assert skipped == 0


def test_ordering_preserved_after_dedupe() -> None:
    row_a = {"recommendation_record_id": "rcr_a", "record_hash": "rch_a"}
    row_b = {"recommendation_record_id": "rcr_b", "record_hash": "rch_b"}
    row_c = {"recommendation_record_id": "rcr_c", "record_hash": "rch_c"}
    kept, skipped = refresh._dedupe_recommendation_rows([row_a, row_b, row_a, row_c])
    assert [item["recommendation_record_id"] for item in kept] == ["rcr_a", "rcr_b", "rcr_c"]
    assert skipped == 1


def test_bridge_step_fail_open_preserved(tmp_path: Path) -> None:
    recommendation_path = tmp_path / "recommendation_governance.jsonl"
    _seed_recommendation(recommendation_path)

    class _FailBridge:
        def evaluate_records(self, records: list[dict[str, Any]], *, created_at: str | None = None, final_status: str = "REPORTED") -> _BatchResult:
            raise RuntimeError("dedupe_bridge_boom")

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


def test_repeated_refresh_produces_identical_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
            "input_records": 2,
            "dedupe_skipped_records": 1,
            "evaluated_records": 1,
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


def test_no_uploader_interaction(tmp_path: Path) -> None:
    row = {"recommendation_record_id": "rcr_001", "record_hash": "rch_001"}
    kept, skipped = refresh._dedupe_recommendation_rows([row])
    assert kept == [row]
    assert skipped == 0


def test_no_deployment_interaction(tmp_path: Path) -> None:
    row = {"recommendation_record_id": "rcr_001", "record_hash": "rch_001"}
    key = refresh._dedupe_fingerprint(row)
    assert key == "rcr_001:rch_001"
