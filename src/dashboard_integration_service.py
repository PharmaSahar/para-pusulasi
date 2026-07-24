from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .analytics_snapshot_foundation import AnalyticsSnapshotRecord, AnalyticsSnapshotStoreError, AnalyticsSnapshotValidationError
from .analytics_snapshot_writer import SnapshotValidator


@dataclass(frozen=True, slots=True)
class ChannelDashboardSummary:
    channel_id: str
    youtube_channel_id: str | None
    snapshot_count: int
    total_views: int
    total_watch_time_minutes: int
    total_likes: int
    total_comments: int
    latest_snapshot_timestamp: str | None

    def __post_init__(self) -> None:
        if not str(self.channel_id or "").strip():
            raise ValueError("channel_id is required")
        if int(self.snapshot_count) < 0:
            raise ValueError("snapshot_count must be nonnegative")


@dataclass(frozen=True, slots=True)
class DashboardProjection:
    projection_identity: str
    channel_count: int
    snapshot_count: int
    total_views: int
    total_watch_time_minutes: int
    total_likes: int
    total_comments: int
    channel_summaries: tuple[ChannelDashboardSummary, ...]

    def __post_init__(self) -> None:
        if not str(self.projection_identity or "").strip():
            raise ValueError("projection_identity is required")
        if int(self.channel_count) < 0:
            raise ValueError("channel_count must be nonnegative")
        if int(self.snapshot_count) < 0:
            raise ValueError("snapshot_count must be nonnegative")
        object.__setattr__(self, "channel_summaries", tuple(self.channel_summaries))


class ProjectionValidator:
    """Validates snapshots and projection-level consistency."""

    def __init__(self, *, snapshot_validator: SnapshotValidator | None = None) -> None:
        self._snapshot_validator = snapshot_validator or SnapshotValidator()

    def validate_snapshot_payload(self, payload: Mapping[str, Any]) -> AnalyticsSnapshotRecord:
        record = self._snapshot_validator.validate(dict(payload))
        if record.snapshot_date != record.snapshot_timestamp[:10]:
            raise AnalyticsSnapshotValidationError("snapshot_date does not match snapshot_timestamp")
        return record

    def validate_projection(self, projection: DashboardProjection) -> None:
        if projection.channel_count != len(projection.channel_summaries):
            raise AnalyticsSnapshotValidationError("projection channel_count mismatch")

        derived_snapshot_count = sum(item.snapshot_count for item in projection.channel_summaries)
        if projection.snapshot_count != derived_snapshot_count:
            raise AnalyticsSnapshotValidationError("projection snapshot_count mismatch")


class SnapshotReader:
    """Read-only snapshot loader that validates each row against snapshot contract."""

    def __init__(
        self,
        *,
        root: str | Path,
        validator: ProjectionValidator | None = None,
    ) -> None:
        self._root = Path(root).resolve()
        self._validator = validator or ProjectionValidator()

    def load_channel_snapshots(self, channel_id: str) -> tuple[AnalyticsSnapshotRecord, ...]:
        normalized_channel_id = str(channel_id or "").strip()
        if not normalized_channel_id:
            raise AnalyticsSnapshotValidationError("channel_id is required")

        ledger_path = self._root / normalized_channel_id / "snapshots.jsonl"
        if not ledger_path.exists():
            return ()

        rows: list[AnalyticsSnapshotRecord] = []
        for raw_line in ledger_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError as exc:
                raise AnalyticsSnapshotStoreError("malformed ledger content") from exc
            if not isinstance(parsed, dict):
                raise AnalyticsSnapshotStoreError("malformed ledger content")

            row = self._validator.validate_snapshot_payload(parsed)
            if row.channel_id != normalized_channel_id:
                raise AnalyticsSnapshotValidationError("channel mismatch")
            rows.append(row)

        ordered = sorted(rows, key=lambda item: (item.snapshot_timestamp, item.snapshot_id, item.youtube_video_id))
        return tuple(ordered)


class DashboardIntegrationService:
    """Read-only service building deterministic dashboard projections from snapshots."""

    def __init__(
        self,
        *,
        snapshot_reader: SnapshotReader,
        validator: ProjectionValidator | None = None,
    ) -> None:
        self._snapshot_reader = snapshot_reader
        self._validator = validator or ProjectionValidator()

    def build_projection(self, *, channel_ids: tuple[str, ...]) -> DashboardProjection:
        ordered_channels = tuple(sorted({str(value).strip() for value in channel_ids if str(value).strip()}))
        summaries: list[ChannelDashboardSummary] = []

        total_views = 0
        total_watch_time_minutes = 0
        total_likes = 0
        total_comments = 0
        total_snapshots = 0

        for channel_id in ordered_channels:
            snapshots = self._snapshot_reader.load_channel_snapshots(channel_id)

            channel_views = sum(int(item.views or 0) for item in snapshots)
            channel_watch_minutes = sum(int(item.watch_time_minutes or 0) for item in snapshots)
            channel_likes = sum(int(item.likes or 0) for item in snapshots)
            channel_comments = sum(int(item.comments or 0) for item in snapshots)
            latest_snapshot_timestamp = snapshots[-1].snapshot_timestamp if snapshots else None
            youtube_channel_id = snapshots[-1].youtube_channel_id if snapshots else None

            summaries.append(
                ChannelDashboardSummary(
                    channel_id=channel_id,
                    youtube_channel_id=youtube_channel_id,
                    snapshot_count=len(snapshots),
                    total_views=channel_views,
                    total_watch_time_minutes=channel_watch_minutes,
                    total_likes=channel_likes,
                    total_comments=channel_comments,
                    latest_snapshot_timestamp=latest_snapshot_timestamp,
                )
            )

            total_views += channel_views
            total_watch_time_minutes += channel_watch_minutes
            total_likes += channel_likes
            total_comments += channel_comments
            total_snapshots += len(snapshots)

        summary_tuple = tuple(sorted(summaries, key=lambda item: item.channel_id))
        projection_identity = self._build_projection_identity(summary_tuple)

        projection = DashboardProjection(
            projection_identity=projection_identity,
            channel_count=len(summary_tuple),
            snapshot_count=total_snapshots,
            total_views=total_views,
            total_watch_time_minutes=total_watch_time_minutes,
            total_likes=total_likes,
            total_comments=total_comments,
            channel_summaries=summary_tuple,
        )
        self._validator.validate_projection(projection)
        return projection

    def _build_projection_identity(self, channel_summaries: tuple[ChannelDashboardSummary, ...]) -> str:
        payload = {
            "channel_summaries": [
                {
                    "channel_id": item.channel_id,
                    "youtube_channel_id": item.youtube_channel_id,
                    "snapshot_count": item.snapshot_count,
                    "total_views": item.total_views,
                    "total_watch_time_minutes": item.total_watch_time_minutes,
                    "total_likes": item.total_likes,
                    "total_comments": item.total_comments,
                    "latest_snapshot_timestamp": item.latest_snapshot_timestamp,
                }
                for item in channel_summaries
            ]
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        return f"dash_{digest[:24]}"


__all__ = [
    "ChannelDashboardSummary",
    "DashboardIntegrationService",
    "DashboardProjection",
    "ProjectionValidator",
    "SnapshotReader",
]
