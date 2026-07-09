"""Analytics collector core (mock-first, pipeline-agnostic).

This module normalizes YouTube Analytics payloads into evaluator-compatible rows
without mutating pipeline/runtime state.
"""

from __future__ import annotations

from typing import Any

from .youtube_analytics import fetch_video_analytics


class CollectorError(RuntimeError):
    pass


class CollectorAPIError(CollectorError):
    pass


class CollectorValidationError(CollectorError):
    pass


_REQUIRED_EVALUATOR_FIELDS = (
    "experiment_id",
    "variant_id",
    "impressions",
    "clicks",
    "ctr",
    "watch_time_hours",
    "average_view_duration_seconds",
)


def _require_text(field_name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CollectorValidationError(f"missing_required_field:{field_name}")
    return value.strip()


def _as_non_negative_int(field_name: str, value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise CollectorValidationError(f"invalid_metric:{field_name}")
    try:
        num = int(value)
    except Exception as exc:
        raise CollectorValidationError(f"invalid_metric:{field_name}") from exc
    if num < 0:
        raise CollectorValidationError(f"invalid_metric:{field_name}")
    return num


def _as_non_negative_float(field_name: str, value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise CollectorValidationError(f"invalid_metric:{field_name}")
    try:
        num = float(value)
    except Exception as exc:
        raise CollectorValidationError(f"invalid_metric:{field_name}") from exc
    if num < 0:
        raise CollectorValidationError(f"invalid_metric:{field_name}")
    return num


def _normalize_ctr(value: Any) -> float | None:
    ctr = _as_non_negative_float("ctr", value)
    if ctr is None:
        return None
    if ctr <= 1.0:
        return ctr
    if ctr <= 100.0:
        return ctr / 100.0
    raise CollectorValidationError("invalid_metric:ctr")


def normalize_analytics_report(
    *,
    experiment_id: str,
    variant_id: str,
    report: dict[str, Any],
) -> dict[str, Any]:
    """Normalize one analytics report into evaluator-compatible shape."""
    exp = _require_text("experiment_id", experiment_id)
    var = _require_text("variant_id", variant_id)

    impressions = _as_non_negative_int("impressions", report.get("impressions"))
    ctr = _normalize_ctr(report.get("click_through_rate"))
    watch_time_hours = _as_non_negative_float("watch_time_hours", report.get("watch_time_hours"))
    avg_view_duration = _as_non_negative_float(
        "average_view_duration_seconds",
        report.get("average_view_duration_seconds"),
    )

    clicks: int | None
    if impressions is None or ctr is None:
        clicks = None
    else:
        clicks = int(round(impressions * ctr))

    return {
        "experiment_id": exp,
        "variant_id": var,
        "impressions": impressions,
        "clicks": clicks,
        "ctr": ctr,
        "watch_time_hours": watch_time_hours,
        "average_view_duration_seconds": avg_view_duration,
        "source": "youtube_analytics",
        "video_id": str(report.get("video_id") or "").strip() or None,
        "start_date": str(report.get("start_date") or "").strip() or None,
        "end_date": str(report.get("end_date") or "").strip() or None,
    }


def collect_analytics_rows(
    *,
    experiment_id: str,
    variant_by_video_id: dict[str, str],
    video_ids: list[str],
    channel_cfg=None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch and normalize analytics rows for evaluator input pipeline."""
    _require_text("experiment_id", experiment_id)
    if not isinstance(video_ids, list) or not video_ids:
        raise CollectorValidationError("empty_video_ids")

    rows: list[dict[str, Any]] = []
    for raw_video_id in video_ids:
        video_id = _require_text("video_id", raw_video_id)
        variant_id = _require_text("variant_id", variant_by_video_id.get(video_id))
        try:
            report = fetch_video_analytics(
                video_id=video_id,
                channel_cfg=channel_cfg,
                start_date=start_date,
                end_date=end_date,
            )
        except Exception as exc:
            raise CollectorAPIError(f"analytics_fetch_failed:{video_id}") from exc

        if not isinstance(report, dict):
            raise CollectorValidationError("invalid_report_shape")

        row = normalize_analytics_report(
            experiment_id=experiment_id,
            variant_id=variant_id,
            report=report,
        )
        rows.append(row)

    return rows


def build_evaluator_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only rows that are complete for evaluator ingestion."""
    if not isinstance(rows, list):
        raise CollectorValidationError("invalid_rows")

    result: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise CollectorValidationError("invalid_row")
        if any(row.get(field) is None for field in _REQUIRED_EVALUATOR_FIELDS):
            continue
        result.append(
            {
                "experiment_id": _require_text("experiment_id", row.get("experiment_id")),
                "variant_id": _require_text("variant_id", row.get("variant_id")),
                "impressions": _as_non_negative_int("impressions", row.get("impressions")),
                "clicks": _as_non_negative_int("clicks", row.get("clicks")),
                "ctr": _normalize_ctr(row.get("ctr")),
                "watch_time_hours": _as_non_negative_float("watch_time_hours", row.get("watch_time_hours")),
                "average_view_duration_seconds": _as_non_negative_float(
                    "average_view_duration_seconds",
                    row.get("average_view_duration_seconds"),
                ),
            }
        )

    return result
