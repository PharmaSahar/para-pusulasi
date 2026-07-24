from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping

from .analytics_snapshot_foundation import AnalyticsSnapshotRecord, AnalyticsSnapshotValidationError
from .dashboard_integration_service import SnapshotReader


class IncrementalSyncValidationError(ValueError):
    """Raised when incremental synchronization planning input is invalid."""


@dataclass(frozen=True, slots=True)
class SyncCursor:
    channel_id: str
    youtube_channel_id: str
    last_snapshot_timestamp: str

    def __post_init__(self) -> None:
        channel_id = str(self.channel_id or "").strip()
        youtube_channel_id = str(self.youtube_channel_id or "").strip()
        if not channel_id:
            raise ValueError("channel_id is required")
        if not youtube_channel_id:
            raise ValueError("youtube_channel_id is required")

        parsed_timestamp = _parse_timestamp(self.last_snapshot_timestamp)

        object.__setattr__(self, "channel_id", channel_id)
        object.__setattr__(self, "youtube_channel_id", youtube_channel_id)
        object.__setattr__(self, "last_snapshot_timestamp", parsed_timestamp.isoformat())


@dataclass(frozen=True, slots=True)
class SyncWatermark:
    channel_id: str
    lower_bound_date: str
    upper_bound_date: str

    def __post_init__(self) -> None:
        channel_id = str(self.channel_id or "").strip()
        if not channel_id:
            raise ValueError("channel_id is required")

        lower = _parse_date(self.lower_bound_date)
        upper = _parse_date(self.upper_bound_date)
        if lower > upper:
            raise ValueError("lower_bound_date must be on or before upper_bound_date")

        object.__setattr__(self, "channel_id", channel_id)
        object.__setattr__(self, "lower_bound_date", lower.isoformat())
        object.__setattr__(self, "upper_bound_date", upper.isoformat())


@dataclass(frozen=True, slots=True)
class SyncPlan:
    channel_id: str
    youtube_channel_id: str
    current_cursor: SyncCursor | None
    next_cursor: SyncCursor
    watermark: SyncWatermark
    missing_ranges: tuple[tuple[str, str], ...]
    should_sync: bool
    retry_metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        channel_id = str(self.channel_id or "").strip()
        youtube_channel_id = str(self.youtube_channel_id or "").strip()
        if not channel_id:
            raise ValueError("channel_id is required")
        if not youtube_channel_id:
            raise ValueError("youtube_channel_id is required")

        parsed_ranges: list[tuple[date, date]] = []
        for start_raw, end_raw in tuple(self.missing_ranges):
            start = _parse_date(start_raw)
            end = _parse_date(end_raw)
            if start > end:
                raise ValueError("range start_date must be on or before end_date")
            parsed_ranges.append((start, end))

        for index in range(1, len(parsed_ranges)):
            previous = parsed_ranges[index - 1]
            current = parsed_ranges[index]
            if current[0] <= previous[1]:
                raise ValueError("missing_ranges must be strictly non-overlapping")

        if self.should_sync and not parsed_ranges:
            raise ValueError("missing_ranges required when should_sync is true")

        if not self.should_sync and parsed_ranges:
            raise ValueError("missing_ranges must be empty when should_sync is false")

        if self.current_cursor is not None:
            cursor_date = _parse_timestamp(self.current_cursor.last_snapshot_timestamp).date()
            lower = _parse_date(self.watermark.lower_bound_date)
            if lower <= cursor_date:
                raise ValueError("watermark must advance beyond current cursor")

        object.__setattr__(self, "channel_id", channel_id)
        object.__setattr__(self, "youtube_channel_id", youtube_channel_id)
        object.__setattr__(self, "missing_ranges", tuple((s.isoformat(), e.isoformat()) for s, e in parsed_ranges))
        object.__setattr__(self, "retry_metadata", dict(self.retry_metadata))


