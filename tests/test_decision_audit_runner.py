from __future__ import annotations

import json
import socket
from pathlib import Path

from src.decision_contract import build_decision_record
from src.decision_memory import DecisionMemoryStore
from src.run_decision_memory_audit import main
from tests.decision_memory_fixtures import BASE_CREATED_AT, BASE_TIMESTAMP, build_decision_payload


def _seed_store(path: Path) -> None:
    store = DecisionMemoryStore(memory_path=path)
    record = build_decision_record(
        build_decision_payload(),
        created_by="tester",
        source_module="tests.test_decision_audit_runner",
        source_version="1.0",
        created_at=BASE_CREATED_AT,
        decision_timestamp=BASE_TIMESTAMP,
    )
    store.append_decision(
        record,
        created_by="tester",
        source_module="tests.test_decision_audit_runner",
        source_version="1.0",
        created_at=BASE_CREATED_AT,
        decision_timestamp=BASE_TIMESTAMP,
    )


def test_audit_runner_writes_deterministic_artifact(tmp_path: Path, monkeypatch) -> None:
    memory_path = tmp_path / "decision_memory.jsonl"
    artifact_path = tmp_path / "assessment.json"
    _seed_store(memory_path)

    args = [
        "--memory-path",
        str(memory_path),
        "--repo-root",
        str(Path(__file__).resolve().parents[1]),
        "--artifact-path",
        str(artifact_path),
        "--generated-at",
        "2026-07-13T12:00:00+00:00",
        "--final-status",
        "VALIDATED",
        "--test-command",
        "PYTHONPATH=/Users/klara/Projects/parapusulasi pytest -q tests/test_decision_contract.py tests/test_decision_memory_store.py tests/test_decision_memory.py tests/test_decision_audit_runner.py",
        "--test-result",
        "focused=PASS",
    ]

    first_rc = main(args)
    assert first_rc == 0
    first = artifact_path.read_text(encoding="utf-8")

    second_rc = main(args)
    assert second_rc == 0
    second = artifact_path.read_text(encoding="utf-8")
    assert first == second

    artifact = json.loads(first)
    assert artifact["overall_status"] == "VALIDATED"
    assert artifact["project"] == "PROJECT_003"
    assert artifact["sprint"] == "SPRINT_1"
    assert artifact["artifact_hash"]
    assert artifact["validation_time"] == "2026-07-13T12:00:00+00:00"
    assert artifact["tests_run"] == 1
    assert artifact["tests_passed"] == 1
    assert artifact["tests_failed"] == 0
    assert "acceptance_matrix" in artifact
    assert "files_created" in artifact
    assert "files_modified" in artifact
    assert "safety_assertions" in artifact
    assert "unresolved_items" in artifact
    assert artifact["audit_checks"]["row_count"] == 1


def test_audit_runner_stays_offline(tmp_path: Path, monkeypatch) -> None:
    memory_path = tmp_path / "decision_memory.jsonl"
    artifact_path = tmp_path / "assessment.json"
    _seed_store(memory_path)

    def _deny_socket(*_args, **_kwargs):
        raise AssertionError("network access is not allowed")

    monkeypatch.setattr(socket, "socket", _deny_socket)

    rc = main(
        [
            "--memory-path",
            str(memory_path),
            "--repo-root",
            str(Path(__file__).resolve().parents[1]),
            "--artifact-path",
            str(artifact_path),
            "--generated-at",
            "2026-07-13T12:00:00+00:00",
            "--final-status",
            "VALIDATED",
        ]
    )
    assert rc == 0
    assert artifact_path.exists()
