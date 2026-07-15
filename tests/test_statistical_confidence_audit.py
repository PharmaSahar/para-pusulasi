from __future__ import annotations

import json
import socket
from pathlib import Path

from src.run_statistical_confidence_audit import main
from src.statistical_confidence_store import StatisticalConfidenceStore
from tests.statistical_confidence_fixtures import BASE_TIME, base_confidence_payload


def _seed(path: Path) -> None:
    store = StatisticalConfidenceStore(confidence_path=path)
    record = store.append_confidence_event(
        base_confidence_payload(),
        created_by="tester",
        source_module="tests.test_statistical_confidence_audit",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    assert record.appended is True


def test_audit_runner_is_deterministic(tmp_path: Path) -> None:
    confidence_path = tmp_path / "statistical_confidence.jsonl"
    artifact_path = tmp_path / "assessment.json"
    _seed(confidence_path)

    args = [
        "--confidence-path",
        str(confidence_path),
        "--repo-root",
        str(Path(__file__).resolve().parents[1]),
        "--artifact-path",
        str(artifact_path),
        "--generated-at",
        "2026-07-15T13:30:00+00:00",
        "--final-status",
        "CONDITIONALLY_VALIDATED",
        "--test-result",
        "targeted=PASS",
    ]

    assert main(args) == 0
    first = artifact_path.read_text(encoding="utf-8")
    assert main(args) == 0
    second = artifact_path.read_text(encoding="utf-8")
    assert first == second

    payload = json.loads(first)
    assert payload["sprint"] == "SPRINT_6"
    assert payload["artifact_hash"]
    assert payload["overall_status"] == "CONDITIONALLY_VALIDATED"
    assert payload["validation_summary"]["state_counts"]["STATISTICALLY_SUPPORTED"] == 1


def test_audit_runner_offline(tmp_path: Path, monkeypatch) -> None:
    confidence_path = tmp_path / "statistical_confidence.jsonl"
    artifact_path = tmp_path / "assessment.json"
    _seed(confidence_path)

    def _deny_socket(*_args, **_kwargs):
        raise AssertionError("network access is not allowed")

    monkeypatch.setattr(socket, "socket", _deny_socket)
    assert main([
        "--confidence-path",
        str(confidence_path),
        "--repo-root",
        str(Path(__file__).resolve().parents[1]),
        "--artifact-path",
        str(artifact_path),
    ]) == 0
    assert artifact_path.exists()