class SyncPlanner:
    """Deterministic planner that produces incremental synchronization ranges."""

    def __init__(self, *, max_retry_attempts: int = 5) -> None:
        self._max_retry_attempts = max(1, int(max_retry_attempts))

    def build_plans(
        self,
        *,
        channel_bindings: Mapping[str, str],
        snapshots_by_channel: Mapping[str, tuple[AnalyticsSnapshotRecord, ...]],
        target_end_date: str,
        default_start_date: str,
        cursors: Mapping[str, SyncCursor] | None = None,
        history_ranges: Mapping[str, tuple[tuple[str, str], ...]] | None = None,
        retry_metadata: Mapping[str, Any] | None = None,
    ) -> tuple[SyncPlan, ...]:
        normalized_bindings = {str(k).strip(): str(v).strip() for k, v in dict(channel_bindings).items() if str(k).strip()}
        if any(not value for value in normalized_bindings.values()):
            raise IncrementalSyncValidationError("youtube_channel_id binding is required")

        ordered_channels = tuple(sorted(normalized_bindings.keys()))
        target_end = _parse_date(target_end_date)
        default_start = _parse_date(default_start_date)

        cursor_map = dict(cursors or {})
        history_map = dict(history_ranges or {})
        base_retry_metadata = self._bounded_retry_metadata(retry_metadata or {})

        plans: list[SyncPlan] = []
        for channel_id in ordered_channels:
            youtube_channel_id = normalized_bindings[channel_id]
            snapshots = tuple(snapshots_by_channel.get(channel_id, ()))
            current_cursor = cursor_map.get(channel_id)
            channel_history = tuple(history_map.get(channel_id, ()))

            plan = self._build_channel_plan(
                channel_id=channel_id,
                youtube_channel_id=youtube_channel_id,
                snapshots=snapshots,
                target_end=target_end,
                default_start=default_start,
                current_cursor=current_cursor,
                history_ranges=channel_history,
                retry_metadata=base_retry_metadata,
            )
            plans.append(plan)

        return tuple(plans)

    def _build_channel_plan(
        self,
        *,
        channel_id: str,
        youtube_channel_id: str,
        snapshots: tuple[AnalyticsSnapshotRecord, ...],
        target_end: date,
        default_start: date,
        current_cursor: SyncCursor | None,
        history_ranges: tuple[tuple[str, str], ...],
        retry_metadata: Mapping[str, Any],
    ) -> SyncPlan:
        latest_snapshot_timestamp = self._latest_snapshot_timestamp(snapshots)
        latest_snapshot_date = _parse_timestamp(latest_snapshot_timestamp).date() if latest_snapshot_timestamp else None

        if current_cursor is not None:
            if current_cursor.channel_id != channel_id:
                raise IncrementalSyncValidationError("cursor channel mismatch")
            if current_cursor.youtube_channel_id != youtube_channel_id:
                raise IncrementalSyncValidationError("cursor youtube channel mismatch")

        cursor_date = _parse_timestamp(current_cursor.last_snapshot_timestamp).date() if current_cursor is not None else None
        base_start = default_start

        if latest_snapshot_date is not None:
            base_start = max(base_start, latest_snapshot_date + timedelta(days=1))

        if cursor_date is not None:
            base_start = max(base_start, cursor_date + timedelta(days=1))
            if cursor_date > target_end:
                raise IncrementalSyncValidationError("cursor timestamp exceeds target_end_date")

        normalized_history = self._normalize_history_ranges(history_ranges)
        if normalized_history and cursor_date is not None:
            latest_history_end = normalized_history[-1][1]
            if cursor_date < latest_history_end:
                raise IncrementalSyncValidationError("cursor is behind history watermark")

        watermark = SyncWatermark(
            channel_id=channel_id,
            lower_bound_date=base_start.isoformat(),
            upper_bound_date=target_end.isoformat(),
        )

        missing_ranges = self._compute_missing_ranges(
            start=base_start,
            end=target_end,
            history_ranges=normalized_history,
        )

        should_sync = len(missing_ranges) > 0
        next_cursor = SyncCursor(
            channel_id=channel_id,
            youtube_channel_id=youtube_channel_id,
            last_snapshot_timestamp=_timestamp_from_date(target_end),
        )

        return SyncPlan(
            channel_id=channel_id,
            youtube_channel_id=youtube_channel_id,
            current_cursor=current_cursor,
            next_cursor=next_cursor,
            watermark=watermark,
            missing_ranges=tuple((left.isoformat(), right.isoformat()) for left, right in missing_ranges),
            should_sync=should_sync,
            retry_metadata=retry_metadata,
        )

    def _normalize_history_ranges(self, history_ranges: tuple[tuple[str, str], ...]) -> list[tuple[date, date]]:
        normalized = [(_parse_date(start), _parse_date(end)) for start, end in history_ranges]
        normalized.sort(key=lambda item: (item[0], item[1]))

        for start, end in normalized:
            if start > end:
                raise IncrementalSyncValidationError("history range start_date must be on or before end_date")

        for index in range(1, len(normalized)):
            previous = normalized[index - 1]
            current = normalized[index]
            if current[0] <= previous[1]:
                raise IncrementalSyncValidationError("overlapping history ranges are not allowed")

        return normalized

    def _compute_missing_ranges(
        self,
        *,
        start: date,
        end: date,
        history_ranges: list[tuple[date, date]],
    ) -> list[tuple[date, date]]:
        if start > end:
            return []

        uncovered: list[tuple[date, date]] = []
        cursor = start

        for covered_start, covered_end in history_ranges:
            if covered_end < cursor:
                continue
            if covered_start > end:
                break

            if covered_start > cursor:
                uncovered_end = min(end, covered_start - timedelta(days=1))
                if cursor <= uncovered_end:
                    uncovered.append((cursor, uncovered_end))

            cursor = max(cursor, covered_end + timedelta(days=1))
            if cursor > end:
                break

        if cursor <= end:
            uncovered.append((cursor, end))

        return uncovered

    def _latest_snapshot_timestamp(self, snapshots: tuple[AnalyticsSnapshotRecord, ...]) -> str | None:
        if not snapshots:
            return None
        ordered = sorted(snapshots, key=lambda item: (item.snapshot_timestamp, item.snapshot_id))
        return ordered[-1].snapshot_timestamp

    def _bounded_retry_metadata(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        bounded = dict(payload)
        max_attempts = int(bounded.get("max_attempts", 1))
        bounded["max_attempts"] = max(1, min(max_attempts, self._max_retry_attempts))
        return bounded


class IncrementalSyncEngine:
    """Computes deterministic incremental synchronization plans for configured channels."""

    def __init__(
        self,
        *,
        snapshot_reader: SnapshotReader,
        planner: SyncPlanner | None = None,
    ) -> None:
        self._snapshot_reader = snapshot_reader
        self._planner = planner or SyncPlanner()

    def compute_plans(
        self,
        *,
        channel_bindings: Mapping[str, str],
        target_end_date: str,
        default_start_date: str,
        cursors: Mapping[str, SyncCursor] | None = None,
        history_ranges: Mapping[str, tuple[tuple[str, str], ...]] | None = None,
        retry_metadata: Mapping[str, Any] | None = None,
    ) -> tuple[SyncPlan, ...]:
        snapshots_by_channel: dict[str, tuple[AnalyticsSnapshotRecord, ...]] = {}
        for channel_id in sorted({str(key).strip() for key in dict(channel_bindings).keys() if str(key).strip()}):
            snapshots_by_channel[channel_id] = self._snapshot_reader.load_channel_snapshots(channel_id)

        return self._planner.build_plans(
            channel_bindings=channel_bindings,
            snapshots_by_channel=snapshots_by_channel,
            target_end_date=target_end_date,
            default_start_date=default_start_date,
            cursors=cursors,
            history_ranges=history_ranges,
            retry_metadata=retry_metadata,
        )


def _parse_date(raw: str) -> date:
    value = str(raw or "").strip()
    if not value:
        raise IncrementalSyncValidationError("date value is required")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise IncrementalSyncValidationError("date must be ISO format YYYY-MM-DD") from exc


def _parse_timestamp(raw: str) -> datetime:
    value = str(raw or "").strip()
    if not value:
        raise IncrementalSyncValidationError("timestamp is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IncrementalSyncValidationError("timestamp must be ISO 8601") from exc
    if parsed.tzinfo is None:
        raise IncrementalSyncValidationError("timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _timestamp_from_date(value: date) -> str:
    return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc).isoformat()


__all__ = [
    "IncrementalSyncEngine",
    "IncrementalSyncValidationError",
    "SyncCursor",
    "SyncPlan",
    "SyncPlanner",
    "SyncWatermark",
]
