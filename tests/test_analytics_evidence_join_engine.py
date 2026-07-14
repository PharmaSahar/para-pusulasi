from __future__ import annotations

import json
from pathlib import Path

from src.analytics_evidence_join import build_analytics_evidence_join_rows


def test_join_priority_content_then_upload_then_run(tmp_path: Path) -> None:
    cp_path = tmp_path / "channel_performance.jsonl"
    af_path = tmp_path / "analytics_feedback.jsonl"
    runtime_dir = tmp_path / "runtime"
    own_dir = tmp_path / "ownership"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    own_dir.mkdir(parents=True, exist_ok=True)

    # runtime with full lineage
    runtime_payload = {
        "content_id": "content_1",
        "run_id": "run_1",
        "channel": "chan_1",
        "video_id": "video_1",
    }
    (runtime_dir / "runtime_1.json").write_text(json.dumps(runtime_payload), encoding="utf-8")

    # source rows: one with content_id, one with upload_id, one with run_id
    cp_rows = [
        {
            "performance_schema_version": "v1",
            "content_id": "content_1",
            "run_id": "wrong_run",
            "video_id": "wrong_video",
            "channel_id": "chan_1",
            "created_at": "2026-07-14T00:00:00+00:00",
            "impressions": 10,
        },
        {
            "performance_schema_version": "v1",
            "content_id": None,
            "run_id": None,
            "video_id": "video_1",
            "channel_id": "chan_1",
            "created_at": "2026-07-14T00:00:10+00:00",
            "impressions": 11,
        },
        {
            "performance_schema_version": "v1",
            "content_id": None,
            "run_id": "run_1",
            "video_id": None,
            "channel_id": "chan_1",
            "created_at": "2026-07-14T00:00:20+00:00",
            "impressions": 12,
        },
    ]
    cp_path.write_text("\n".join(json.dumps(row) for row in cp_rows) + "\n", encoding="utf-8")
    af_path.write_text("", encoding="utf-8")

    built = build_analytics_evidence_join_rows(
        channel_performance_path=cp_path,
        analytics_feedback_path=af_path,
        runtime_evidence_dir=runtime_dir,
        ownership_dir=own_dir,
    )
    assert len(built.joined_records) == 3

    methods = [row["join_method"] for row in built.joined_records]
    assert methods[0] == "BY_CONTENT_ID"
    assert methods[1] == "BY_UPLOAD_ID"
    assert methods[2] == "BY_RUN_ID"
