"""Live YouTube Analytics API helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from googleapiclient.errors import HttpError

from .youtube_auth import get_authenticated_analytics_service

logger = logging.getLogger(__name__)

DEFAULT_METRICS = (
    "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,"
    "impressions,impressionClickThroughRate,subscribersGained,subscribersLost,likes,comments,shares"
)


def _parse_date(value: str | None) -> str:
    if not value:
        return datetime.now(timezone.utc).date().isoformat()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except Exception:
        return datetime.now(timezone.utc).date().isoformat()


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_video_analytics(
    *,
    video_id: str,
    channel_cfg=None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """Fetch live YouTube Analytics metrics for a single video."""
    service = get_authenticated_analytics_service(channel_cfg=channel_cfg)
    start = _parse_date(start_date)
    end = _parse_date(end_date)

    try:
        response = service.reports().query(
            ids="channel==MINE",
            startDate=start,
            endDate=end,
            metrics=DEFAULT_METRICS,
            dimensions="video",
            filters=f"video=={video_id}",
            maxResults=1,
        ).execute()
    except HttpError as exc:
        logger.warning("YouTube Analytics query failed for %s: %s", video_id, exc)
        raise

    rows = response.get("rows") or []
    if not rows:
        return {
            "video_id": video_id,
            "start_date": start,
            "end_date": end,
            "impressions": None,
            "click_through_rate": None,
            "average_view_duration_seconds": None,
            "average_view_percentage": None,
            "watch_time_hours": None,
            "views": None,
            "estimated_minutes_watched": None,
            "subscribers_gained": None,
            "subscribers_lost": None,
            "likes": None,
            "comments": None,
            "shares": None,
        }

    row = rows[0]
    metrics = response.get("columnHeaders") or []
    values = {header.get("name"): row[idx] for idx, header in enumerate(metrics) if header.get("name")}

    estimated_minutes_watched = _as_float(values.get("estimatedMinutesWatched"))
    watch_time_hours = (estimated_minutes_watched / 60.0) if estimated_minutes_watched is not None else None

    return {
        "video_id": video_id,
        "start_date": start,
        "end_date": end,
        "views": int(values.get("views")) if values.get("views") is not None else None,
        "estimated_minutes_watched": estimated_minutes_watched,
        "average_view_duration_seconds": _as_float(values.get("averageViewDuration")),
        "average_view_percentage": _as_float(values.get("averageViewPercentage")),
        "impressions": int(values.get("impressions")) if values.get("impressions") is not None else None,
        "click_through_rate": _as_float(values.get("impressionClickThroughRate")),
        "watch_time_hours": watch_time_hours,
        "subscribers_gained": int(values.get("subscribersGained")) if values.get("subscribersGained") is not None else None,
        "subscribers_lost": int(values.get("subscribersLost")) if values.get("subscribersLost") is not None else None,
        "likes": int(values.get("likes")) if values.get("likes") is not None else None,
        "comments": int(values.get("comments")) if values.get("comments") is not None else None,
        "shares": int(values.get("shares")) if values.get("shares") is not None else None,
    }


def fetch_recent_video_analytics(
    *,
    video_ids: list[str],
    channel_cfg=None,
    lookback_days: int = 14,
) -> list[dict]:
    end_date = datetime.now(timezone.utc).date().isoformat()
    start_date = (datetime.now(timezone.utc) - timedelta(days=max(1, lookback_days))).date().isoformat()
    reports: list[dict] = []
    for video_id in video_ids:
        try:
            reports.append(
                fetch_video_analytics(
                    video_id=video_id,
                    channel_cfg=channel_cfg,
                    start_date=start_date,
                    end_date=end_date,
                )
            )
        except Exception:
            continue
    return reports
