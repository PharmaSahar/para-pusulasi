from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any

from .evidence_reference import validate_evidence_reference_row


LEARNING_RECORD_SCHEMA_VERSION = "v1"


class LearningEventType(str, Enum):
    INITIAL_OBSERVATION = "initial_observation"
    METRIC_UPDATE = "metric_update"
    CORRECTION = "correction"
    MATURITY_TRANSITION = "maturity_transition"
    ARCHIVAL = "archival"
    SUPERSESSION = "supersession"


class LearningMaturityState(str, Enum):
    UNKNOWN = "unknown"
    IMMATURE = "immature"
    PARTIALLY_OBSERVED = "partially_observed"
    MATURE = "mature"
    ARCHIVED = "archived"
    SUPERSEDED = "superseded"


class ObservationWindowType(str, Enum):
    LIFETIME = "lifetime"
    ROLLING_24H = "rolling_24h"
    ROLLING_7D = "rolling_7d"
    CUSTOM = "custom"


_MATURITY_TRANSITIONS: dict[str, set[str]] = {
    LearningMaturityState.UNKNOWN.value: {
        LearningMaturityState.IMMATURE.value,
        LearningMaturityState.PARTIALLY_OBSERVED.value,
    },
    LearningMaturityState.IMMATURE.value: {
        LearningMaturityState.PARTIALLY_OBSERVED.value,
        LearningMaturityState.ARCHIVED.value,
    },
    LearningMaturityState.PARTIALLY_OBSERVED.value: {
        LearningMaturityState.MATURE.value,
        LearningMaturityState.ARCHIVED.value,
        LearningMaturityState.SUPERSEDED.value,
    },
    LearningMaturityState.MATURE.value: {
        LearningMaturityState.ARCHIVED.value,
        LearningMaturityState.SUPERSEDED.value,
    },
    LearningMaturityState.SUPERSEDED.value: {
        LearningMaturityState.ARCHIVED.value,
    },
    LearningMaturityState.ARCHIVED.value: set(),
}

_FORBIDDEN_FIELDS = {
    "confidence",
    "probability",
    "prediction_certainty",
    "rpm",
    "revenue",
    "revenue_currency",
    "estimated_revenue",
    "predicted_ctr",
    "predicted_retention",
    "recommendation_score",
}


@dataclass(frozen=True, slots=True)
class OutcomeAttributionExtensionPoint:
    status: str = "not_implemented"
    attribution_event_ref: dict[str, Any] | None = None
    attribution_notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": _safe_text(self.status) or "not_implemented",
            "attribution_event_ref": dict(self.attribution_event_ref or {}) or None,
            "attribution_notes": _safe_text(self.attribution_notes) or None,
        }


@dataclass(frozen=True, slots=True)
class LearningRecord:
    schema_version: str
    learning_record_id: str
    learning_event_id: str
    event_type: str
    decision_id: str
    correlation_id: str
    channel_id: str
    content_id: str
    content_type: str
    window_type: str
    window_start: str
    window_end: str
    measurement_timestamp: str
    decision_record_ref: dict[str, Any] | None = None
    analytics_evidence_refs: tuple[dict[str, Any], ...] = ()
    cqga_evidence_refs: tuple[dict[str, Any], ...] = ()
    runtime_evidence_refs: tuple[dict[str, Any], ...] = ()
    experiment_evidence_refs: tuple[dict[str, Any], ...] = ()
    topic: str | None = None
    publish_slot: str | None = None
    impressions: int | None = None
    views: int | None = None
    ctr_ratio: float | None = None
    watch_time_hours: float | None = None
    average_view_duration_seconds: float | None = None
    average_percentage_viewed_ratio: float | None = None
    subscribers_gained: int | None = None
    likes: int | None = None
    comments: int | None = None
    maturity_state: str = LearningMaturityState.UNKNOWN.value
    metric_completeness: float | None = None
    evidence_completeness: float | None = None
    sample_sufficiency: float | None = None
    provisional_status: bool = True
    unknown_reasons: tuple[str, ...] = ()
    record_hash: str = ""
    previous_record_hash: str | None = None
    created_at: str = ""
    created_by: str = ""
    source_module: str = ""
    source_version: str = ""
    advisory_only: bool = True
    pipeline_output_changed: bool = False
    attribution_extension: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        validate_learning_record_row(asdict(self))

    def to_dict(self) -> dict[str, Any]:
        return validate_learning_record_row(asdict(self))


