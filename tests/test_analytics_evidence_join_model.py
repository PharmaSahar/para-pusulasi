from __future__ import annotations

import pytest

from src.analytics_evidence_join import (
    ANALYTICS_EVIDENCE_JOIN_SCHEMA_VERSION,
    AnalyticsJoinMethod,
    MetricAvailability,
    compute_analytics_record_id,
    validate_analytics_evidence_row,
)


def test_enum_values_stable() -> None:
    assert MetricAvailability.OBSERVED.value == "observed"
    assert MetricAvailability.UNAVAILABLE.value == "unavailable"
    assert MetricAvailability.UNKNOWN.value == "unknown"
    assert AnalyticsJoinMethod.BY_CONTENT_ID.value == "BY_CONTENT_ID"


def test_analytics_record_id_is_deterministic() -> None:
    a = compute_analytics_record_id(
        source_type="channel_performance",
        source_cursor="cp:1",
        snapshot_time="2026-07-14T00:00:00+00:00",
        content_id="content_1",
        run_id="run_1",
        upload_id="video_1",
        channel_id="chan_1",
    )
    b = compute_analytics_record_id(
        source_type="channel_performance",
        source_cursor="cp:1",
        snapshot_time="2026-07-14T00:00:00+00:00",
        content_id="content_1",
        run_id="run_1",
        upload_id="video_1",
        channel_id="chan_1",
    )
    assert a == b


def test_validate_requires_advisory_and_no_mutation() -> None:
    row = {
        "schema_version": ANALYTICS_EVIDENCE_JOIN_SCHEMA_VERSION,
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
        "metrics": {
            "impressions": {"state": "observed", "value": 100},
            "ctr": {"state": "unavailable", "value": None},
        },
        "advisory_only": True,
        "pipeline_output_changed": False,
        "created_at": "2026-07-14T00:00:00+00:00",
    }
    ok = validate_analytics_evidence_row(row)
    assert ok["pipeline_output_changed"] is False

    bad = dict(row)
    bad["pipeline_output_changed"] = True
    with pytest.raises(ValueError):
        validate_analytics_evidence_row(bad)
