from __future__ import annotations

import json
import socket
from pathlib import Path

from src.experiment_evaluation_store import ExperimentEvaluationStore
from src.run_experiment_evaluation_audit import main
from tests.experiment_evaluation_fixtures import BASE_TIME, base_evaluation_payload


def _seed(path: Path) -> None:
    store = ExperimentEvaluationStore(evaluation_path=path)
    record = store.append_evaluation_event(
        base_evaluation_payload(),
        created_by="tester",
        source_module="tests.test_experiment_evaluation_audit",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    assert record.appended is True


def test_audit_runner_is_deterministic(tmp_path: Path) -> None:
    evaluation_path = tmp_path / "experiment_evaluation.jsonl"
    artifact_path = tmp_path / "assessment.json"
    _seed(evaluation_path)

    args = [
        "--evaluation-path",
        str(evaluation_path),
        "--repo-root",
        str(Path(__file__).resolve().parents[1]),
        "--artifact-path",
        str(artifact_path),
        "--generated-at",
        "2026-07-15T12:30:00+00:00",
        "--final-status",
        "VALIDATED",
        "--test-result",
        "targeted=PASS",
    ]

    assert main(args) == 0
    first = artifact_path.read_text(encoding="utf-8")
    assert main(args) == 0
    second = artifact_path.read_text(encoding="utf-8")
    assert first == second

    payload = json.loads(first)
    assert payload["sprint"] == "SPRINT_5"
    assert payload["artifact_hash"]
    assert payload["overall_status"] == "VALIDATED"
    assert payload["validation_summary"]["state_counts"]["VALIDATED_RESULT"] == 1


def test_audit_runner_offline(tmp_path: Path, monkeypatch) -> None:
    evaluation_path = tmp_path / "experiment_evaluation.jsonl"
    artifact_path = tmp_path / "assessment.json"
    _seed(evaluation_path)

    def _deny_socket(*_args, **_kwargs):
        raise AssertionError("network access is not allowed")

    monkeypatch.setattr(socket, "socket", _deny_socket)
    assert main([
        "--evaluation-path",
        str(evaluation_path),
        "--repo-root",
        str(Path(__file__).resolve().parents[1]),
        "--artifact-path",
        str(artifact_path),
    ]) == 0
    assert artifact_path.exists()
