"""Helpers for passive render duration measurement."""

from __future__ import annotations

from datetime import datetime, timezone


RENDER_METRICS_VERSION = "v1"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coerce_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    normalized = str(value).strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    return datetime.fromisoformat(normalized)


def _safe_non_negative_duration_seconds(started_at: datetime, finished_at: datetime) -> float:
    delta = (finished_at - started_at).total_seconds()
    return max(0.0, round(delta, 3))


def build_render_metrics(
    *,
    render_started_at: str | datetime,
    render_finished_at: str | datetime,
    render_status: str = "completed",
    output_resolution: str | None = None,
    output_fps: int | float | None = None,
) -> dict:
    started_dt = _coerce_datetime(render_started_at)
    finished_dt = _coerce_datetime(render_finished_at)

    metrics = {
        "render_metrics_version": RENDER_METRICS_VERSION,
        "render_started_at": started_dt.isoformat(),
        "render_finished_at": finished_dt.isoformat(),
        "render_duration_seconds": _safe_non_negative_duration_seconds(started_dt, finished_dt),
        "render_status": str(render_status or "completed"),
    }
    if output_resolution:
        metrics["output_resolution"] = str(output_resolution)
    if output_fps is not None:
        metrics["output_fps"] = output_fps
    return metrics