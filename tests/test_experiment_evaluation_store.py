from __future__ import annotations

from pathlib import Path

import pytest

from src.experiment_evaluation_contract import ExperimentEvaluationState, build_experiment_evaluation_record
from src.experiment_evaluation_store import (
    ExperimentEvaluationConflictError,
    ExperimentEvaluationCorruptionError,
    ExperimentEvaluationStore,
)
from tests.experiment_evaluation_fixtures import BASE_TIME, base_evaluation_payload


def _store(tmp_path: Path) -> ExperimentEvaluationStore:
    return ExperimentEvaluationStore(evaluation_path=tmp_path / "experiment_evaluation.jsonl")


def _append_base(store: ExperimentEvaluationStore, **overrides: object) -> dict[str, object]:
    payload = base_evaluation_payload(**overrides)
    record = build_experiment_evaluation_record(
        payload,
        created_by="tester",
        source_module="tests.test_experiment_evaluation_store",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    result = store.append_evaluation_event(
        record,
        created_by="tester",
        source_module="tests.test_experiment_evaluation_store",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    assert result.appended is True
    return record


def test_append_and_duplicate_idempotent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    record = _append_base(store)

    duplicate = store.append_evaluation_event(
        build_experiment_evaluation_record(
            base_evaluation_payload(),
            created_by="tester",
            source_module="tests.test_experiment_evaluation_store",
            source_version="1.0",
            created_at=BASE_TIME,
        ),
        created_by="tester",
        source_module="tests.test_experiment_evaluation_store",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    assert duplicate.duplicate is True
    assert duplicate.evaluation_record_id == record["evaluation_record_id"]
    assert len(store.get_rows()) == 1


def test_replay_is_deterministic_and_tracks_state_counts(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _append_base(store)
    projection1, diag1 = store.replay()
    projection2, diag2 = store.replay()
    assert projection1 == projection2
    assert diag1 == diag2
    assert projection1["state_counts"][ExperimentEvaluationState.VALIDATED_RESULT.value] == 1


def test_corruption_detection_raises(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _append_base(store)
    path = tmp_path / "experiment_evaluation.jsonl"
    path.write_text("{bad json}\n", encoding="utf-8")
    corrupted = ExperimentEvaluationStore(evaluation_path=path)
    with pytest.raises(ExperimentEvaluationCorruptionError):
        corrupted.get_rows()
