from __future__ import annotations

from pathlib import Path

import pytest

from src.historical_learning_store import (
    HistoricalLearningConflictError,
    HistoricalLearningCorruptionError,
    HistoricalLearningStore,
)
from src.learning_record_contract import LearningMaturityState, build_learning_record
from tests.learning_record_fixtures import BASE_TIME, base_learning_payload


def _store(tmp_path: Path) -> HistoricalLearningStore:
    return HistoricalLearningStore(learning_path=tmp_path / "historical_learning.jsonl")


def _append_base(store: HistoricalLearningStore) -> dict[str, object]:
    payload = base_learning_payload()
    record = build_learning_record(
        payload,
        created_by="tester",
        source_module="tests.test_historical_learning_store",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    result = store.append_learning_event(
        record,
        created_by="tester",
        source_module="tests.test_historical_learning_store",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    assert result.appended is True
    return record


def test_append_and_exact_duplicate_is_idempotent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    record = _append_base(store)

    duplicate = store.append_learning_event(
        record,
        created_by="tester",
        source_module="tests.test_historical_learning_store",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    assert duplicate.duplicate is True
    assert len(store.get_rows()) == 1


def test_late_arriving_metrics_and_correction_are_new_events(tmp_path: Path) -> None:
    store = _store(tmp_path)
    base = _append_base(store)

    update = store.append_learning_event(
        base_learning_payload(views=220, event_type="metric_update", maturity_state="partially_observed"),
        created_by="tester",
        source_module="tests.test_historical_learning_store",
        source_version="1.0",
        created_at="2026-07-14T13:00:00+00:00",
        event_type="metric_update",
        maturity_state="partially_observed",
    )
    correction = store.append_learning_event(
        base_learning_payload(views=200, event_type="correction", maturity_state="partially_observed"),
        created_by="tester",
        source_module="tests.test_historical_learning_store",
        source_version="1.0",
        created_at="2026-07-14T14:00:00+00:00",
        event_type="correction",
        maturity_state="partially_observed",
    )
    assert update.appended is True
    assert correction.appended is True
    assert len(store.get_rows()) == 3


def test_invalid_maturity_transition_fails(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _append_base(store)

    with pytest.raises(HistoricalLearningConflictError):
        store.append_learning_event(
            base_learning_payload(maturity_state=LearningMaturityState.UNKNOWN.value),
            created_by="tester",
            source_module="tests.test_historical_learning_store",
            source_version="1.0",
            created_at="2026-07-14T13:00:00+00:00",
            maturity_state=LearningMaturityState.UNKNOWN.value,
        )


def test_replay_parity_and_index_rebuild(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _append_base(store)
    store.append_learning_event(
        base_learning_payload(views=220, maturity_state="partially_observed", event_type="metric_update"),
        created_by="tester",
        source_module="tests.test_historical_learning_store",
        source_version="1.0",
        created_at="2026-07-14T13:00:00+00:00",
        event_type="metric_update",
        maturity_state="partially_observed",
    )

    first, first_diag = store.replay()
    second, second_diag = store.replay()
    assert first == second
    assert first_diag == second_diag
    assert len(first["learning_index"]) == 1


def test_hash_chain_corruption_detected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _append_base(store)
    path = tmp_path / "historical_learning.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("{bad json}\n" + "\n".join(lines), encoding="utf-8")

    corrupted = HistoricalLearningStore(learning_path=path)
    with pytest.raises(HistoricalLearningCorruptionError):
        corrupted.get_rows()
