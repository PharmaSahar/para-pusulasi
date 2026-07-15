from __future__ import annotations

from typing import Any


BASE_TIME = "2026-07-14T12:00:00+00:00"


def base_assignment_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "experiment_id": "exp_lifecycle_001",
        "experiment_version": "4.0.0",
        "assignment_version": "v1",
        "randomization_unit": "channel_id",
        "randomization_key": "channel_001",
        "eligibility_snapshot": {
            "channel_id": "channel_001",
            "content_type": "video",
            "country": "TR",
            "language": "tr",
        },
        "assigned_variant": "control",
    }
    payload.update(overrides)
    return payload


def base_exposure_payload(**overrides: Any) -> dict[str, Any]:
    payload = base_assignment_payload(
        exposure_name="thumbnail_rendered",
        exposure_timestamp="2026-07-14T12:01:00+00:00",
    )
    payload.update(overrides)
    return payload


def base_contamination_payload(**overrides: Any) -> dict[str, Any]:
    payload = base_assignment_payload(
        contamination_severity="LOW",
        contamination_reason="cross_assignment_touchpoint",
        intervention_action="record_only",
    )
    payload.update(overrides)
    return payload
