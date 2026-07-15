from __future__ import annotations

from pathlib import Path

import pytest

from src.statistical_confidence_contract import StatisticalConfidenceState, build_statistical_confidence_record
from src.statistical_confidence_store import (
    StatisticalConfidenceCorruptionError,
    StatisticalConfidenceStore,
)
from tests.statistical_confidence_fixtures import BASE_TIME, base_confidence_payload


def _store(tmp_path: Path) -> StatisticalConfidenceStore:
    return StatisticalConfidenceStore(confidence_path=tmp_path / "statistical_confidence.jsonl")


def _append_base(store: StatisticalConfidenceStore, **overrides: object) -> dict[str, object]:
    payload = base_confidence_payload(**overrides)
    record = build_statistical_confidence_record(
        payload,
        created_by="tester",
        source_module="tests.test_statistical_confidence_store",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    result = store.append_confidence_event(
        record,
        created_by="tester",
        source_module="tests.test_statistical_confidence_store",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    assert result.appended is True
    return record


def test_append_and_duplicate_idempotent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    record = _append_base(store)

    duplicate = store.append_confidence_event(
        build_statistical_confidence_record(
            base_confidence_payload(),
            created_by="tester",
            source_module="tests.test_statistical_confidence_store",
            source_version="1.0",
            created_at=BASE_TIME,
        ),
        created_by="tester",
        source_module="tests.test_statistical_confidence_store",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    assert duplicate.duplicate is True
    assert duplicate.confidence_id == record["confidence_id"]
    assert len(store.get_rows()) == 1


def test_replay_is_deterministic_and_tracks_state_counts(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _append_base(store)
    _append_base(store, effect_size_absolute=0.01, effect_size_relative=0.01)
    projection1, diag1 = store.replay()
    projection2, diag2 = store.replay()
    assert projection1 == projection2
    assert diag1 == diag2
    assert projection1["state_counts"][StatisticalConfidenceState.STATISTICALLY_SUPPORTED.value] == 1


def test_corruption_detection_raises(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _append_base(store)
    path = tmp_path / "statistical_confidence.jsonl"
    path.write_text("{bad json}\n", encoding="utf-8")
    corrupted = StatisticalConfidenceStore(confidence_path=path)
    with pytest.raises(StatisticalConfidenceCorruptionError):
        corrupted.get_rows()
