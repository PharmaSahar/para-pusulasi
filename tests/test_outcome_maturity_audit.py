from __future__ import annotations

import json
import socket
from pathlib import Path

from src.outcome_maturity_contract import build_outcome_maturity_record
from src.outcome_maturity_store import OutcomeMaturityStore
from src.run_outcome_maturity_audit import main
from tests.outcome_maturity_fixtures import BASE_TIME, base_outcome_payload


def _seed(path: Path) -> None:
    store = OutcomeMaturityStore(outcome_path=path)
    record = build_outcome_maturity_record(
        base_outcome_payload(),
        created_by="tester",
        source_module="tests.test_outcome_maturity_audit",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    store.append_outcome_event(
        record,
        created_by="tester",
        source_module="tests.test_outcome_maturity_audit",
        source_version="1.0",
        created_at=BASE_TIME,
    )


def test_audit_runner_is_deterministic(tmp_path: Path) -> None:
    outcome_path = tmp_path / "outcome_maturity.jsonl"
    artifact_path = tmp_path / "assessment.json"
    _seed(outcome_path)

    args = [
        "--outcome-path",
        str(outcome_path),
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
    assert payload["sprint"] == "SPRINT_3"
    assert payload["artifact_hash"]
    assert payload["overall_status"] == "VALIDATED"


def test_audit_runner_offline(tmp_path: Path, monkeypatch) -> None:
    outcome_path = tmp_path / "outcome_maturity.jsonl"
    artifact_path = tmp_path / "assessment.json"
    _seed(outcome_path)

    def _deny_socket(*_args, **_kwargs):
        raise AssertionError("network access is not allowed")

    monkeypatch.setattr(socket, "socket", _deny_socket)
    assert main([
        "--outcome-path",
        str(outcome_path),
        "--repo-root",
        str(Path(__file__).resolve().parents[1]),
        "--artifact-path",
        str(artifact_path),
    ]) == 0
    assert artifact_path.exists()
