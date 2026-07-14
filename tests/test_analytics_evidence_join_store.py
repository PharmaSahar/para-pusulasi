from __future__ import annotations

import json
from pathlib import Path

from src.analytics_evidence_join import (
    AnalyticsEvidenceJoinRecorder,
    AnalyticsEvidenceJoinStore,
    load_analytics_evidence_rows,
)


def test_append_only_malformed_tolerance_and_duplicate(tmp_path: Path) -> None:
    path = tmp_path / "analytics_evidence_join.jsonl"
    path.write_text("{bad json}\n", encoding="utf-8")

    recorder = AnalyticsEvidenceJoinRecorder(output_path=path)
    row = {
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
        "metrics": {"impressions": {"state": "observed", "value": 10}},
        "advisory_only": True,
        "pipeline_output_changed": False,
        "created_at": "2026-07-14T00:00:00+00:00",
    }

    first = recorder.append_joined_record(row=row)
    second = recorder.append_joined_record(row=row)

    assert first.appended is True
    assert second.duplicate is True

    rows, malformed, _errors = load_analytics_evidence_rows(input_path=path)
    assert malformed >= 1
    assert len(rows) == 1


def test_deterministic_serialization(tmp_path: Path) -> None:
    path = tmp_path / "analytics_evidence_join.jsonl"
    store = AnalyticsEvidenceJoinStore(output_path=path)

    row = {
        "schema_version": "v1",
        "analytics_record_id": "aej_demo",
        "source_type": "channel_performance",
        "join_method": "UNRESOLVED",
        "content_id": None,
        "run_id": None,
        "upload_id": None,
        "channel_id": "chan_1",
        "snapshot_time": "2026-07-14T00:00:00+00:00",
        "metrics_version": "v1",
        "provenance": {"source_cursor": "cp:1"},
        "metrics": {"impressions": {"state": "unknown", "value": None}},
        "advisory_only": True,
        "pipeline_output_changed": False,
        "created_at": "2026-07-14T00:00:00+00:00",
    }

    appended = store.append(row)
    assert appended.appended is True

    decoded = json.loads(path.read_text(encoding="utf-8").strip())
    assert list(decoded.keys()) == sorted(decoded.keys())
