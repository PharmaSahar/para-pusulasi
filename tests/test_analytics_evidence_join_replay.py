from __future__ import annotations

from src.analytics_evidence_join import (
    compute_analytics_join_coverage,
    estimate_cqga_impact,
    replay_analytics_evidence_join,
)


def test_replay_and_coverage_metrics() -> None:
    rows = [
        {
            "schema_version": "v1",
            "analytics_record_id": "aej_1",
            "source_type": "channel_performance",
            "join_method": "BY_CONTENT_ID",
            "content_id": "content_1",
            "run_id": "run_1",
            "upload_id": "video_1",
            "channel_id": "chan_1",
            "snapshot_time": "2026-07-14T00:00:00+00:00",
            "metrics_version": "v1",
            "provenance": {"source_cursor": "cp:1"},
            "metrics": {"impressions": {"state": "observed", "value": 100}},
            "advisory_only": True,
            "pipeline_output_changed": False,
            "created_at": "2026-07-14T00:00:00+00:00",
        },
        {
            "schema_version": "v1",
            "analytics_record_id": "aej_2",
            "source_type": "analytics_feedback",
            "join_method": "UNRESOLVED",
            "content_id": None,
            "run_id": None,
            "upload_id": None,
            "channel_id": "chan_1",
            "snapshot_time": "2026-07-14T00:05:00+00:00",
            "metrics_version": "v1",
            "provenance": {"source_cursor": "af:1"},
            "metrics": {"impressions": {"state": "unknown", "value": None}},
            "advisory_only": True,
            "pipeline_output_changed": False,
            "created_at": "2026-07-14T00:05:00+00:00",
        },
    ]

    state, diagnostics = replay_analytics_evidence_join(rows=rows)
    assert diagnostics.replay_errors == []
    assert list(state.keys()) == ["aej_1", "aej_2"]

    coverage = compute_analytics_join_coverage(joined_rows=list(state.values()))
    assert coverage["total_analytics_rows"] == 2
    assert coverage["joined_count"] == 1
    assert coverage["unresolved_count"] == 1

    impact = estimate_cqga_impact(coverage=coverage)
    assert impact["advisory_only"] is True
    assert impact["pipeline_output_changed"] is False
