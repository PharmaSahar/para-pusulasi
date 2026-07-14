from __future__ import annotations

import json
from pathlib import Path

from src.analytics_evidence_join import build_analytics_evidence_join_rows


def test_never_joins_by_title_filename_or_timestamp_proximity(tmp_path: Path) -> None:
    cp_path = tmp_path / "channel_performance.jsonl"
    af_path = tmp_path / "analytics_feedback.jsonl"
    runtime_dir = tmp_path / "runtime"
    own_dir = tmp_path / "ownership"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    own_dir.mkdir(parents=True, exist_ok=True)

    # runtime row has matching title-like semantics but different deterministic identifiers
    runtime_payload = {
        "content_id": "content_a",
        "run_id": "run_a",
        "channel": "chan_1",
        "video_id": "video_a",
        "title": "Ayni Baslik",
        "created_at": "2026-07-14T10:00:00+00:00",
    }
    (runtime_dir / "runtime_a.json").write_text(json.dumps(runtime_payload), encoding="utf-8")

    # analytics row intentionally shares title/time hints but has no content_id/upload_id/run_id
    cp_row = {
        "performance_schema_version": "v1",
        "channel_id": "chan_1",
        "title": "Ayni Baslik",
        "created_at": "2026-07-14T10:00:01+00:00",
        "thumbnail_path": "output/videos/a.png",
        "impressions": 10,
    }
    cp_path.write_text(json.dumps(cp_row) + "\n", encoding="utf-8")
    af_path.write_text("", encoding="utf-8")

    built = build_analytics_evidence_join_rows(
        channel_performance_path=cp_path,
        analytics_feedback_path=af_path,
        runtime_evidence_dir=runtime_dir,
        ownership_dir=own_dir,
    )

    assert len(built.joined_records) == 1
    assert built.joined_records[0]["join_method"] == "UNRESOLVED"
