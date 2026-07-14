from __future__ import annotations

from pathlib import Path

from src.thumbnail_metadata_lineage import (
    ThumbnailMetadataLineageRecorder,
    build_thumbnail_metadata_lineage_row,
    load_thumbnail_metadata_lineage_rows,
    verify_thumbnail_metadata_lineage_integrity,
)


def _row(tmp_path: Path) -> dict:
    thumb = tmp_path / "thumb.jpg"
    thumb.write_bytes(b"thumb-bytes")
    return build_thumbnail_metadata_lineage_row(
        content_id="content_1",
        run_id="run_1",
        blueprint_id="bp_1",
        planning_id="plan_1",
        thumbnail_prompt="prompt",
        thumbnail_path=str(thumb),
        metadata_version="1.0",
        creation_timestamp="2026-07-14T06:00:00+00:00",
        content_type="video",
        variant_id="var_a",
    )


def test_append_only_and_duplicate_detection(tmp_path: Path) -> None:
    path = tmp_path / "lineage.jsonl"
    recorder = ThumbnailMetadataLineageRecorder(lineage_path=path)
    row = _row(tmp_path)
    first = recorder.append_thumbnail_metadata(row)
    second = recorder.append_thumbnail_metadata(row)

    assert first.appended is True
    assert second.duplicate is True
    rows, malformed, errors = load_thumbnail_metadata_lineage_rows(input_path=path)
    assert len(rows) == 1
    assert malformed == 0
    assert errors == []


def test_integrity_summary_reports_duplicates_and_completeness(tmp_path: Path) -> None:
    path = tmp_path / "lineage.jsonl"
    recorder = ThumbnailMetadataLineageRecorder(lineage_path=path)
    recorder.append_thumbnail_metadata(_row(tmp_path))
    summary = verify_thumbnail_metadata_lineage_integrity(lineage_path=path)

    assert summary["rows"] == 1
    assert summary["thumbnail_generations"] == 1
    assert summary["average_completeness_score"] == 1.0
    assert summary["pipeline_output_changed"] is False