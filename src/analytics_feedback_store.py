"""Slice 3 Phase 1 append-only analytics feedback storage.

This layer stores normalized analytics snapshots without integrating any API.
It is intentionally independent from YouTube client code.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


ANALYTICS_FEEDBACK_SCHEMA_VERSION = "v1"
DEFAULT_FEEDBACK_PATH = Path("logs/analytics_feedback.jsonl")


class AnalyticsFeedbackValidationError(ValueError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_text(field_name: str, value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise AnalyticsFeedbackValidationError(f"missing_field:{field_name}")
    return text


def _as_non_negative_float(field_name: str, value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise AnalyticsFeedbackValidationError(f"invalid_metric:{field_name}")
    try:
        num = float(value)
    except Exception as exc:
        raise AnalyticsFeedbackValidationError(f"invalid_metric:{field_name}") from exc
    if num < 0:
        raise AnalyticsFeedbackValidationError(f"invalid_metric:{field_name}")
    return num


def _as_non_negative_int(field_name: str, value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise AnalyticsFeedbackValidationError(f"invalid_metric:{field_name}")
    try:
        num = int(value)
    except Exception as exc:
        raise AnalyticsFeedbackValidationError(f"invalid_metric:{field_name}") from exc
    if num < 0:
        raise AnalyticsFeedbackValidationError(f"invalid_metric:{field_name}")
    return num


def _parse_iso(field_name: str, value: Any) -> str:
    text = _require_text(field_name, value)
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception as exc:
        raise AnalyticsFeedbackValidationError(f"invalid_datetime:{field_name}") from exc
    return text


@dataclass(frozen=True)
class AnalyticsFeedbackRecord:
    schema_version: str
    channel_id: str
    video_id: str
    upload_timestamp: str
    title: str
    thumbnail_hash: str
    topic: str
    script_hash: str
    shorts_hash: str
    impressions: int | None = None
    ctr: float | None = None
    average_view_duration: float | None = None
    average_percentage_viewed: float | None = None
    audience_retention: dict[str, Any] = field(default_factory=dict)
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    subscribers_gained: int | None = None
    traffic_sources: dict[str, float] = field(default_factory=dict)
    suggested_video_traffic: float | None = None
    browse_traffic: float | None = None
    search_traffic: float | None = None
    end_screen_ctr: float | None = None
    card_ctr: float | None = None
    playlist_additions: int | None = None
    recorded_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_feedback_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise AnalyticsFeedbackValidationError("invalid_payload")

    out: dict[str, Any] = {}
    out["schema_version"] = _require_text("schema_version", payload.get("schema_version"))
    out["channel_id"] = _require_text("channel_id", payload.get("channel_id"))
    out["video_id"] = _require_text("video_id", payload.get("video_id"))
    out["upload_timestamp"] = _parse_iso("upload_timestamp", payload.get("upload_timestamp"))
    out["title"] = _require_text("title", payload.get("title"))
    out["thumbnail_hash"] = _require_text("thumbnail_hash", payload.get("thumbnail_hash"))
    out["topic"] = _require_text("topic", payload.get("topic"))
    out["script_hash"] = _require_text("script_hash", payload.get("script_hash"))
    out["shorts_hash"] = _require_text("shorts_hash", payload.get("shorts_hash"))

    out["impressions"] = _as_non_negative_int("impressions", payload.get("impressions"))
    out["ctr"] = _as_non_negative_float("ctr", payload.get("ctr"))
    if out["ctr"] is not None and out["ctr"] > 1.0:
        raise AnalyticsFeedbackValidationError("invalid_metric:ctr")
    out["average_view_duration"] = _as_non_negative_float("average_view_duration", payload.get("average_view_duration"))
    out["average_percentage_viewed"] = _as_non_negative_float("average_percentage_viewed", payload.get("average_percentage_viewed"))
    if out["average_percentage_viewed"] is not None and out["average_percentage_viewed"] > 1.0:
        raise AnalyticsFeedbackValidationError("invalid_metric:average_percentage_viewed")

    retention = payload.get("audience_retention")
    out["audience_retention"] = retention if isinstance(retention, dict) else {}

    out["likes"] = _as_non_negative_int("likes", payload.get("likes"))
    out["comments"] = _as_non_negative_int("comments", payload.get("comments"))
    out["shares"] = _as_non_negative_int("shares", payload.get("shares"))
    out["subscribers_gained"] = _as_non_negative_int("subscribers_gained", payload.get("subscribers_gained"))

    traffic = payload.get("traffic_sources")
    if traffic is None:
        out["traffic_sources"] = {}
    elif not isinstance(traffic, dict):
        raise AnalyticsFeedbackValidationError("invalid_metric:traffic_sources")
    else:
        normalized_traffic = {}
        for key, value in traffic.items():
            normalized_traffic[str(key)] = _as_non_negative_float(f"traffic_sources.{key}", value) or 0.0
        out["traffic_sources"] = normalized_traffic

    out["suggested_video_traffic"] = _as_non_negative_float("suggested_video_traffic", payload.get("suggested_video_traffic"))
    out["browse_traffic"] = _as_non_negative_float("browse_traffic", payload.get("browse_traffic"))
    out["search_traffic"] = _as_non_negative_float("search_traffic", payload.get("search_traffic"))
    out["end_screen_ctr"] = _as_non_negative_float("end_screen_ctr", payload.get("end_screen_ctr"))
    out["card_ctr"] = _as_non_negative_float("card_ctr", payload.get("card_ctr"))
    if out["end_screen_ctr"] is not None and out["end_screen_ctr"] > 1.0:
        raise AnalyticsFeedbackValidationError("invalid_metric:end_screen_ctr")
    if out["card_ctr"] is not None and out["card_ctr"] > 1.0:
        raise AnalyticsFeedbackValidationError("invalid_metric:card_ctr")

    out["playlist_additions"] = _as_non_negative_int("playlist_additions", payload.get("playlist_additions"))
    out["recorded_at"] = _parse_iso("recorded_at", payload.get("recorded_at") or _now_iso())
    return out


def make_feedback_record(**kwargs: Any) -> AnalyticsFeedbackRecord:
    payload = {
        "schema_version": kwargs.get("schema_version", ANALYTICS_FEEDBACK_SCHEMA_VERSION),
        **kwargs,
    }
    normalized = validate_feedback_payload(payload)
    return AnalyticsFeedbackRecord(**normalized)


def append_feedback_record(record: AnalyticsFeedbackRecord, *, output_path: Path | str = DEFAULT_FEEDBACK_PATH) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")


def load_feedback_records(*, input_path: Path | str = DEFAULT_FEEDBACK_PATH) -> list[AnalyticsFeedbackRecord]:
    path = Path(input_path)
    if not path.exists():
        return []

    records: list[AnalyticsFeedbackRecord] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        payload = json.loads(line)
        normalized = validate_feedback_payload(payload)
        records.append(AnalyticsFeedbackRecord(**normalized))
    return records
