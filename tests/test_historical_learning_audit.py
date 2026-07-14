from __future__ import annotations

import json
import socket
from pathlib import Path

from src.historical_learning_store import HistoricalLearningStore
from src.learning_record_contract import build_learning_record
from src.run_historical_learning_audit import main
from tests.learning_record_fixtures import BASE_TIME, base_learning_payload


def _seed(path: Path) -> None:
    store = HistoricalLearningStore(learning_path=path)
    record = build_learning_record(
        base_learning_payload(),
        created_by="tester",
        source_module="tests.test_historical_learning_audit",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    store.append_learning_event(
        record,
        created_by="tester",
        source_module="tests.test_historical_learning_audit",
        source_version="1.0",
        created_at=BASE_TIME,
    )


def test_audit_runner_is_deterministic(tmp_path: Path) -> None:
    learning_path = tmp_path / "historical_learning.jsonl"
    artifact_path = tmp_path / "assessment.json"
    _seed(learning_path)

    args = [
        "--learning-path",
        str(learning_path),
        "--repo-root",
        str(Path(__file__).resolve().parents[1]),
        "--artifact-path",
        str(artifact_path),
        "--generated-at",
        "2026-07-14T12:00:00+00:00",
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
    assert payload["sprint"] == "SPRINT_2"
    assert payload["artifact_hash"]
    assert payload["overall_status"] == "VALIDATED"


def test_audit_runner_offline(tmp_path: Path, monkeypatch) -> None:
    learning_path = tmp_path / "historical_learning.jsonl"
    artifact_path = tmp_path / "assessment.json"
    _seed(learning_path)

    def _deny_socket(*_args, **_kwargs):
        raise AssertionError("network access is not allowed")

    monkeypatch.setattr(socket, "socket", _deny_socket)
    assert main([
        "--learning-path",
        str(learning_path),
        "--repo-root",
        str(Path(__file__).resolve().parents[1]),
        "--artifact-path",
        str(artifact_path),
    ]) == 0
    assert artifact_path.exists()
