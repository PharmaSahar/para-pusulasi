from __future__ import annotations

from src.unresolved_analytics_recovery import PHASE4C_SCHEMA_VERSION, determine_snapshot_dispositions


def _row(record_id: str, *, row_hash: str, content_id: str = "content_1", youtube_video_id: str = "vid_1", run_id: str = "run_1", snapshot_start: str = "2026-07-10", snapshot_end: str = "2026-07-10", metric_definition_version: str = "v1", source_row=None):
    return {
        "schema_version": PHASE4C_SCHEMA_VERSION,
        "unresolved_record_id": record_id,
        "content_id": content_id,
        "youtube_video_id": youtube_video_id,
        "run_id": run_id,
        "snapshot_start": snapshot_start,
        "snapshot_end": snapshot_end,
        "row_hash": row_hash,
        "metric_definition_version": metric_definition_version,
        "source_row": source_row or {"title": "Example"},
    }


def test_exact_duplicate_source_row_detected() -> None:
    rows = [_row("a", row_hash="same"), _row("b", row_hash="same")]
    out = determine_snapshot_dispositions(rows)
    assert out["a"]["status"] == "DUPLICATE_SOURCE_ROW"
    assert out["b"]["status"] == "DUPLICATE_SOURCE_ROW"


def test_exact_duplicate_snapshot_detected() -> None:
    rows = [_row("a", row_hash="one"), _row("b", row_hash="two")]
    out = determine_snapshot_dispositions(rows)
    assert out["a"]["status"] == "DUPLICATE_SNAPSHOT"


def test_valid_later_snapshot_and_overlap_and_incompatible_definition() -> None:
    rows = [
        _row("a", row_hash="one", snapshot_start="2026-07-10", snapshot_end="2026-07-10", metric_definition_version="v1"),
        _row("b", row_hash="two", snapshot_start="2026-07-11", snapshot_end="2026-07-11", metric_definition_version="v1"),
        _row("c", row_hash="three", snapshot_start="2026-07-10", snapshot_end="2026-07-12", metric_definition_version="v2"),
    ]
    out = determine_snapshot_dispositions(rows)
    assert out["a"]["later_valid_snapshot"] is True
    assert out["a"]["overlapping_snapshot"] is True
    assert out["a"]["incompatible_snapshot_definition"] is True


def test_aggregate_row_flagged() -> None:
    rows = [_row("agg", row_hash="agg", content_id="", youtube_video_id="", run_id="", source_row={"title": "Total"})]
    out = determine_snapshot_dispositions(rows)
    assert out["agg"]["aggregate_row"] is True