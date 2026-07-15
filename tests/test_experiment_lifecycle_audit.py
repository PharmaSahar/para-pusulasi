from __future__ import annotations

import json
import socket
from pathlib import Path

from src.experiment_lifecycle_store import ExperimentLifecycleStore
from src.run_experiment_lifecycle_audit import main
from tests.experiment_lifecycle_fixtures import BASE_TIME, base_assignment_payload, base_contamination_payload, base_exposure_payload


def _seed(path: Path) -> None:
    store = ExperimentLifecycleStore(lifecycle_path=path)
    assignment = store.append_assignment_event(
        base_assignment_payload(),
        created_by="tester",
        source_module="tests.test_experiment_lifecycle_audit",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    rows = store.get_rows()
    assignment_row = rows[-1]

    store.append_exposure_event(
        base_exposure_payload(
            assignment_id=assignment.assignment_id,
            assignment_seed=assignment_row["assignment_seed"],
            assignment_hash=assignment_row["assignment_hash"],
            eligibility_snapshot_hash=assignment_row["eligibility_snapshot_hash"],
        ),
        created_by="tester",
        source_module="tests.test_experiment_lifecycle_audit",
        source_version="1.0",
        created_at="2026-07-14T12:01:00+00:00",
    )
    store.append_contamination_event(
        base_contamination_payload(
            assignment_id=assignment.assignment_id,
            assignment_seed=assignment_row["assignment_seed"],
            assignment_hash=assignment_row["assignment_hash"],
            eligibility_snapshot_hash=assignment_row["eligibility_snapshot_hash"],
            contamination_severity="LOW",
        ),
        created_by="tester",
        source_module="tests.test_experiment_lifecycle_audit",
        source_version="1.0",
        created_at="2026-07-14T12:02:00+00:00",
    )


def test_audit_runner_is_deterministic(tmp_path: Path) -> None:
    lifecycle_path = tmp_path / "experiment_lifecycle.jsonl"
    artifact_path = tmp_path / "assessment.json"
    _seed(lifecycle_path)

    args = [
        "--lifecycle-path",
        str(lifecycle_path),
        "--repo-root",
        str(Path(__file__).resolve().parents[1]),
        "--artifact-path",
        str(artifact_path),
        "--generated-at",
        "2026-07-14T12:30:00+00:00",
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
    assert payload["project"] == "PROJECT_003"
    assert payload["sprint"] == "SPRINT_4"
    assert payload["overall_status"] == "VALIDATED"
    assert payload["artifact_hash"]
    assert payload["validation_summary"]["assignment_count"] == 1


def test_audit_runner_offline(tmp_path: Path, monkeypatch) -> None:
    lifecycle_path = tmp_path / "experiment_lifecycle.jsonl"
    artifact_path = tmp_path / "assessment.json"
    _seed(lifecycle_path)

    def _deny_socket(*_args, **_kwargs):
        raise AssertionError("network access is not allowed")

    monkeypatch.setattr(socket, "socket", _deny_socket)
    assert main([
        "--lifecycle-path",
        str(lifecycle_path),
        "--repo-root",
        str(Path(__file__).resolve().parents[1]),
        "--artifact-path",
        str(artifact_path),
    ]) == 0
    assert artifact_path.exists()