def _defaults() -> dict[str, Any]:
    return {
        "schema_version": LEARNING_RECORD_SCHEMA_VERSION,
        "learning_record_id": "",
        "learning_event_id": "",
        "event_type": LearningEventType.INITIAL_OBSERVATION.value,
        "decision_id": "",
        "correlation_id": "",
        "channel_id": "",
        "content_id": "",
        "content_type": "",
        "window_type": ObservationWindowType.LIFETIME.value,
        "window_start": "",
        "window_end": "",
        "measurement_timestamp": "",
        "decision_record_ref": None,
        "analytics_evidence_refs": [],
        "cqga_evidence_refs": [],
        "runtime_evidence_refs": [],
        "experiment_evidence_refs": [],
        "topic": None,
        "publish_slot": None,
        "impressions": None,
        "views": None,
        "ctr_ratio": None,
        "watch_time_hours": None,
        "average_view_duration_seconds": None,
        "average_percentage_viewed_ratio": None,
        "subscribers_gained": None,
        "likes": None,
        "comments": None,
        "maturity_state": LearningMaturityState.UNKNOWN.value,
        "metric_completeness": None,
        "evidence_completeness": None,
        "sample_sufficiency": None,
        "provisional_status": True,
        "unknown_reasons": [],
        "record_hash": "",
        "previous_record_hash": None,
        "created_at": "",
        "created_by": "",
        "source_module": "",
        "source_version": "",
        "advisory_only": True,
        "pipeline_output_changed": False,
        "attribution_extension": OutcomeAttributionExtensionPoint().to_dict(),
    }


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _parse_iso(name: str, value: Any) -> str:
    text = _safe_text(value)
    if not text:
        raise ValueError(f"missing_field:{name}")
    datetime.fromisoformat(text.replace("Z", "+00:00"))
    return text


def _normalize_int(name: str, value: Any, *, allow_none: bool = True) -> int | None:
    if value is None and allow_none:
        return None
    try:
        num = int(value)
    except Exception as exc:
        raise ValueError(f"invalid_field:{name}") from exc
    if num < 0:
        raise ValueError(f"invalid_field:{name}")
    return num


def _normalize_ratio(name: str, value: Any) -> float | None:
    if value is None:
        return None
    try:
        num = float(value)
    except Exception as exc:
        raise ValueError(f"invalid_field:{name}") from exc
    if not 0.0 <= num <= 1.0:
        raise ValueError(f"invalid_field:{name}_range")
    return num


def _normalize_non_negative_float(name: str, value: Any) -> float | None:
    if value is None:
        return None
    try:
        num = float(value)
    except Exception as exc:
        raise ValueError(f"invalid_field:{name}") from exc
    if num < 0.0:
        raise ValueError(f"invalid_field:{name}")
    return num


