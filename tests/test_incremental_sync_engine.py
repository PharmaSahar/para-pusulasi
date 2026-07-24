from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.incremental_sync_engine import (
    IncrementalSyncEngine,
    IncrementalSyncValidationError,
    SyncCursor,
    SyncPlanner,
    SyncWatermark,
)
from src.dashboard_integration_service import SnapshotReader


def _snapshot_payload(
    *,
    channel_id: str,
    youtube_channel_id: str,
    snapshot_timestamp: str,
    video_suffix: str,
    views: int = 10,
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "snapshot_timestamp": snapshot_timestamp,
        "snapshot_date": snapshot_timestamp[:10],
        "channel_id": channel_id,
        "youtube_channel_id": youtube_channel_id,
        "internal_video_id": f"vid-{video_suffix}",
        "youtube_video_id": f"yt-{video_suffix}",
        "content_job_id": f"job-{video_suffix}",
        "content_type": "LONG_FORM",
        "metric_source": "fixture",
        "provenance_reference": f"fixture://{video_suffix}",
        "title_at_snapshot": "Example",
        "topic": "analytics",
        "topic_domain": "growth",
        "language": "en",
        "duration_seconds": 120,
        "publication_timestamp": "2026-07-23T10:00:00+00:00",
        "thumbnail_identity": "thumb",
        "prompt_template_version": "v1",
        "impressions": 100,
        "views": views,
        "watch_time_minutes": 5,
        "subscribers_gained": 1,
        "subscribers_lost": 0,
        "likes": 2,
        "comments": 1,
        "shares": 1,
        "impressions_ctr": 0.1,
        "average_view_duration_seconds": 45.0,
        "average_percentage_viewed": 35.0,
        "fetched_at": "2026-07-24T12:05:00+00:00",
        "freshness_status": "fresh",
        "completeness_status": "complete",
        "missing_fields": [],
        "partial_data_reason": None,
        "validation_status": "accepted",
        "source_query_version": "v1",
    }


def _write_ledger(root: Path, channel_id: str, rows: list[dict[str, object]]) -> None:
    folder = root / channel_id
    folder.mkdir(parents=True, exist_ok=True)
    content = "\n".join(json.dumps(item, sort_keys=True) for item in rows)
    if content:
        content += "\n"
    (folder / "snapshots.jsonl").write_text(content, encoding="utf-8")


def _engine(root: Path) -> IncrementalSyncEngine:
    return IncrementalSyncEngine(snapshot_reader=SnapshotReader(root=root), planner=SyncPlanner(max_retry_attempts=5))


