from __future__ import annotations

from typing import Any

from src.evidence_reference import build_evidence_reference


BASE_TIME = "2026-07-14T12:00:00+00:00"


def base_learning_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "decision_id": "dcn_123",
        "correlation_id": "corr_123",
        "channel_id": "channel_123",
        "content_id": "content_123",
        "content_type": "video",
        "window_type": "rolling_24h",
        "window_start": "2026-07-13T12:00:00+00:00",
        "window_end": "2026-07-14T12:00:00+00:00",
        "measurement_timestamp": BASE_TIME,
        "decision_record_ref": build_evidence_reference(
            evidence_type="execution_evidence",
            evidence_id="dev_123",
            source_path="logs/decision_memory.jsonl",
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
        "cqga_evidence_refs": [
            build_evidence_reference(
                evidence_type="cqga_revalidation",
                evidence_id="cqga_123",
                source_path="logs/content_quality_gap_analysis.jsonl",
                availability_state="unknown",
                created_at=BASE_TIME,
            ).to_dict()
        ],
        "runtime_evidence_refs": [
            build_evidence_reference(
                evidence_type="runtime_evidence",
                evidence_id="rt_123",
                source_path="logs/forward_evidence_capture.jsonl",
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
        "topic": "markets",
        "publish_slot": "morning",
        "impressions": 1000,
        "views": 150,
        "ctr_ratio": 0.15,
        "watch_time_hours": 12.5,
        "average_view_duration_seconds": 210.0,
        "average_percentage_viewed_ratio": 0.42,
        "subscribers_gained": 7,
        "likes": 20,
        "comments": 5,
        "maturity_state": "immature",
        "metric_completeness": 0.8,
        "evidence_completeness": 0.75,
        "sample_sufficiency": 0.3,
        "provisional_status": True,
        "unknown_reasons": ["awaiting_longer_window"],
        "advisory_only": True,
        "pipeline_output_changed": False,
        "attribution_extension": {
            "status": "not_implemented",
            "attribution_event_ref": None,
            "attribution_notes": "reserved_for_future_sprint",
        },
    }
    payload.update(overrides)
    return payload
