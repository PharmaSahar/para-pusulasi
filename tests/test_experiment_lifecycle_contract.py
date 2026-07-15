from __future__ import annotations

import pytest

from src.experiment_lifecycle_contract import (
    ContaminationSeverity,
    LifecycleEventType,
    build_experiment_lifecycle_event,
    compute_exposure_dedupe_key,
    compute_eligibility_snapshot_hash,
)
from tests.experiment_lifecycle_fixtures import BASE_TIME, base_assignment_payload, base_contamination_payload, base_exposure_payload


def test_assignment_build_is_deterministic_and_complete() -> None:
    payload = base_assignment_payload()
    first = build_experiment_lifecycle_event(
        payload,
        created_by="tester",
        source_module="tests.test_experiment_lifecycle_contract",
        source_version="1.0",
        created_at=BASE_TIME,
        event_type=LifecycleEventType.ASSIGNMENT,
    )
    second = build_experiment_lifecycle_event(
        payload,
        created_by="tester",
        source_module="tests.test_experiment_lifecycle_contract",
        source_version="1.0",
        created_at=BASE_TIME,
        event_type=LifecycleEventType.ASSIGNMENT,
    )

    required = {
        "experiment_id",
        "experiment_version",
        "assignment_id",
        "assignment_seed",
        "assignment_hash",
        "assignment_version",
        "randomization_unit",
        "eligibility_snapshot_hash",
    }
    assert required.issubset(first.keys())
    assert first["assignment_id"] == second["assignment_id"]
    assert first["assignment_hash"] == second["assignment_hash"]
    assert first["assignment_seed"] == second["assignment_seed"]


def test_eligibility_snapshot_hash_mismatch_rejected() -> None:
    payload = base_assignment_payload(eligibility_snapshot_hash="esh_bad")
    with pytest.raises(ValueError):
        build_experiment_lifecycle_event(
            payload,
            created_by="tester",
            source_module="tests.test_experiment_lifecycle_contract",
            source_version="1.0",
            created_at=BASE_TIME,
            event_type=LifecycleEventType.ASSIGNMENT,
        )


def test_exposure_dedupe_key_is_deterministic() -> None:
    payload = base_exposure_payload()
    first = build_experiment_lifecycle_event(
        payload,
        created_by="tester",
        source_module="tests.test_experiment_lifecycle_contract",
        source_version="1.0",
        created_at=BASE_TIME,
        event_type=LifecycleEventType.EXPOSURE,
    )
    second = build_experiment_lifecycle_event(
        payload,
        created_by="tester",
        source_module="tests.test_experiment_lifecycle_contract",
        source_version="1.0",
        created_at=BASE_TIME,
        event_type=LifecycleEventType.EXPOSURE,
    )
    assert first["exposure_dedupe_key"] == second["exposure_dedupe_key"]
    assert first["exposure_dedupe_key"] == compute_exposure_dedupe_key(first)


def test_contamination_severity_and_record_only_policy() -> None:
    payload = base_contamination_payload(contamination_severity=ContaminationSeverity.HIGH.value)
    row = build_experiment_lifecycle_event(
        payload,
        created_by="tester",
        source_module="tests.test_experiment_lifecycle_contract",
        source_version="1.0",
        created_at=BASE_TIME,
        event_type=LifecycleEventType.CONTAMINATION,
    )
    assert row["contamination_severity"] == ContaminationSeverity.HIGH.value
    assert row["intervention_action"] == "record_only"

    with pytest.raises(ValueError):
        build_experiment_lifecycle_event(
            base_contamination_payload(intervention_action="auto_rollback"),
            created_by="tester",
            source_module="tests.test_experiment_lifecycle_contract",
            source_version="1.0",
            created_at=BASE_TIME,
            event_type=LifecycleEventType.CONTAMINATION,
        )


def test_eligibility_snapshot_hash_function_stable() -> None:
    left = compute_eligibility_snapshot_hash({"b": 2, "a": 1})
    right = compute_eligibility_snapshot_hash({"a": 1, "b": 2})
    assert left == right