def test_first_synchronization(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    plans = engine.compute_plans(
        channel_bindings={"channel_alpha": "UC-alpha"},
        target_end_date="2026-07-10",
        default_start_date="2026-07-01",
    )

    assert len(plans) == 1
    plan = plans[0]
    assert plan.should_sync is True
    assert plan.missing_ranges == (("2026-07-01", "2026-07-10"),)


def test_incremental_synchronization(tmp_path: Path) -> None:
    _write_ledger(
        tmp_path,
        "channel_alpha",
        [
            _snapshot_payload(
                channel_id="channel_alpha",
                youtube_channel_id="UC-alpha",
                snapshot_timestamp="2026-07-10T00:00:00+00:00",
                video_suffix="001",
            )
        ],
    )
    engine = _engine(tmp_path)
    plans = engine.compute_plans(
        channel_bindings={"channel_alpha": "UC-alpha"},
        target_end_date="2026-07-15",
        default_start_date="2026-07-01",
    )

    assert plans[0].missing_ranges == (("2026-07-11", "2026-07-15"),)


def test_empty_history_uses_full_window(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    plans = engine.compute_plans(
        channel_bindings={"channel_alpha": "UC-alpha"},
        target_end_date="2026-07-03",
        default_start_date="2026-07-01",
        history_ranges={"channel_alpha": ()},
    )

    assert plans[0].missing_ranges == (("2026-07-01", "2026-07-03"),)


def test_duplicate_execution_is_idempotent(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    payload = {
        "channel_bindings": {"channel_alpha": "UC-alpha"},
        "target_end_date": "2026-07-05",
        "default_start_date": "2026-07-01",
        "history_ranges": {"channel_alpha": (("2026-07-01", "2026-07-05"),)},
    }

    first = engine.compute_plans(**payload)
    second = engine.compute_plans(**payload)

    assert first == second
    assert first[0].should_sync is False
    assert first[0].missing_ranges == ()


def test_overlapping_history_is_rejected(tmp_path: Path) -> None:
    engine = _engine(tmp_path)

    with pytest.raises(IncrementalSyncValidationError):
        engine.compute_plans(
            channel_bindings={"channel_alpha": "UC-alpha"},
            target_end_date="2026-07-10",
            default_start_date="2026-07-01",
            history_ranges={"channel_alpha": (("2026-07-01", "2026-07-05"), ("2026-07-05", "2026-07-07"))},
        )


def test_deterministic_planning_order(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    first = engine.compute_plans(
        channel_bindings={"channel_b": "UC-b", "channel_a": "UC-a"},
        target_end_date="2026-07-04",
        default_start_date="2026-07-01",
    )
    second = engine.compute_plans(
        channel_bindings={"channel_a": "UC-a", "channel_b": "UC-b"},
        target_end_date="2026-07-04",
        default_start_date="2026-07-01",
    )

    assert [item.channel_id for item in first] == ["channel_a", "channel_b"]
    assert first == second


def test_immutable_models() -> None:
    cursor = SyncCursor(
        channel_id="channel_alpha",
        youtube_channel_id="UC-alpha",
        last_snapshot_timestamp="2026-07-01T00:00:00+00:00",
    )
    watermark = SyncWatermark(
        channel_id="channel_alpha",
        lower_bound_date="2026-07-02",
        upper_bound_date="2026-07-10",
    )

    with pytest.raises(AttributeError):
        cursor.channel_id = "changed"
    with pytest.raises(AttributeError):
        watermark.upper_bound_date = "2026-07-11"


def test_retry_propagation_with_bounds(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    plans = engine.compute_plans(
        channel_bindings={"channel_alpha": "UC-alpha"},
        target_end_date="2026-07-10",
        default_start_date="2026-07-01",
        retry_metadata={"max_attempts": 99, "trace": "sync"},
    )

    assert plans[0].retry_metadata["trace"] == "sync"
    assert plans[0].retry_metadata["max_attempts"] == 5


def test_cursor_consistency_and_watermark_monotonicity(tmp_path: Path) -> None:
    _write_ledger(
        tmp_path,
        "channel_alpha",
        [
            _snapshot_payload(
                channel_id="channel_alpha",
                youtube_channel_id="UC-alpha",
                snapshot_timestamp="2026-07-05T00:00:00+00:00",
                video_suffix="one",
            )
        ],
    )
    engine = _engine(tmp_path)

    plan = engine.compute_plans(
        channel_bindings={"channel_alpha": "UC-alpha"},
        target_end_date="2026-07-10",
        default_start_date="2026-07-01",
        cursors={
            "channel_alpha": SyncCursor(
                channel_id="channel_alpha",
                youtube_channel_id="UC-alpha",
                last_snapshot_timestamp="2026-07-06T00:00:00+00:00",
            )
        },
    )[0]

    assert plan.watermark.lower_bound_date == "2026-07-07"
    assert plan.next_cursor.last_snapshot_timestamp.startswith("2026-07-10T00:00:00")


def test_no_forbidden_runtime_behaviors_in_source() -> None:
    source = Path("src/incremental_sync_engine.py").read_text(encoding="utf-8").lower()
    forbidden = [
        "scheduler",
        "cron",
        "polling",
        "upload",
        "deploy",
        "production",
        "dashboardintegrationservice(",
        "write_text(",
        "thread",
        "asyncio.gather",
    ]
    for token in forbidden:
        assert token not in source
