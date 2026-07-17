"""Daily channel performance snapshot and aggregation helpers."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from .analytics_quality_guard import validate_performance_snapshot


PERFORMANCE_SCHEMA_VERSION = "v1"
DEFAULT_PERFORMANCE_PATH = Path("logs/channel_performance.jsonl")


def _parse_dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return datetime.now(timezone.utc)


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _latest_value(rows: list[dict[str, Any]], key: str):
    for row in reversed(rows):
        value = row.get(key)
        if value is not None:
            return value
    return None


def build_performance_snapshot(
    *,
    channel_id: str,
    content_id: str,
    run_id: str,
    title: str,
    youtube_url: str | None = None,
    short_url: str | None = None,
    video_id: str | None = None,
    short_video_id: str | None = None,
    publish_at: str | None = None,
    thumbnail_path: str | None = None,
    thumbnail_strategy: str | None = None,
    render_metrics: dict | None = None,
    analytics_join_metadata: dict | None = None,
    quality_score_metadata: dict | None = None,
    youtube_stats: dict | None = None,
    youtube_analytics: dict | None = None,
) -> dict:
    render_metrics = render_metrics or {}
    analytics_join_metadata = analytics_join_metadata or {}
    quality_score_metadata = quality_score_metadata or {}
    youtube_stats = youtube_stats or {}
    youtube_analytics = youtube_analytics or {}

    return {
        "performance_schema_version": PERFORMANCE_SCHEMA_VERSION,
        "day": (_parse_dt(publish_at).date().isoformat() if publish_at else datetime.now(timezone.utc).date().isoformat()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "channel_id": channel_id,
        "content_id": content_id,
        "run_id": run_id,
        "title": title,
        "youtube_url": youtube_url,
        "short_url": short_url,
        "video_id": video_id,
        "short_video_id": short_video_id,
        "thumbnail_path": thumbnail_path,
        "thumbnail_strategy": thumbnail_strategy,
        "hook_score": quality_score_metadata.get("hook_score"),
        "structure_score": quality_score_metadata.get("structure_score"),
        "thumbnail_attention_score": quality_score_metadata.get("thumbnail_attention_score"),
        "retention_signal_score": quality_score_metadata.get("retention_signal_score"),
        "overall_quality_score": quality_score_metadata.get("overall_quality_score"),
        "render_status": render_metrics.get("render_status"),
        "render_duration_seconds": render_metrics.get("render_duration_seconds"),
        "render_resolution": render_metrics.get("output_resolution"),
        "render_fps": render_metrics.get("output_fps"),
        "prompt_version": analytics_join_metadata.get("prompt_version"),
        "model_version": analytics_join_metadata.get("model_version"),
        "channel_dna_version": analytics_join_metadata.get("channel_dna_version"),
        "channel_dna_id": analytics_join_metadata.get("channel_dna_id"),
        "channel_subscribers": youtube_stats.get("subscribers"),
        "channel_total_views": youtube_stats.get("total_views"),
        "channel_video_count": youtube_stats.get("video_count"),
        "impressions": youtube_analytics.get("impressions"),
        "click_through_rate": youtube_analytics.get("click_through_rate"),
        "average_view_duration_seconds": youtube_analytics.get("average_view_duration_seconds"),
        "average_view_percentage": youtube_analytics.get("average_view_percentage"),
        "watch_time_hours": youtube_analytics.get("watch_time_hours"),
    }


def append_performance_snapshot(
    snapshot: dict,
    *,
    history_path: Path | str = DEFAULT_PERFORMANCE_PATH,
) -> None:
    path = Path(history_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = dict(snapshot)
    payload.setdefault("created_at", datetime.now(timezone.utc).isoformat())

    existing_rows = load_recent_performance_snapshots(history_path=path, lookback_days=60, max_items=5000)
    validation = validate_performance_snapshot(payload, existing_rows=existing_rows)
    if not validation.accepted:
        raise ValueError(validation.reason_code)
    if validation.duplicate:
        return

    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def load_recent_performance_snapshots(
    *,
    history_path: Path | str = DEFAULT_PERFORMANCE_PATH,
    lookback_days: int = 30,
    max_items: int = 1000,
) -> list[dict[str, Any]]:
    path = Path(history_path)
    if not path.exists():
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, lookback_days))
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw:
                continue
            try:
                item = json.loads(raw)
            except Exception:
                continue
            created_at = _parse_dt(item.get("created_at"))
            if created_at >= cutoff:
                rows.append(item)
    except Exception:
        return []

    return rows[-max_items:]


def build_daily_performance_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        day = str(row.get("day") or _parse_dt(row.get("created_at")).date().isoformat())
        channel_id = str(row.get("channel_id") or "default")
        grouped[(day, channel_id)].append(row)

    table: list[dict[str, Any]] = []
    for (day, channel_id), bucket in sorted(grouped.items()):
        numeric_fields = [
            "hook_score",
            "structure_score",
            "thumbnail_attention_score",
            "retention_signal_score",
            "overall_quality_score",
            "render_duration_seconds",
            "click_through_rate",
            "average_view_duration_seconds",
            "average_view_percentage",
            "watch_time_hours",
            "impressions",
        ]
        row = {
            "day": day,
            "channel_id": channel_id,
            "videos_published": len(bucket),
            "shorts_published": sum(1 for item in bucket if item.get("short_url")),
            "latest_title": _latest_value(bucket, "title"),
            "latest_youtube_url": _latest_value(bucket, "youtube_url"),
            "latest_short_url": _latest_value(bucket, "short_url"),
            "latest_channel_subscribers": _latest_value(bucket, "channel_subscribers"),
            "latest_channel_total_views": _latest_value(bucket, "channel_total_views"),
            "latest_channel_video_count": _latest_value(bucket, "channel_video_count"),
            "latest_thumbnail_strategy": _latest_value(bucket, "thumbnail_strategy"),
        }
        for field in numeric_fields:
            values = [_safe_float(item.get(field)) for item in bucket]
            values = [value for value in values if value is not None]
            row[f"avg_{field}"] = round(mean(values), 3) if values else None
        table.append(row)

    return table
