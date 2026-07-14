from __future__ import annotations

from pathlib import Path

import pytest

from src.decision_contract import DecisionState, build_decision_record
from src.decision_memory import (
    DecisionMemoryConflictError,
    DecisionMemoryCorruptionError,
    DecisionMemoryStore,
    DecisionMemoryTransitionError,
    build_decision_memory_audit_summary,
)
from tests.decision_memory_fixtures import BASE_CREATED_AT, BASE_TIMESTAMP, build_decision_payload


def _store(tmp_path: Path) -> DecisionMemoryStore:
    return DecisionMemoryStore(memory_path=tmp_path / "decision_memory.jsonl")


def _append_base_decision(store: DecisionMemoryStore, *, content_id: str = "content_001") -> dict[str, object]:
    payload = build_decision_payload(content_id=content_id)
    record = build_decision_record(
        payload,
        created_by="tester",
        source_module="tests.test_decision_memory_store",
        source_version="1.0",
        created_at=BASE_CREATED_AT,
        decision_timestamp=BASE_TIMESTAMP,
    )
    result = store.append_decision(
        record,
        created_by="tester",
        source_module="tests.test_decision_memory_store",
        source_version="1.0",
        created_at=BASE_CREATED_AT,
        decision_timestamp=BASE_TIMESTAMP,
    )
    assert result.appended is True
    return record


def test_append_replay_and_retrievals(tmp_path: Path) -> None:
    store = _store(tmp_path)
    record = _append_base_decision(store)

    rows = store.get_rows()
    assert len(rows) == 1
    assert store.get_by_decision_id(record["decision_id"])[0]["decision_id"] == record["decision_id"]
    assert store.get_by_correlation_id(record["correlation_id"])[0]["correlation_id"] == record["correlation_id"]
    assert store.get_by_content_id(record["content_id"])[0]["content_id"] == record["content_id"]
    assert store.get_by_channel_id(record["channel_id"])[0]["channel_id"] == record["channel_id"]
    assert store.get_by_decision_type(record["decision_type"])[0]["decision_type"] == record["decision_type"]
    assert store.get_by_state(DecisionState.DRAFT)[0]["decision_state"] == DecisionState.DRAFT.value
    assert store.get_by_time_range(BASE_TIMESTAMP, BASE_TIMESTAMP)[0]["decision_id"] == record["decision_id"]

    projections, diagnostics = store.replay()
    assert diagnostics.malformed_rows == 0
    assert diagnostics.duplicate_rows == 0
    assert projections["current_state_by_decision_id"][record["decision_id"]]["decision_id"] == record["decision_id"]
    assert len(projections["decision_timeline"][record["decision_id"]]) == 1
    assert projections["decision_feature_projection"][0]["content_type"] == "video"
    assert projections["decision_feature_projection"][0]["topic_category"] == "economy"
    assert projections["decision_feature_projection"][0]["evidence_class_distribution"]["execution"] >= 1

    summary = build_decision_memory_audit_summary(store=store)
    assert summary["hash_chain"]["valid"] is True
    assert summary["current_state_count"] == 1


def test_exact_duplicate_append_is_idempotent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    record = _append_base_decision(store)

    duplicate = store.append_decision(
        build_decision_record(
            build_decision_payload(),
            created_by="tester",
            source_module="tests.test_decision_memory_store",
            source_version="1.0",
            created_at=BASE_CREATED_AT,
            decision_timestamp=BASE_TIMESTAMP,
        ),
        created_by="tester",
        source_module="tests.test_decision_memory_store",
        source_version="1.0",
        created_at=BASE_CREATED_AT,
        decision_timestamp=BASE_TIMESTAMP,
    )

    assert duplicate.duplicate is True
    assert duplicate.decision_id == record["decision_id"]
    assert len(store.get_rows()) == 1


