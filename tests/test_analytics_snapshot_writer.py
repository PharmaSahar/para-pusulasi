from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from src.analytics_snapshot_foundation import AnalyticsSnapshotRecord, AnalyticsSnapshotStoreError, AnalyticsSnapshotValidationError
from src.analytics_snapshot_writer import AnalyticsSnapshotWriter, LocalFileOperations, SnapshotValidator, SnapshotWriteResult


def _snapshot_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "schema_version": "1.0",
        "snapshot_timestamp": "2026-07-24T12:00:00+00:00",
        "snapshot_date": "2026-07-24",
        "channel_id": "channel_alpha",
        "youtube_channel_id": "UC-alpha",
        "internal_video_id": "video-001",
        "youtube_video_id": "yt-video-001",
        "content_job_id": "job-001",
        "content_type": "LONG_FORM",
        "metric_source": "fixture",
        "provenance_reference": "fixture://evidence/001",
        "title_at_snapshot": "Example",
        "topic": "analytics",
        "topic_domain": "growth",
        "language": "en",
        "duration_seconds": 180,
        "publication_timestamp": "2026-07-23T10:00:00+00:00",
        "thumbnail_identity": "thumb-001",
        "prompt_template_version": "v1",
        "impressions": 100,
        "views": 90,
        "watch_time_minutes": 15,
        "subscribers_gained": 2,
        "subscribers_lost": 0,
        "likes": 5,
        "comments": 1,
        "shares": 1,
        "impressions_ctr": 0.12,
        "average_view_duration_seconds": 45.5,
        "average_percentage_viewed": 42.1,
        "fetched_at": "2026-07-24T12:05:00+00:00",
        "freshness_status": "fresh",
        "completeness_status": "complete",
        "missing_fields": [],
        "partial_data_reason": None,
        "validation_status": "accepted",
        "source_query_version": "v1",
    }
    payload.update(overrides)
    return payload


def test_successful_write() -> None:
    with pytest.TempPathFactory().mktemp("data") as _:
        pass


def test_successful_write(tmp_path: Path) -> None:
    writer = AnalyticsSnapshotWriter(root=tmp_path)
    result = writer.write_channel_snapshots(
        channel_id="channel_alpha",
        snapshots=(_snapshot_payload(),),
    )

    assert isinstance(result, SnapshotWriteResult)
    assert result.persisted_count == 1
    assert result.duplicate_count == 0

    ledger = tmp_path / "channel_alpha" / "snapshots.jsonl"
    lines = ledger.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1


def test_atomic_replacement_uses_temp_strategy(tmp_path: Path) -> None:
    writer = AnalyticsSnapshotWriter(root=tmp_path)
    writer.write_channel_snapshots(channel_id="channel_alpha", snapshots=(_snapshot_payload(),))

    ledger = tmp_path / "channel_alpha" / "snapshots.jsonl"
    first_content = ledger.read_text(encoding="utf-8")

    result = writer.write_channel_snapshots(
        channel_id="channel_alpha",
        snapshots=(_snapshot_payload(youtube_video_id="yt-video-002", internal_video_id="video-002"),),
    )

    assert result.persisted_count == 1
    second_content = ledger.read_text(encoding="utf-8")
    assert first_content != second_content
    assert not (tmp_path / "channel_alpha" / "snapshots.jsonl.tmp").exists()


def test_duplicate_prevention_and_idempotency(tmp_path: Path) -> None:
    writer = AnalyticsSnapshotWriter(root=tmp_path)
    first = writer.write_channel_snapshots(channel_id="channel_alpha", snapshots=(_snapshot_payload(),))
    second = writer.write_channel_snapshots(channel_id="channel_alpha", snapshots=(_snapshot_payload(),))

    assert first.persisted_count == 1
    assert second.persisted_count == 0
    assert second.duplicate_count == 1

    ledger = tmp_path / "channel_alpha" / "snapshots.jsonl"
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 1


def test_conflicting_duplicate_is_rejected(tmp_path: Path) -> None:
    writer = AnalyticsSnapshotWriter(root=tmp_path)
    writer.write_channel_snapshots(channel_id="channel_alpha", snapshots=(_snapshot_payload(),))

    conflict = _snapshot_payload(title_at_snapshot="changed title")
    with pytest.raises(AnalyticsSnapshotStoreError):
        writer.write_channel_snapshots(channel_id="channel_alpha", snapshots=(conflict,))


