"""Canonical runtime analytics shadow ingestion.

This module adds a shadow-only runtime path that:
1) Collects read-only YouTube Analytics metrics for one runtime video.
2) Builds and validates canonical analytics records.
3) Appends records to canonical storage with idempotent duplicate prevention.

The path is explicitly fail-open and does not alter legacy runtime outputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
from typing import Any

from googleapiclient.errors import HttpError

from .studio_analytics_learning_bridge import (
    CANONICAL_ANALYTICS_PATH,
    CANONICAL_METRICS_VERSION,
    CanonicalAnalyticsRecord,
    ContentType,
    MetricState,
    append_canonical_record_row,
    build_canonical_record_id,
    load_canonical_records,
    validate_canonical_record,
)
from .youtube_analytics_smoke import (
    _build_service,
    _credentials_scope_ok,
    _load_credentials_read_only,
    _redact_error,
    _resolve_channel_context,
    _resolve_gate_enabled,
    _validate_date_window,
)


RUNTIME_COLLECTOR_SOURCE = "RuntimeShadowCollector"
RUNTIME_SHADOW_FLAG = "CANONICAL_RUNTIME_ANALYTICS_SHADOW_ENABLED"
RUNTIME_SHADOW_PATH_ENV = "CANONICAL_RUNTIME_ANALYTICS_PATH"
RUNTIME_SHADOW_LOOKBACK_DAYS_ENV = "CANONICAL_RUNTIME_ANALYTICS_LOOKBACK_DAYS"
RUNTIME_UPLOAD_REGISTRY_PATH_ENV = "UPLOAD_REGISTRY_PATH"

# Keep runtime collector metrics limited to combinations proven compatible
# for the video-filtered query path.
RUNTIME_COLLECTOR_ALLOWED_METRICS = (
    "views",
    "estimatedMinutesWatched",
    "averageViewDuration",
    "averageViewPercentage",
    "subscribersGained",
    "subscribersLost",
)


@dataclass(frozen=True)
class RuntimeCollectorResult:
    ok: bool
    result_state: str
    error_class: str | None
    redacted_error: str | None
    payload: dict[str, Any]


def _is_enabled(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _sha(text: str) -> str:
    import hashlib

    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def _parse_iso_date(value: str) -> date:
    text = str(value or "").strip()
    if not text:
        raise ValueError("invalid_date:empty")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text).date()


def _resolve_upload_registry_path() -> Path | None:
    explicit = str(os.getenv(RUNTIME_UPLOAD_REGISTRY_PATH_ENV, "")).strip()
    candidates = [
        explicit,
        "output/runtime/state/production_upload_registry.json",
        "state/production_upload_registry.json",
        "/opt/parapusulasi-current/output/runtime/state/production_upload_registry.json",
    ]
    for raw in candidates:
        text = str(raw or "").strip()
        if not text:
            continue
        path = Path(text)
        if path.exists():
            return path
    return None


def _resolve_earliest_valid_date(*, channel_id: str, video_id: str) -> str | None:
    path = _resolve_upload_registry_path()
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

    entries = data.get("entries") if isinstance(data, dict) else {}
    if not isinstance(entries, dict):
        return None

    candidates: list[date] = []
    for payload in entries.values():
        if not isinstance(payload, dict):
            continue
        if _safe_text(payload.get("channel")) != _safe_text(channel_id):
            continue
        if _safe_text(payload.get("video_id")) != _safe_text(video_id):
            continue

        for key in ("published_at", "publish_at", "registered_at"):
            raw = _safe_text(payload.get(key))
            if not raw:
                continue
            try:
                candidates.append(_parse_iso_date(raw))
            except Exception:
                continue

    if not candidates:
        return None
    return min(candidates).isoformat()


def _resolve_effective_window(
    *,
    now_date: date,
    requested_days: int,
    earliest_valid_date: str | None,
) -> tuple[str, str, int]:
    clamped_days = max(1, min(7, int(requested_days)))
    floor_start = now_date - timedelta(days=clamped_days - 1)

    if _safe_text(earliest_valid_date):
        try:
            earliest = _parse_iso_date(_safe_text(earliest_valid_date))
        except Exception:
            earliest = floor_start
    else:
        earliest = floor_start

    if earliest > now_date:
        earliest = now_date

    start = max(floor_start, earliest)
    end = now_date
    day_count = (end - start).days + 1
    return start.isoformat(), end.isoformat(), day_count


def _is_invalid_metric_combination_error(exc: Exception) -> bool:
    text = str(exc or "")
    if isinstance(exc, HttpError):
        content = getattr(exc, "content", b"")
        if isinstance(content, bytes):
            text = f"{text} {content.decode('utf-8', errors='ignore')}"
        else:
            text = f"{text} {content}"
    low = text.lower()
    return ("unknown identifier" in low and "metrics" in low) or "parameters.metrics" in low


def canonical_runtime_shadow_enabled() -> bool:
    return _is_enabled(os.getenv(RUNTIME_SHADOW_FLAG, "false"))


def _runtime_output_path() -> Path:
    raw = str(os.getenv(RUNTIME_SHADOW_PATH_ENV, str(CANONICAL_ANALYTICS_PATH))).strip()
    return Path(raw) if raw else Path(CANONICAL_ANALYTICS_PATH)


def _normalize_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _normalize_ratio(value: Any) -> float | None:
    num = _normalize_number(value)
    if num is None:
        return None
    if num <= 1.0:
        return num
    if num <= 100.0:
        return num / 100.0
    return None


def _metric_value(state: MetricState, value: Any, *, raw_name: str | None = None) -> dict[str, Any]:
    return {
        "state": state.value,
        "value": value,
        "raw_name": _safe_text(raw_name) or None,
    }


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _extract_metric_payload(*, row: dict[str, Any], returned_columns: list[str]) -> dict[str, dict[str, Any]]:
    metrics: dict[str, dict[str, Any]] = {}

    raw_views = row.get("views")
    raw_impressions = row.get("impressions")
    raw_ctr = row.get("impressionClickThroughRate")
    raw_avg_view_duration = row.get("averageViewDuration")
    raw_avg_pct = row.get("averageViewPercentage")
    raw_est_minutes = row.get("estimatedMinutesWatched")
    raw_subs_gained = row.get("subscribersGained")
    raw_subs_lost = row.get("subscribersLost")

    metrics["views"] = _metric_value(
        MetricState.OBSERVED if _normalize_number(raw_views) is not None else MetricState.UNAVAILABLE,
        _normalize_number(raw_views),
        raw_name="views",
    )
    metrics["impressions"] = _metric_value(
        MetricState.OBSERVED if _normalize_number(raw_impressions) is not None else MetricState.UNAVAILABLE,
        _normalize_number(raw_impressions),
        raw_name="impressions",
    )
    metrics["impressions_ctr"] = _metric_value(
        MetricState.OBSERVED if _normalize_ratio(raw_ctr) is not None else MetricState.UNAVAILABLE,
        _normalize_ratio(raw_ctr),
        raw_name="impressionClickThroughRate",
    )
    metrics["average_view_duration"] = _metric_value(
        MetricState.OBSERVED if _normalize_number(raw_avg_view_duration) is not None else MetricState.UNAVAILABLE,
        _normalize_number(raw_avg_view_duration),
        raw_name="averageViewDuration",
    )
    metrics["average_percentage_viewed"] = _metric_value(
        MetricState.OBSERVED if _normalize_ratio(raw_avg_pct) is not None else MetricState.UNAVAILABLE,
        _normalize_ratio(raw_avg_pct),
        raw_name="averageViewPercentage",
    )

    watch_time_hours = None
    minutes = _normalize_number(raw_est_minutes)
    if minutes is not None:
        watch_time_hours = minutes / 60.0
    metrics["watch_time"] = _metric_value(
        MetricState.OBSERVED if watch_time_hours is not None else MetricState.UNAVAILABLE,
        watch_time_hours,
        raw_name="estimatedMinutesWatched",
    )

    metrics["subscribers_gained"] = _metric_value(
        MetricState.OBSERVED if _normalize_number(raw_subs_gained) is not None else MetricState.UNAVAILABLE,
        _normalize_number(raw_subs_gained),
        raw_name="subscribersGained",
    )
    metrics["subscribers_lost"] = _metric_value(
        MetricState.OBSERVED if _normalize_number(raw_subs_lost) is not None else MetricState.UNAVAILABLE,
        _normalize_number(raw_subs_lost),
        raw_name="subscribersLost",
    )

    # Explicitly preserve collector contract evidence.
    metrics["collector_returned_columns"] = _metric_value(
        MetricState.OBSERVED,
        sorted(set(str(col) for col in returned_columns)),
        raw_name="returned_columns",
    )
    return metrics


def collect_runtime_video_analytics(
    *,
    channel_id: str,
    video_id: str,
    start_date: str,
    end_date: str,
    timeout_seconds: int = 15,
    metrics: tuple[str, ...] | None = None,
) -> RuntimeCollectorResult:
    payload = {
        "channel_id": _safe_text(channel_id),
        "video_id": _safe_text(video_id),
        "start_date": None,
        "end_date": None,
        "day_count": 0,
        "requested_metrics": [],
        "returned_columns": [],
        "rows": [],
        "api_call_attempted": False,
        "api_call_succeeded": False,
        "selected_token_source": "NONE",
    }

    try:
        start_iso, end_iso = _validate_date_window(start_date, end_date)
        payload["start_date"] = start_iso
        payload["end_date"] = end_iso
        payload["day_count"] = (_parse_iso_date(end_iso) - _parse_iso_date(start_iso)).days + 1

        requested_metrics = tuple(metrics or RUNTIME_COLLECTOR_ALLOWED_METRICS)
        payload["requested_metrics"] = list(requested_metrics)

        if not _resolve_gate_enabled():
            return RuntimeCollectorResult(
                ok=False,
                result_state="API_NOT_ENABLED",
                error_class="API_NOT_ENABLED",
                redacted_error=None,
                payload=payload,
            )

        context = _resolve_channel_context(_safe_text(channel_id))
        payload["selected_token_source"] = context.selected_token_source

        credentials = _load_credentials_read_only(context.selected_token_path)
        if credentials is None:
            return RuntimeCollectorResult(
                ok=False,
                result_state="TOKEN_MISSING",
                error_class="TOKEN_MISSING",
                redacted_error=None,
                payload=payload,
            )
        if not _credentials_scope_ok(credentials):
            return RuntimeCollectorResult(
                ok=False,
                result_state="API_SCOPE_INSUFFICIENT",
                error_class="API_SCOPE_INSUFFICIENT",
                redacted_error=None,
                payload=payload,
            )
        if bool(getattr(credentials, "expired", False)):
            return RuntimeCollectorResult(
                ok=False,
                result_state="TOKEN_EXPIRED",
                error_class="TOKEN_EXPIRED",
                redacted_error=None,
                payload=payload,
            )
        if not bool(getattr(credentials, "valid", False)):
            return RuntimeCollectorResult(
                ok=False,
                result_state="AUTHENTICATION_BLOCKED",
                error_class="AUTHENTICATION_BLOCKED",
                redacted_error=None,
                payload=payload,
            )

        service = _build_service(credentials, timeout_seconds=timeout_seconds)
        payload["api_call_attempted"] = True
        response = service.reports().query(
            ids="channel==MINE",
            startDate=start_iso,
            endDate=end_iso,
            metrics=",".join(requested_metrics),
            dimensions="video",
            filters=f"video=={_safe_text(video_id)}",
            maxResults=1,
        ).execute(num_retries=0)
        payload["api_call_succeeded"] = True

        headers = response.get("columnHeaders") or []
        returned_columns = [str(h.get("name") or "").strip() for h in headers if str(h.get("name") or "").strip()]
        payload["returned_columns"] = returned_columns

        if returned_columns and returned_columns[0] != "video":
            return RuntimeCollectorResult(
                ok=False,
                result_state="UNSUPPORTED_DIMENSION",
                error_class="UNSUPPORTED_DIMENSION",
                redacted_error="unexpected_dimension",
                payload=payload,
            )
        for name in returned_columns[1:]:
            if name not in requested_metrics:
                return RuntimeCollectorResult(
                    ok=False,
                    result_state="UNSUPPORTED_METRIC",
                    error_class="UNSUPPORTED_METRIC",
                    redacted_error=name,
                    payload=payload,
                )

        rows = response.get("rows") or []
        normalized_rows: list[dict[str, Any]] = []
        for raw in rows:
            if not isinstance(raw, list):
                continue
            normalized = {}
            for idx, col in enumerate(returned_columns):
                normalized[col] = raw[idx] if idx < len(raw) else None
            normalized_rows.append(normalized)

        normalized_rows = sorted(normalized_rows, key=lambda item: _stable_json(item))
        payload["rows"] = normalized_rows
        if not normalized_rows:
            return RuntimeCollectorResult(
                ok=False,
                result_state="TRUE_EMPTY_RESPONSE",
                error_class="TRUE_EMPTY_RESPONSE",
                redacted_error=None,
                payload=payload,
            )

        if int(payload.get("day_count") or 0) < 7:
            return RuntimeCollectorResult(
                ok=True,
                result_state="VALID_PARTIAL_WINDOW",
                error_class=None,
                redacted_error=None,
                payload=payload,
            )

        return RuntimeCollectorResult(
            ok=True,
            result_state="SUCCESS",
            error_class=None,
            redacted_error=None,
            payload=payload,
        )
    except HttpError as exc:
        if _is_invalid_metric_combination_error(exc):
            return RuntimeCollectorResult(
                ok=False,
                result_state="INVALID_METRIC_COMBINATION",
                error_class=exc.__class__.__name__,
                redacted_error=_redact_error(exc),
                payload=payload,
            )
        return RuntimeCollectorResult(
            ok=False,
            result_state="API_REQUEST_FAILED",
            error_class=exc.__class__.__name__,
            redacted_error=_redact_error(exc),
            payload=payload,
        )
    except Exception as exc:
        return RuntimeCollectorResult(
            ok=False,
            result_state="API_REQUEST_FAILED",
            error_class=exc.__class__.__name__,
            redacted_error=_redact_error(exc),
            payload=payload,
        )


def build_runtime_canonical_record(
    *,
    collection: RuntimeCollectorResult,
    channel_id: str,
    content_id: str,
    run_id: str,
    video_id: str,
) -> dict[str, Any]:
    if not collection.ok:
        raise ValueError(f"collection_failed:{collection.result_state}")

    payload = dict(collection.payload or {})
    rows = list(payload.get("rows") or [])
    if not rows:
        raise ValueError("collection_failed:EMPTY_RESPONSE")
    row = dict(rows[0] or {})
    returned_columns = list(payload.get("returned_columns") or [])
    start_date = _safe_text(payload.get("start_date")) or None
    end_date = _safe_text(payload.get("end_date")) or None

    source_hash = _sha(
        "|".join(
            [
                RUNTIME_COLLECTOR_SOURCE,
                _safe_text(channel_id),
                _safe_text(video_id),
                _safe_text(start_date),
                _safe_text(end_date),
            ]
        )
    )
    record_id = build_canonical_record_id(
        provider="FutureOfficialYouTubeProvider",
        source_file_hash=source_hash,
        source_row_number=1,
        youtube_video_id=_safe_text(video_id) or None,
        snapshot_start=start_date,
        snapshot_end=end_date,
        metrics_version=CANONICAL_METRICS_VERSION,
    )

    metrics = _extract_metric_payload(row=row, returned_columns=returned_columns)
    candidate = CanonicalAnalyticsRecord(
        schema_version="v1",
        analytics_record_id=record_id,
        provider="FutureOfficialYouTubeProvider",
        source_file_hash=source_hash,
        source_row_number=1,
        canonical_channel_id=_safe_text(channel_id) or None,
        content_id=_safe_text(content_id) or None,
        youtube_video_id=_safe_text(video_id) or None,
        content_type=ContentType.UNKNOWN.value,
        snapshot_start=start_date,
        snapshot_end=end_date,
        imported_at=datetime.now(timezone.utc).isoformat(),
        metrics_version=CANONICAL_METRICS_VERSION,
        provenance={
            "source_type": "runtime_collector",
            "source": RUNTIME_COLLECTOR_SOURCE,
            "window_type": "daily" if start_date and end_date and start_date == end_date else "date_range",
            "join_outcome": "LINKED",
            "join_method": "BY_UPLOAD_RESULT_VIDEO_ID",
            "runtime_content_id": _safe_text(content_id) or None,
            "runtime_run_id": _safe_text(run_id) or None,
            "collector_result_state": collection.result_state,
            "returned_columns": sorted(set(str(x) for x in returned_columns)),
        },
        advisory_only=True,
        pipeline_output_changed=False,
        metrics=metrics,
    ).to_dict()
    return validate_canonical_record(candidate)


def append_runtime_canonical_records(
    *,
    rows: list[dict[str, Any]],
    output_path: Path | str | None = None,
) -> dict[str, Any]:
    path = Path(output_path) if output_path is not None else _runtime_output_path()
    existing, malformed_existing = load_canonical_records(path=path)
    known_ids = {
        _safe_text(item.get("analytics_record_id"))
        for item in existing
        if isinstance(item, dict) and _safe_text(item.get("analytics_record_id"))
    }

    appended = 0
    duplicates = 0
    invalid_rows = 0

    ordered = sorted(rows, key=lambda item: (_safe_text(item.get("analytics_record_id")), _stable_json(item)))
    for row in ordered:
        try:
            normalized = validate_canonical_record(dict(row or {}))
        except Exception:
            invalid_rows += 1
            continue

        rec_id = _safe_text(normalized.get("analytics_record_id"))
        if not rec_id:
            invalid_rows += 1
            continue
        if rec_id in known_ids:
            duplicates += 1
            continue

        append_canonical_record_row(output_path=path, row=normalized)
        known_ids.add(rec_id)
        appended += 1

    return {
        "output_path": str(path),
        "appended": appended,
        "duplicates": duplicates,
        "invalid_rows": invalid_rows,
        "existing_malformed": malformed_existing,
        "advisory_only": True,
        "pipeline_output_changed": False,
    }


def replay_runtime_canonical_rows(*, output_path: Path | str | None = None) -> dict[str, Any]:
    path = Path(output_path) if output_path is not None else _runtime_output_path()
    rows, malformed = load_canonical_records(path=path)
    ordered = sorted(
        rows,
        key=lambda item: (
            _safe_text(item.get("snapshot_start")),
            _safe_text(item.get("snapshot_end")),
            _safe_text(item.get("analytics_record_id")),
        ),
    )
    digest = _sha(_stable_json(ordered)) if ordered else None
    return {
        "output_path": str(path),
        "row_count": len(ordered),
        "malformed": malformed,
        "digest": digest,
        "deterministic_ordering": True,
    }


def run_pipeline_runtime_canonical_shadow(
    *,
    channel_id: str,
    content_id: str,
    run_id: str,
    video_id: str,
    now_utc: datetime | None = None,
    lookback_days: int | None = None,
    earliest_valid_date: str | None = None,
    output_path: Path | str | None = None,
) -> dict[str, Any]:
    if not canonical_runtime_shadow_enabled():
        return {
            "status": "shadow_disabled",
            "advisory_only": True,
            "pipeline_output_changed": False,
        }

    channel = _safe_text(channel_id)
    content = _safe_text(content_id)
    run = _safe_text(run_id)
    video = _safe_text(video_id)
    if not channel or not content or not run or not video:
        return {
            "status": "shadow_skipped_missing_identity",
            "advisory_only": True,
            "pipeline_output_changed": False,
        }

    now = now_utc or datetime.now(timezone.utc)
    requested_days = lookback_days
    if requested_days is None:
        try:
            requested_days = int(os.getenv(RUNTIME_SHADOW_LOOKBACK_DAYS_ENV, "7"))
        except ValueError:
            requested_days = 7

    resolved_earliest = _safe_text(earliest_valid_date) or _resolve_earliest_valid_date(
        channel_id=channel,
        video_id=video,
    )
    start_date, end_date, day_count = _resolve_effective_window(
        now_date=now.date(),
        requested_days=max(1, min(7, int(requested_days))),
        earliest_valid_date=resolved_earliest or None,
    )

    collection = collect_runtime_video_analytics(
        channel_id=channel,
        video_id=video,
        start_date=start_date,
        end_date=end_date,
    )
    if not collection.ok:
        return {
            "status": "shadow_collect_failed",
            "result_state": collection.result_state,
            "error_class": collection.error_class,
            "redacted_error": collection.redacted_error,
            "start_date": start_date,
            "end_date": end_date,
            "day_count": day_count,
            "api_row_count": len(list(collection.payload.get("rows") or [])),
            "advisory_only": True,
            "pipeline_output_changed": False,
        }

    record = build_runtime_canonical_record(
        collection=collection,
        channel_id=channel,
        content_id=content,
        run_id=run,
        video_id=video,
    )
    write_report = append_runtime_canonical_records(rows=[record], output_path=output_path)

    return {
        "status": "shadow_success",
        "collector": {
            "result_state": collection.result_state,
            "api_call_attempted": bool(collection.payload.get("api_call_attempted")),
            "api_call_succeeded": bool(collection.payload.get("api_call_succeeded")),
            "start_date": start_date,
            "end_date": end_date,
            "day_count": day_count,
            "api_row_count": len(list(collection.payload.get("rows") or [])),
        },
        "writer": write_report,
        "record_id": record.get("analytics_record_id"),
        "advisory_only": True,
        "pipeline_output_changed": False,
    }