def _normalize_bool(name: str, value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = _safe_text(value).lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid_field:{name}")


def _normalize_ref(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("invalid_field:evidence_reference")
    return validate_evidence_reference_row(dict(value))


def _normalize_ref_list(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ValueError("invalid_field:evidence_reference_list")
    out: list[dict[str, Any]] = []
    for item in value:
        normalized = _normalize_ref(item)
        if normalized is not None:
            out.append(normalized)
    return out


def _sha(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def compute_learning_record_id(record: dict[str, Any]) -> str:
    seed = "|".join(
        [
            _safe_text(record.get("decision_id")),
            _safe_text(record.get("correlation_id")),
            _safe_text(record.get("channel_id")),
            _safe_text(record.get("content_id")),
            _safe_text(record.get("content_type")),
        ]
    )
    return "lrn_" + _sha(seed)[:24]


def compute_record_hash(record: dict[str, Any]) -> str:
    payload = dict(record)
    payload.pop("record_hash", None)
    payload.pop("learning_event_id", None)
    payload.pop("created_at", None)
    return "lrh_" + _sha(_stable_json(payload))[:24]


def compute_learning_event_id(record: dict[str, Any]) -> str:
    seed = "|".join(
        [
            _safe_text(record.get("learning_record_id")),
            _safe_text(record.get("event_type")),
            _safe_text(record.get("maturity_state")),
            _safe_text(record.get("record_hash")),
        ]
    )
    return "lre_" + _sha(seed)[:24]


def validate_maturity_transition(previous_state: str, next_state: str) -> bool:
    prev = _safe_text(previous_state)
    nxt = _safe_text(next_state)
    if prev not in _MATURITY_TRANSITIONS:
        return False
    return nxt in _MATURITY_TRANSITIONS.get(prev, set())


def canonicalize_learning_record_row(row: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ValueError("invalid_payload")

    forbidden = [key for key in _FORBIDDEN_FIELDS if key in row]
    if forbidden:
        raise ValueError(f"forbidden_field:{forbidden[0]}")

    normalized = _defaults()
    normalized.update(dict(row))

    if _safe_text(normalized.get("schema_version")) != LEARNING_RECORD_SCHEMA_VERSION:
        raise ValueError("invalid_field:schema_version")

    for key in [
        "decision_id",
        "correlation_id",
        "channel_id",
        "content_id",
        "content_type",
        "window_start",
        "window_end",
        "measurement_timestamp",
        "created_by",
        "source_module",
        "source_version",
    ]:
        normalized[key] = _safe_text(normalized.get(key))
        if not normalized[key]:
            raise ValueError(f"missing_field:{key}")

    normalized["created_at"] = _parse_iso("created_at", normalized.get("created_at"))
    normalized["measurement_timestamp"] = _parse_iso("measurement_timestamp", normalized.get("measurement_timestamp"))
    normalized["window_start"] = _parse_iso("window_start", normalized.get("window_start"))
    normalized["window_end"] = _parse_iso("window_end", normalized.get("window_end"))

    try:
        ObservationWindowType(_safe_text(normalized.get("window_type")))
    except Exception as exc:
        raise ValueError("invalid_field:window_type") from exc

    try:
        LearningEventType(_safe_text(normalized.get("event_type")))
    except Exception as exc:
        raise ValueError("invalid_field:event_type") from exc

    try:
        LearningMaturityState(_safe_text(normalized.get("maturity_state")))
    except Exception as exc:
        raise ValueError("invalid_field:maturity_state") from exc

    normalized["learning_record_id"] = _safe_text(normalized.get("learning_record_id")) or compute_learning_record_id(normalized)

    normalized["decision_record_ref"] = _normalize_ref(normalized.get("decision_record_ref"))
    normalized["analytics_evidence_refs"] = _normalize_ref_list(normalized.get("analytics_evidence_refs"))
    normalized["cqga_evidence_refs"] = _normalize_ref_list(normalized.get("cqga_evidence_refs"))
    normalized["runtime_evidence_refs"] = _normalize_ref_list(normalized.get("runtime_evidence_refs"))
    normalized["experiment_evidence_refs"] = _normalize_ref_list(normalized.get("experiment_evidence_refs"))

    normalized["topic"] = _safe_text(normalized.get("topic")) or None
    normalized["publish_slot"] = _safe_text(normalized.get("publish_slot")) or None

    normalized["impressions"] = _normalize_int("impressions", normalized.get("impressions"))
    normalized["views"] = _normalize_int("views", normalized.get("views"))
    normalized["ctr_ratio"] = _normalize_ratio("ctr_ratio", normalized.get("ctr_ratio"))
    normalized["watch_time_hours"] = _normalize_non_negative_float("watch_time_hours", normalized.get("watch_time_hours"))
    normalized["average_view_duration_seconds"] = _normalize_non_negative_float(
        "average_view_duration_seconds", normalized.get("average_view_duration_seconds")
    )
    normalized["average_percentage_viewed_ratio"] = _normalize_ratio(
        "average_percentage_viewed_ratio", normalized.get("average_percentage_viewed_ratio")
    )
    normalized["subscribers_gained"] = _normalize_int("subscribers_gained", normalized.get("subscribers_gained"))
    normalized["likes"] = _normalize_int("likes", normalized.get("likes"))
    normalized["comments"] = _normalize_int("comments", normalized.get("comments"))

    normalized["metric_completeness"] = _normalize_ratio("metric_completeness", normalized.get("metric_completeness"))
    normalized["evidence_completeness"] = _normalize_ratio("evidence_completeness", normalized.get("evidence_completeness"))
    normalized["sample_sufficiency"] = _normalize_ratio("sample_sufficiency", normalized.get("sample_sufficiency"))
    normalized["provisional_status"] = _normalize_bool("provisional_status", normalized.get("provisional_status"))
    unknown_reasons = normalized.get("unknown_reasons") or []
    if not isinstance(unknown_reasons, (list, tuple)):
        raise ValueError("invalid_field:unknown_reasons")
    normalized["unknown_reasons"] = [_safe_text(item) for item in unknown_reasons if _safe_text(item)]

    normalized["advisory_only"] = _normalize_bool("advisory_only", normalized.get("advisory_only"))
    normalized["pipeline_output_changed"] = _normalize_bool("pipeline_output_changed", normalized.get("pipeline_output_changed"))
    if not normalized["advisory_only"]:
        raise ValueError("invalid_field:advisory_only")
    if normalized["pipeline_output_changed"]:
        raise ValueError("invalid_field:pipeline_output_changed")

    attribution = normalized.get("attribution_extension")
    if attribution is None:
        attribution = OutcomeAttributionExtensionPoint().to_dict()
    if not isinstance(attribution, dict):
        raise ValueError("invalid_field:attribution_extension")
    normalized["attribution_extension"] = {
        "status": _safe_text(attribution.get("status")) or "not_implemented",
        "attribution_event_ref": dict(attribution.get("attribution_event_ref") or {}) or None,
        "attribution_notes": _safe_text(attribution.get("attribution_notes")) or None,
    }

    normalized["previous_record_hash"] = _safe_text(normalized.get("previous_record_hash")) or None
    normalized["record_hash"] = compute_record_hash(normalized)
    normalized["learning_event_id"] = compute_learning_event_id(normalized)

    return normalized


def validate_learning_record_row(row: dict[str, Any]) -> dict[str, Any]:
    return canonicalize_learning_record_row(row)


def build_learning_record(
    payload: dict[str, Any],
    *,
    created_by: str,
    source_module: str,
    source_version: str,
    created_at: str | None = None,
    previous_record_hash: str | None = None,
    event_type: str | LearningEventType | None = None,
    maturity_state: str | LearningMaturityState | None = None,
) -> dict[str, Any]:
    base = _defaults()
    base.update(dict(payload or {}))
    if event_type is not None:
        base["event_type"] = event_type.value if isinstance(event_type, LearningEventType) else str(event_type)
    if maturity_state is not None:
        base["maturity_state"] = maturity_state.value if isinstance(maturity_state, LearningMaturityState) else str(maturity_state)

    base["created_by"] = _safe_text(created_by)
    base["source_module"] = _safe_text(source_module)
    base["source_version"] = _safe_text(source_version)
    base["created_at"] = _safe_text(created_at) or datetime.now(timezone.utc).isoformat()
    base["previous_record_hash"] = _safe_text(previous_record_hash) or _safe_text(base.get("previous_record_hash")) or None

    return canonicalize_learning_record_row(base)