def test_rollback_on_replace_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    writer = AnalyticsSnapshotWriter(root=tmp_path)
    writer.write_channel_snapshots(channel_id="channel_alpha", snapshots=(_snapshot_payload(),))

    ledger = tmp_path / "channel_alpha" / "snapshots.jsonl"
    before = ledger.read_text(encoding="utf-8")

    original_replace = LocalFileOperations.replace

    def _boom(self: LocalFileOperations, source: Path, destination: Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(LocalFileOperations, "replace", _boom)

    with pytest.raises(OSError):
        writer.write_channel_snapshots(
            channel_id="channel_alpha",
            snapshots=(_snapshot_payload(youtube_video_id="yt-video-003", internal_video_id="video-003"),),
        )

    assert ledger.read_text(encoding="utf-8") == before
    assert not (tmp_path / "channel_alpha" / "snapshots.jsonl.tmp").exists()

    monkeypatch.setattr(LocalFileOperations, "replace", original_replace)


def test_invalid_schema_rejection(tmp_path: Path) -> None:
    writer = AnalyticsSnapshotWriter(root=tmp_path)

    with pytest.raises(AnalyticsSnapshotValidationError):
        writer.write_channel_snapshots(
            channel_id="channel_alpha",
            snapshots=(_snapshot_payload(schema_version="2.0"),),
        )


def test_timestamp_consistency_validation(tmp_path: Path) -> None:
    writer = AnalyticsSnapshotWriter(root=tmp_path)

    with pytest.raises(AnalyticsSnapshotValidationError):
        writer.write_channel_snapshots(
            channel_id="channel_alpha",
            snapshots=(_snapshot_payload(snapshot_date="2026-07-25"),),
        )


def test_channel_mismatch_rejected(tmp_path: Path) -> None:
    writer = AnalyticsSnapshotWriter(root=tmp_path)

    with pytest.raises(AnalyticsSnapshotValidationError):
        writer.write_channel_snapshots(
            channel_id="channel_alpha",
            snapshots=(_snapshot_payload(channel_id="channel_beta"),),
        )


def test_deterministic_output(tmp_path: Path) -> None:
    writer_a = AnalyticsSnapshotWriter(root=tmp_path / "a")
    writer_b = AnalyticsSnapshotWriter(root=tmp_path / "b")

    one = _snapshot_payload(youtube_video_id="yt-video-010", internal_video_id="video-010")
    two = _snapshot_payload(youtube_video_id="yt-video-020", internal_video_id="video-020")

    writer_a.write_channel_snapshots(channel_id="channel_alpha", snapshots=(one, two))
    writer_b.write_channel_snapshots(channel_id="channel_alpha", snapshots=(two, one))

    a_text = (tmp_path / "a" / "channel_alpha" / "snapshots.jsonl").read_text(encoding="utf-8")
    b_text = (tmp_path / "b" / "channel_alpha" / "snapshots.jsonl").read_text(encoding="utf-8")
    assert a_text == b_text


def test_immutable_models() -> None:
    result = SnapshotWriteResult(
        channel_id="channel_alpha",
        persisted_count=1,
        duplicate_count=0,
        total_requested=1,
        snapshot_ids=("abc",),
        ledger_path="/tmp/channel_alpha/snapshots.jsonl",
    )
    with pytest.raises(AttributeError):
        result.persisted_count = 2

    record = SnapshotValidator().validate(_snapshot_payload())
    assert isinstance(record, AnalyticsSnapshotRecord)
    with pytest.raises(AttributeError):
        record.channel_id = "changed"


def test_duplicate_snapshot_identity_in_single_request_is_idempotent(tmp_path: Path) -> None:
    writer = AnalyticsSnapshotWriter(root=tmp_path)
    payload = _snapshot_payload()
    result = writer.write_channel_snapshots(
        channel_id="channel_alpha",
        snapshots=(payload, dict(payload)),
    )

    assert result.persisted_count == 1
    assert result.duplicate_count == 1


def test_no_forbidden_runtime_behaviors_in_source() -> None:
    source = Path("src/analytics_snapshot_writer.py").read_text(encoding="utf-8").lower()
    forbidden = [
        "dashboard",
        "scheduler",
        "cron",
        "polling",
        "upload",
        "deploy",
        "database",
        "production",
    ]
    for token in forbidden:
        assert token not in source
