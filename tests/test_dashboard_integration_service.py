from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.analytics_snapshot_foundation import AnalyticsSnapshotValidationError
from src.dashboard_integration_service import DashboardIntegrationService, DashboardProjection, ProjectionValidator, SnapshotReader


def _snapshot_payload(
    *,
    channel_id: str,
    youtube_channel_id: str,
    youtube_video_id: str,
    internal_video_id: str,
    snapshot_timestamp: str,
    views: int,
    watch_time_minutes: int,
    likes: int,
    comments: int,
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "snapshot_timestamp": snapshot_timestamp,
        "snapshot_date": snapshot_timestamp[:10],
        "channel_id": channel_id,
        "youtube_channel_id": youtube_channel_id,
        "internal_video_id": internal_video_id,
        "youtube_video_id": youtube_video_id,
        "content_job_id": f"job-{internal_video_id}",
        "content_type": "LONG_FORM",
        "metric_source": "fixture",
        "provenance_reference": f"fixture://{internal_video_id}",
        "title_at_snapshot": "Example",
        "topic": "analytics",
        "topic_domain": "growth",
        "language": "en",
        "duration_seconds": 120,
        "publication_timestamp": "2026-07-23T10:00:00+00:00",
        "thumbnail_identity": "thumb-1",
        "prompt_template_version": "v1",
        "impressions": 100,
        "views": views,
        "watch_time_minutes": watch_time_minutes,
        "subscribers_gained": 1,
        "subscribers_lost": 0,
        "likes": likes,
        "comments": comments,
        "shares": 1,
        "impressions_ctr": 0.12,
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
    channel_dir = root / channel_id
    channel_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = channel_dir / "snapshots.jsonl"
    content = "\n".join(json.dumps(row, sort_keys=True) for row in rows)
    if content:
        content += "\n"
    ledger_path.write_text(content, encoding="utf-8")


def test_successful_projection(tmp_path: Path) -> None:
    _write_ledger(
        tmp_path,
        "channel_alpha",
        [
            _snapshot_payload(
                channel_id="channel_alpha",
                youtube_channel_id="UC-alpha",
                youtube_video_id="yt-001",
                internal_video_id="vid-001",
                snapshot_timestamp="2026-07-24T12:00:00+00:00",
                views=10,
                watch_time_minutes=5,
                likes=2,
                comments=1,
            )
        ],
    )

    service = DashboardIntegrationService(snapshot_reader=SnapshotReader(root=tmp_path))
    projection = service.build_projection(channel_ids=("channel_alpha",))

    assert isinstance(projection, DashboardProjection)
    assert projection.channel_count == 1
    assert projection.snapshot_count == 1
    assert projection.total_views == 10


def test_invalid_snapshot_rejection(tmp_path: Path) -> None:
    _write_ledger(
        tmp_path,
        "channel_alpha",
        [
            _snapshot_payload(
                channel_id="channel_alpha",
                youtube_channel_id="UC-alpha",
                youtube_video_id="yt-001",
                internal_video_id="vid-001",
                snapshot_timestamp="2026-07-24T12:00:00+00:00",
                views=-1,
                watch_time_minutes=5,
                likes=2,
                comments=1,
            )
        ],
    )

    service = DashboardIntegrationService(snapshot_reader=SnapshotReader(root=tmp_path))
    with pytest.raises(AnalyticsSnapshotValidationError):
        service.build_projection(channel_ids=("channel_alpha",))


def test_deterministic_ordering(tmp_path: Path) -> None:
    _write_ledger(
        tmp_path,
        "channel_b",
        [
            _snapshot_payload(
                channel_id="channel_b",
                youtube_channel_id="UC-b",
                youtube_video_id="yt-b1",
                internal_video_id="vid-b1",
                snapshot_timestamp="2026-07-24T12:01:00+00:00",
                views=4,
                watch_time_minutes=2,
                likes=1,
                comments=0,
            )
        ],
    )
    _write_ledger(
        tmp_path,
        "channel_a",
        [
            _snapshot_payload(
                channel_id="channel_a",
                youtube_channel_id="UC-a",
                youtube_video_id="yt-a1",
                internal_video_id="vid-a1",
                snapshot_timestamp="2026-07-24T12:00:00+00:00",
                views=3,
                watch_time_minutes=1,
                likes=1,
                comments=1,
            )
        ],
    )

    service = DashboardIntegrationService(snapshot_reader=SnapshotReader(root=tmp_path))
    first = service.build_projection(channel_ids=("channel_b", "channel_a"))
    second = service.build_projection(channel_ids=("channel_a", "channel_b"))

    assert [item.channel_id for item in first.channel_summaries] == ["channel_a", "channel_b"]
    assert first == second


def test_immutable_projection() -> None:
    projection = DashboardProjection(
        projection_identity="dash_test",
        channel_count=0,
        snapshot_count=0,
        total_views=0,
        total_watch_time_minutes=0,
        total_likes=0,
        total_comments=0,
        channel_summaries=(),
    )
    with pytest.raises(AttributeError):
        projection.total_views = 99


def test_multiple_channel_aggregation(tmp_path: Path) -> None:
    _write_ledger(
        tmp_path,
        "channel_alpha",
        [
            _snapshot_payload(
                channel_id="channel_alpha",
                youtube_channel_id="UC-alpha",
                youtube_video_id="yt-001",
                internal_video_id="vid-001",
                snapshot_timestamp="2026-07-24T12:00:00+00:00",
                views=10,
                watch_time_minutes=5,
                likes=2,
                comments=1,
            ),
            _snapshot_payload(
                channel_id="channel_alpha",
                youtube_channel_id="UC-alpha",
                youtube_video_id="yt-002",
                internal_video_id="vid-002",
                snapshot_timestamp="2026-07-24T12:05:00+00:00",
                views=7,
                watch_time_minutes=4,
                likes=1,
                comments=1,
            ),
        ],
    )
    _write_ledger(
        tmp_path,
        "channel_beta",
        [
            _snapshot_payload(
                channel_id="channel_beta",
                youtube_channel_id="UC-beta",
                youtube_video_id="yt-101",
                internal_video_id="vid-101",
                snapshot_timestamp="2026-07-24T12:03:00+00:00",
                views=9,
                watch_time_minutes=6,
                likes=3,
                comments=2,
            )
        ],
    )

    service = DashboardIntegrationService(snapshot_reader=SnapshotReader(root=tmp_path))
    projection = service.build_projection(channel_ids=("channel_beta", "channel_alpha"))

    assert projection.channel_count == 2
    assert projection.snapshot_count == 3
    assert projection.total_views == 26
    assert projection.total_watch_time_minutes == 15
    assert projection.total_likes == 6
    assert projection.total_comments == 4


def test_empty_snapshot_handling(tmp_path: Path) -> None:
    service = DashboardIntegrationService(snapshot_reader=SnapshotReader(root=tmp_path))
    projection = service.build_projection(channel_ids=("channel_alpha", "channel_beta"))

    assert projection.channel_count == 2
    assert projection.snapshot_count == 0
    assert projection.total_views == 0


def test_projection_validator_consistency_check() -> None:
    validator = ProjectionValidator()
    bad_projection = DashboardProjection(
        projection_identity="dash_bad",
        channel_count=2,
        snapshot_count=0,
        total_views=0,
        total_watch_time_minutes=0,
        total_likes=0,
        total_comments=0,
        channel_summaries=(),
    )

    with pytest.raises(AnalyticsSnapshotValidationError):
        validator.validate_projection(bad_projection)


def test_no_forbidden_runtime_behaviors_in_source() -> None:
    source = Path("src/dashboard_integration_service.py").read_text(encoding="utf-8").lower()
    forbidden = [
        "scheduler",
        "cron",
        "polling",
        "upload",
        "deploy",
        "production",
        "write_text(",
        ".write(",
        "analyticsliveclient",
    ]
    for token in forbidden:
        assert token not in source
