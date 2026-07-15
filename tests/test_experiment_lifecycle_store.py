from __future__ import annotations

from pathlib import Path

import pytest

from src.experiment_lifecycle_store import (
    ExperimentLifecycleConflictError,
    ExperimentLifecycleCorruptionError,
    ExperimentLifecycleStore,
)
from tests.experiment_lifecycle_fixtures import BASE_TIME, base_assignment_payload, base_contamination_payload, base_exposure_payload


def _store(tmp_path: Path) -> ExperimentLifecycleStore:
    return ExperimentLifecycleStore(lifecycle_path=tmp_path / "experiment_lifecycle.jsonl")


def _append_assignment(store: ExperimentLifecycleStore, **overrides: object) -> dict[str, object]:
    payload = base_assignment_payload(**overrides)
    result = store.append_assignment_event(
        payload,
        created_by="tester",
        source_module="tests.test_experiment_lifecycle_store",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    assert result.appended is True
    return store.get_rows()[-1]


def test_assignment_append_and_exact_duplicate_idempotent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _append_assignment(store)

    duplicate = store.append_assignment_event(
        base_assignment_payload(),
        created_by="tester",
        source_module="tests.test_experiment_lifecycle_store",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    assert duplicate.duplicate is True
    assert len(store.get_rows()) == 1


def test_assignment_reproducibility_conflict_detected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = _append_assignment(store)

    with pytest.raises(ExperimentLifecycleConflictError):
        store.append_assignment_event(
            base_assignment_payload(
                assignment_id=first["assignment_id"],
                assigned_variant="treatment",
            ),
            created_by="tester",
            source_module="tests.test_experiment_lifecycle_store",
            source_version="1.0",
            created_at="2026-07-14T12:05:00+00:00",
        )


def test_exposure_deduplication_blocks_repeated_ingestion(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assignment = _append_assignment(store)

    payload = base_exposure_payload(
        assignment_id=assignment["assignment_id"],
        assignment_seed=assignment["assignment_seed"],
        assignment_hash=assignment["assignment_hash"],
        eligibility_snapshot_hash=assignment["eligibility_snapshot_hash"],
    )
    first = store.append_exposure_event(
        payload,
        created_by="tester",
        source_module="tests.test_experiment_lifecycle_store",
        source_version="1.0",
        created_at="2026-07-14T12:06:00+00:00",
    )
    second = store.append_exposure_event(
        payload,
        created_by="tester",
        source_module="tests.test_experiment_lifecycle_store",
        source_version="1.0",
        created_at="2026-07-14T12:07:00+00:00",
    )
    assert first.appended is True
    assert second.duplicate is True
    assert len(store.get_rows()) == 2


def test_contamination_is_record_only_and_severity_counted(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assignment = _append_assignment(store)

    contamination = store.append_contamination_event(
        base_contamination_payload(
            assignment_id=assignment["assignment_id"],
            assignment_seed=assignment["assignment_seed"],
            assignment_hash=assignment["assignment_hash"],
            eligibility_snapshot_hash=assignment["eligibility_snapshot_hash"],
            contamination_severity="MEDIUM",
        ),
        created_by="tester",
        source_module="tests.test_experiment_lifecycle_store",
        source_version="1.0",
        created_at="2026-07-14T12:08:00+00:00",
    )
    assert contamination.appended is True

    projection, diagnostics = store.replay()
    assert diagnostics.malformed_rows == 0
    assert projection["contamination_severity_counts"]["MEDIUM"] == 1


def test_corruption_detection_raises(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _append_assignment(store)
    path = tmp_path / "experiment_lifecycle.jsonl"
    path.write_text("{bad json}\n", encoding="utf-8")
    corrupted = ExperimentLifecycleStore(lifecycle_path=path)
    with pytest.raises(ExperimentLifecycleCorruptionError):
        corrupted.get_rows()
