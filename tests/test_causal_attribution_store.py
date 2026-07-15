from __future__ import annotations

from pathlib import Path

import pytest

from src.causal_attribution_contract import CausalAttributionState, build_causal_attribution_record
from src.causal_attribution_store import (
    CausalAttributionCorruptionError,
    CausalAttributionStore,
)
from tests.causal_attribution_fixtures import BASE_TIME, base_attribution_payload


def _store(tmp_path: Path) -> CausalAttributionStore:
    return CausalAttributionStore(attribution_path=tmp_path / "causal_attribution.jsonl")


def _append_base(store: CausalAttributionStore, **overrides: object) -> dict[str, object]:
    record = build_causal_attribution_record(
        base_attribution_payload(**overrides),
        created_by="tester",
        source_module="tests.test_causal_attribution_store",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    result = store.append_attribution_event(
        record,
        created_by="tester",
        source_module="tests.test_causal_attribution_store",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    assert result.appended is True
    return record


def test_append_duplicate_and_conflict_paths(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = _append_base(store)

    duplicate = store.append_attribution_event(
        build_causal_attribution_record(
            base_attribution_payload(),
            created_by="tester",
            source_module="tests.test_causal_attribution_store",
            source_version="1.0",
            created_at=BASE_TIME,
        ),
        created_by="tester",
        source_module="tests.test_causal_attribution_store",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    assert duplicate.duplicate is True
    assert duplicate.conflict is False
    assert duplicate.attribution_record_id == first["attribution_record_id"]

    conflict = store.append_attribution_event(
        build_causal_attribution_record(
            base_attribution_payload(
                treatment_effect_absolute=0.22,
                treatment_effect_relative=0.31,
            ),
            created_by="tester",
            source_module="tests.test_causal_attribution_store",
            source_version="1.0",
            created_at=BASE_TIME,
        ),
        created_by="tester",
        source_module="tests.test_causal_attribution_store",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    assert conflict.appended is False
    assert conflict.conflict is True
    assert conflict.reason == "conflicting_duplicate"


def test_replay_parity_and_hash_chain(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _append_base(store)
    _append_base(
        store,
        randomized_assignment_proven=False,
        assignment_method="observational",
        treatment_exposure_refs=[{"ref_type": "exposure", "ref_id": "exp_t_002"}],
        control_exposure_refs=[{"ref_type": "exposure", "ref_id": "exp_c_002"}],
        treatment_assignment_ref="assignment:treatment:008",
        control_assignment_ref="assignment:control:008",
        outcome_record_id="omr_008",
        correlation_id="corr_008",
        treatment_outcome_ref="outcome:treatment:008",
        control_outcome_ref="outcome:control:008",
    )

    first_projection, first_diag = store.replay()
    second_projection, second_diag = store.replay()

    assert first_projection == second_projection
    assert first_diag == second_diag
    assert first_projection["state_counts"][CausalAttributionState.CAUSALLY_SUPPORTED.value] == 1
    assert first_projection["state_counts"][CausalAttributionState.ASSOCIATIONAL_ONLY.value] == 1

    chain = store.verify_hash_chain()
    assert chain["valid"] is True
    assert chain["row_count"] == 2


def test_corruption_fail_closed_paths(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _append_base(store)

    path = tmp_path / "causal_attribution.jsonl"

    path.write_text('{"schema_version":"v999"}\n', encoding="utf-8")
    unsupported = CausalAttributionStore(attribution_path=path)
    with pytest.raises(CausalAttributionCorruptionError):
        unsupported.get_rows()

    path.write_text('{"bad":\n', encoding="utf-8")
    malformed = CausalAttributionStore(attribution_path=path)
    with pytest.raises(CausalAttributionCorruptionError):
        malformed.get_rows()

    path.write_text('not_json_no_newline', encoding="utf-8")
    truncated = CausalAttributionStore(attribution_path=path)
    with pytest.raises(CausalAttributionCorruptionError):
        truncated.append_attribution_event(
            base_attribution_payload(),
            created_by="tester",
            source_module="tests.test_causal_attribution_store",
            source_version="1.0",
            created_at=BASE_TIME,
        )
