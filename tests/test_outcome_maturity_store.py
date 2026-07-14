from __future__ import annotations

from pathlib import Path

import pytest

from src.outcome_maturity_contract import OutcomeMaturityState, build_outcome_maturity_record
from src.outcome_maturity_store import (
    OutcomeMaturityConflictError,
    OutcomeMaturityCorruptionError,
    OutcomeMaturityStore,
)
from tests.outcome_maturity_fixtures import BASE_TIME, base_outcome_payload


def _store(tmp_path: Path) -> OutcomeMaturityStore:
    return OutcomeMaturityStore(outcome_path=tmp_path / "outcome_maturity.jsonl")


def _append_base(store: OutcomeMaturityStore) -> dict[str, object]:
    payload = base_outcome_payload()
    record = build_outcome_maturity_record(
        payload,
        created_by="tester",
        source_module="tests.test_outcome_maturity_store",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    result = store.append_outcome_event(
        record,
        created_by="tester",
        source_module="tests.test_outcome_maturity_store",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    assert result.appended is True
    return record


def test_append_and_exact_duplicate_is_idempotent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    record = _append_base(store)

    duplicate = store.append_outcome_event(
        record,
        created_by="tester",
        source_module="tests.test_outcome_maturity_store",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    assert duplicate.duplicate is True
    assert len(store.get_rows()) == 1


def test_late_observations_and_correction_are_new_events(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _append_base(store)

    update = store.append_outcome_event(
        base_outcome_payload(ctr_ratio=0.22, event_type="METRIC_UPDATE", maturity_state="PARTIALLY_OBSERVED"),
        created_by="tester",
        source_module="tests.test_outcome_maturity_store",
        source_version="1.0",
        created_at="2026-07-14T13:00:00+00:00",
        event_type="METRIC_UPDATE",
        maturity_state="PARTIALLY_OBSERVED",
    )
    correction = store.append_outcome_event(
        base_outcome_payload(ctr_ratio=0.20, event_type="CORRECTION", maturity_state="PARTIALLY_OBSERVED"),
        created_by="tester",
        source_module="tests.test_outcome_maturity_store",
        source_version="1.0",
        created_at="2026-07-14T14:00:00+00:00",
        event_type="CORRECTION",
        maturity_state="PARTIALLY_OBSERVED",
    )
    assert update.appended is True
    assert correction.appended is True
    assert len(store.get_rows()) == 3


def test_invalid_maturity_transition_fails(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _append_base(store)

    with pytest.raises(OutcomeMaturityConflictError):
        store.append_outcome_event(
            base_outcome_payload(maturity_state=OutcomeMaturityState.UNKNOWN.value),
            created_by="tester",
            source_module="tests.test_outcome_maturity_store",
            source_version="1.0",
            created_at="2026-07-14T13:00:00+00:00",
            maturity_state=OutcomeMaturityState.UNKNOWN.value,
        )


def test_replay_parity_and_snapshot_rebuild(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _append_base(store)
    store.append_outcome_event(
        base_outcome_payload(ctr_ratio=0.22, maturity_state="PARTIALLY_OBSERVED", event_type="METRIC_UPDATE"),
        created_by="tester",
        source_module="tests.test_outcome_maturity_store",
        source_version="1.0",
        created_at="2026-07-14T13:00:00+00:00",
        event_type="METRIC_UPDATE",
        maturity_state="PARTIALLY_OBSERVED",
    )

    first, first_diag = store.replay()
    second, second_diag = store.replay()
    assert first == second
    assert first_diag == second_diag
    assert len(first["outcome_snapshot"]) == 1


def test_hash_chain_corruption_detected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _append_base(store)
    path = tmp_path / "outcome_maturity.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("{bad json}\n" + "\n".join(lines), encoding="utf-8")

    corrupted = OutcomeMaturityStore(outcome_path=path)
    with pytest.raises(OutcomeMaturityCorruptionError):
        corrupted.get_rows()