def test_conflicting_duplicate_append_fails_explicitly(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _append_base_decision(store)

    conflicting_payload = build_decision_payload(selected_title="Macro Update")
    conflicting_record = build_decision_record(
        conflicting_payload,
        created_by="tester",
        source_module="tests.test_decision_memory_store",
        source_version="1.0",
        created_at=BASE_CREATED_AT,
        decision_timestamp=BASE_TIMESTAMP,
    )

    with pytest.raises(DecisionMemoryConflictError):
        store.append_decision(
            conflicting_record,
            created_by="tester",
            source_module="tests.test_decision_memory_store",
            source_version="1.0",
            created_at=BASE_CREATED_AT,
            decision_timestamp=BASE_TIMESTAMP,
        )


def test_valid_state_transitions_and_idempotency(tmp_path: Path) -> None:
    store = _store(tmp_path)
    record = _append_base_decision(store)

    first_transition = store.append_state_transition(
        record["decision_id"],
        DecisionState.REVIEW_REQUIRED,
        created_by="tester",
        source_module="tests.test_decision_memory_store",
        source_version="1.0",
        created_at="2026-07-13T12:05:00+00:00",
        decision_timestamp="2026-07-13T12:05:00+00:00",
        reviewer_ref="reviewer_1",
        review_reason="Needs human review.",
    )
    second_transition = store.append_state_transition(
        record["decision_id"],
        DecisionState.REVIEW_REQUIRED,
        created_by="tester",
        source_module="tests.test_decision_memory_store",
        source_version="1.0",
        created_at="2026-07-13T12:05:00+00:00",
        decision_timestamp="2026-07-13T12:05:00+00:00",
        reviewer_ref="reviewer_1",
        review_reason="Needs human review.",
    )

    assert first_transition.appended is True
    assert second_transition.duplicate is True

    updated = store.append_state_transition(
        record["decision_id"],
        DecisionState.APPROVED,
        created_by="tester",
        source_module="tests.test_decision_memory_store",
        source_version="1.0",
        created_at="2026-07-13T12:06:00+00:00",
        decision_timestamp="2026-07-13T12:06:00+00:00",
        reviewer_ref="reviewer_1",
        review_reason="Approved after review.",
        human_approval_state="approved",
    )
    assert updated.appended is True
    assert store.get_by_state(DecisionState.APPROVED)[0]["decision_state"] == DecisionState.APPROVED.value


def test_terminal_and_invalid_transitions_are_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    record = _append_base_decision(store)

    with pytest.raises(DecisionMemoryTransitionError):
        store.append_state_transition(
            record["decision_id"],
            DecisionState.EXECUTED,
            created_by="tester",
            source_module="tests.test_decision_memory_store",
            source_version="1.0",
            created_at="2026-07-13T12:05:00+00:00",
            decision_timestamp="2026-07-13T12:05:00+00:00",
        )

    store.append_state_transition(
        record["decision_id"],
        DecisionState.QUARANTINED,
        created_by="tester",
        source_module="tests.test_decision_memory_store",
        source_version="1.0",
        created_at="2026-07-13T12:05:00+00:00",
        decision_timestamp="2026-07-13T12:05:00+00:00",
        review_reason="Quarantined during review.",
    )
    with pytest.raises(DecisionMemoryTransitionError):
        store.append_state_transition(
            record["decision_id"],
            DecisionState.APPROVED,
            created_by="tester",
            source_module="tests.test_decision_memory_store",
            source_version="1.0",
            created_at="2026-07-13T12:06:00+00:00",
            decision_timestamp="2026-07-13T12:06:00+00:00",
        )


def test_superseding_and_rollback_history(tmp_path: Path) -> None:
    store = _store(tmp_path)
    original = _append_base_decision(store)
    superseding_payload = build_decision_payload(
        correlation_id="corr_002",
        content_id="content_002",
        supersedes_decision_id=original["decision_id"],
        selected_title="Market Outlook v2",
        title_candidates=["Market Outlook v2"],
        rejected_title_candidates=[],
        decision_state="superseded",
    )
    superseding_record = build_decision_record(
        superseding_payload,
        created_by="tester",
        source_module="tests.test_decision_memory_store",
        source_version="1.0",
        created_at="2026-07-13T12:10:00+00:00",
        decision_timestamp="2026-07-13T12:10:00+00:00",
        decision_state=DecisionState.SUPERSEDED,
    )
    appended = store.append_decision(
        superseding_record,
        created_by="tester",
        source_module="tests.test_decision_memory_store",
        source_version="1.0",
        created_at="2026-07-13T12:10:00+00:00",
        decision_timestamp="2026-07-13T12:10:00+00:00",
        decision_state=DecisionState.SUPERSEDED,
    )
    assert appended.appended is True

    store.append_state_transition(
        original["decision_id"],
        DecisionState.REVIEW_REQUIRED,
        created_by="tester",
        source_module="tests.test_decision_memory_store",
        source_version="1.0",
        created_at="2026-07-13T12:11:00+00:00",
        decision_timestamp="2026-07-13T12:11:00+00:00",
        reviewer_ref="reviewer_1",
        review_reason="Escalated for review.",
    )
    store.append_state_transition(
        original["decision_id"],
        DecisionState.APPROVED,
        created_by="tester",
        source_module="tests.test_decision_memory_store",
        source_version="1.0",
        created_at="2026-07-13T12:12:00+00:00",
        decision_timestamp="2026-07-13T12:12:00+00:00",
        reviewer_ref="reviewer_1",
        review_reason="Approved.",
        human_approval_state="approved",
    )
    rollback = store.append_state_transition(
        original["decision_id"],
        DecisionState.EXECUTED,
        created_by="tester",
        source_module="tests.test_decision_memory_store",
        source_version="1.0",
        created_at="2026-07-13T12:13:00+00:00",
        decision_timestamp="2026-07-13T12:13:00+00:00",
        final_execution_status="success",
    )
    assert rollback.appended is True

    projections, _diagnostics = store.replay()
    assert projections["superseded_decision_chain"]
    assert projections["rollback_history"]


def test_replay_is_deterministic_and_reports_corruption(tmp_path: Path) -> None:
    store = _store(tmp_path)
    record = _append_base_decision(store)
    first, first_diag = store.replay()
    second, second_diag = store.replay()
    assert first == second
    assert first_diag == second_diag

    path = store.memory_path
    path.write_text("{bad json}\n", encoding="utf-8")
    corrupted_store = DecisionMemoryStore(memory_path=path)
    with pytest.raises(DecisionMemoryCorruptionError):
        corrupted_store.append_state_transition(
            record["decision_id"],
            DecisionState.APPROVED,
            created_by="tester",
            source_module="tests.test_decision_memory_store",
            source_version="1.0",
        )


def test_malformed_truncated_schema_and_hash_chain_detection(tmp_path: Path) -> None:
    path = tmp_path / "decision_memory.jsonl"
    first = build_decision_record(
        build_decision_payload(content_id="content_001"),
        created_by="tester",
        source_module="tests.test_decision_memory_store",
        source_version="1.0",
        created_at=BASE_CREATED_AT,
        decision_timestamp=BASE_TIMESTAMP,
    )
    second = build_decision_record(
        build_decision_payload(content_id="content_002"),
        created_by="tester",
        source_module="tests.test_decision_memory_store",
        source_version="1.0",
        created_at=BASE_CREATED_AT,
        decision_timestamp=BASE_TIMESTAMP,
        previous_record_hash="bad_previous_hash",
    )
    path.write_text(
        "{bad json}\n"
        + json_line(first)
        + "\n"
        + json_line(second)[:-1],
        encoding="utf-8",
    )

    rows, diagnostics = DecisionMemoryStore(memory_path=path)._load()
    assert diagnostics.malformed_rows >= 1
    assert diagnostics.partial_trailing_rows >= 1
    assert diagnostics.broken_hash_links >= 0
    assert len(rows) >= 1

    unsupported = build_decision_record(
        build_decision_payload(content_id="content_003"),
        created_by="tester",
        source_module="tests.test_decision_memory_store",
        source_version="1.0",
        created_at=BASE_CREATED_AT,
        decision_timestamp=BASE_TIMESTAMP,
    )
    unsupported["schema_version"] = "v999"
    unsupported_path = tmp_path / "unsupported.jsonl"
    unsupported_path.write_text(json_line(unsupported) + "\n", encoding="utf-8")
    unsupported_store = DecisionMemoryStore(memory_path=unsupported_path)
    with pytest.raises(DecisionMemoryCorruptionError):
        unsupported_store.get_rows()


def json_line(payload: dict[str, object]) -> str:
    import json

    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
