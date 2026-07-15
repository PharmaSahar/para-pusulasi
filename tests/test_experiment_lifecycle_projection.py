from __future__ import annotations

from src.experiment_lifecycle_contract import LifecycleEventType, build_experiment_lifecycle_event
from src.experiment_lifecycle_projection import build_experiment_projection_from_rows
from tests.experiment_lifecycle_fixtures import BASE_TIME, base_assignment_payload, base_contamination_payload, base_exposure_payload


def test_projection_is_deterministic_and_replay_derived() -> None:
    assignment = build_experiment_lifecycle_event(
        base_assignment_payload(),
        created_by="tester",
        source_module="tests.test_experiment_lifecycle_projection",
        source_version="1.0",
        created_at=BASE_TIME,
        previous_record_hash=None,
        event_type=LifecycleEventType.ASSIGNMENT,
    )
    exposure = build_experiment_lifecycle_event(
        base_exposure_payload(
            assignment_id=assignment["assignment_id"],
            assignment_seed=assignment["assignment_seed"],
            assignment_hash=assignment["assignment_hash"],
            eligibility_snapshot_hash=assignment["eligibility_snapshot_hash"],
        ),
        created_by="tester",
        source_module="tests.test_experiment_lifecycle_projection",
        source_version="1.0",
        created_at="2026-07-14T12:01:00+00:00",
        previous_record_hash=assignment["record_hash"],
        event_type=LifecycleEventType.EXPOSURE,
    )
    contamination = build_experiment_lifecycle_event(
        base_contamination_payload(
            assignment_id=assignment["assignment_id"],
            assignment_seed=assignment["assignment_seed"],
            assignment_hash=assignment["assignment_hash"],
            eligibility_snapshot_hash=assignment["eligibility_snapshot_hash"],
            contamination_severity="HIGH",
        ),
        created_by="tester",
        source_module="tests.test_experiment_lifecycle_projection",
        source_version="1.0",
        created_at="2026-07-14T12:02:00+00:00",
        previous_record_hash=exposure["record_hash"],
        event_type=LifecycleEventType.CONTAMINATION,
    )

    rows = [contamination, assignment, exposure]
    first = build_experiment_projection_from_rows(rows)
    second = build_experiment_projection_from_rows(rows)

    assert first == second
    assert len(first["current_assignment_by_id"]) == 1
    assert len(first["exposure_events"]) == 1
    assert len(first["contamination_events"]) == 1
    assert first["contamination_severity_counts"]["HIGH"] == 1
