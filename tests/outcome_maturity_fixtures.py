from __future__ import annotations

from typing import Any

from src.evidence_reference import build_evidence_reference


BASE_TIME = "2026-07-14T12:00:00+00:00"


def base_outcome_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "decision_id": "dcn_123",
        "learning_record_id": "lrn_123",
        "correlation_id": "corr_123",
        "channel_id": "channel_123",
        "content_id": "content_123",
        "observation_window_type": "TWENTY_FOUR_HOURS",
        "observation_start": "2026-07-13T12:00:00+00:00",
        "observation_end": "2026-07-14T12:00:00+00:00",
        "observation_timestamp": BASE_TIME,
        "decision_record_ref": build_evidence_reference(
            evidence_type="execution_evidence",
            evidence_id="dev_123",
            source_path="logs/decision_memory.jsonl",
            availability_state="available",
            created_at=BASE_TIME,
        ).to_dict(),
        "learning_record_ref": build_evidence_reference(
            evidence_type="analytics_feedback",
            evidence_id="lr_123",
            source_path="logs/historical_learning.jsonl",
            availability_state="available",
            created_at=BASE_TIME,
        ).to_dict(),
        "analytics_evidence_refs": [
            build_evidence_reference(
                evidence_type="analytics_evidence_join",
                evidence_id="aej_123",
                source_path="logs/analytics_evidence_join.jsonl",
                availability_state="available",
                created_at=BASE_TIME,
            ).to_dict()
        ],
        "experiment_evidence_refs": [
            build_evidence_reference(
                evidence_type="experiment_assignment",
                evidence_id="exp_123",
                source_path="output/telemetry/experiments.jsonl",
                availability_state="available",
                created_at=BASE_TIME,
            ).to_dict()
        ],
        "impressions": 1000,
        "ctr_ratio": 0.15,
        "watch_time_hours": 12.5,
        "average_view_duration_seconds": 210.0,
        "average_percentage_viewed_ratio": 0.42,
        "subscribers_gained": 7,
        "likes": 20,
        "comments": 5,
        "maturity_state": "IMMATURE",
        "metric_completeness": 0.8,
        "evidence_completeness": 0.75,
        "sample_sufficiency": 0.3,
        "provisional_status": True,
        "unknown_reasons": ["awaiting_longer_window"],
        "advisory_only": True,
        "pipeline_output_changed": False,
    }
    payload.update(overrides)
    return payload
