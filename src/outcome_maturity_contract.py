from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any

from .evidence_reference import validate_evidence_reference_row


OUTCOME_MATURITY_SCHEMA_VERSION = "v1"


class OutcomeEventType(str, Enum):
    INITIAL_OBSERVATION = "INITIAL_OBSERVATION"
    METRIC_UPDATE = "METRIC_UPDATE"
    CORRECTION = "CORRECTION"
    MATURITY_TRANSITION = "MATURITY_TRANSITION"
    ARCHIVAL = "ARCHIVAL"
    SUPERSESSION = "SUPERSESSION"


class OutcomeMaturityState(str, Enum):
    UNKNOWN = "UNKNOWN"
    IMMATURE = "IMMATURE"
    PARTIALLY_OBSERVED = "PARTIALLY_OBSERVED"
    MATURE = "MATURE"
    ARCHIVED = "ARCHIVED"
    SUPERSEDED = "SUPERSEDED"


class ObservationWindowType(str, Enum):
    ONE_HOUR = "ONE_HOUR"
    SIX_HOURS = "SIX_HOURS"
    TWENTY_FOUR_HOURS = "TWENTY_FOUR_HOURS"
    SEVEN_DAYS = "SEVEN_DAYS"
    TWENTY_EIGHT_DAYS = "TWENTY_EIGHT_DAYS"
    NINETY_DAYS = "NINETY_DAYS"
    LIFETIME = "LIFETIME"


KPI_CATEGORY_MAP: dict[str, tuple[str, ...]] = {
    "exposure": ("impressions", "ctr_ratio"),
    "engagement": ("watch_time_hours", "average_view_duration_seconds", "average_percentage_viewed_ratio"),
    "community": ("subscribers_gained", "likes", "comments"),
}


_MATURITY_TRANSITIONS: dict[str, set[str]] = {
    OutcomeMaturityState.UNKNOWN.value: {
        OutcomeMaturityState.IMMATURE.value,
        OutcomeMaturityState.PARTIALLY_OBSERVED.value,
    },
    OutcomeMaturityState.IMMATURE.value: {
        OutcomeMaturityState.PARTIALLY_OBSERVED.value,
        OutcomeMaturityState.ARCHIVED.value,
    },
    OutcomeMaturityState.PARTIALLY_OBSERVED.value: {
        OutcomeMaturityState.MATURE.value,
        OutcomeMaturityState.ARCHIVED.value,
        OutcomeMaturityState.SUPERSEDED.value,
    },
    OutcomeMaturityState.MATURE.value: {
        OutcomeMaturityState.ARCHIVED.value,
        OutcomeMaturityState.SUPERSEDED.value,
    },
    OutcomeMaturityState.SUPERSEDED.value: {
        OutcomeMaturityState.ARCHIVED.value,
    },
    OutcomeMaturityState.ARCHIVED.value: set(),
}


_FORBIDDEN_FIELDS = {
    "confidence",
    "probability",
    "prediction_certainty",
    "predicted_ctr",
    "predicted_retention",
    "recommendation_score",
    "rank_score",
    "causal_score",
    "attribution_score",
    "winner_variant",
    "policy_action",
    "rpm",
    "revenue",
    "revenue_currency",
    "estimated_revenue",
}


@dataclass(frozen=True, slots=True)
class OutcomeMaturityRecord:
    schema_version: str
    outcome_record_id: str
    outcome_event_id: str
    event_type: str
    decision_id: str
    learning_record_id: str
    correlation_id: str
    channel_id: str
    content_id: str
    observation_window_type: str
    observation_start: str
    observation_end: str
    observation_timestamp: str
    decision_record_ref: dict[str, Any] | None = None
    learning_record_ref: dict[str, Any] | None = None
    analytics_evidence_refs: tuple[dict[str, Any], ...] = ()
    experiment_evidence_refs: tuple[dict[str, Any], ...] = ()
    impressions: int | None = None
    ctr_ratio: float | None = None
    watch_time_hours: float | None = None
    average_view_duration_seconds: float | None = None
    average_percentage_viewed_ratio: float | None = None
    subscribers_gained: int | None = None
    likes: int | None = None
    comments: int | None = None
    maturity_state: str = OutcomeMaturityState.UNKNOWN.value
    metric_completeness: float | None = None
    evidence_completeness: float | None = None
    sample_sufficiency: float | None = None
    provisional_status: bool = True
    unknown_reasons: tuple[str, ...] = ()
    kpi_categories: dict[str, tuple[str, ...]] | None = None
    record_hash: str = ""
    previous_record_hash: str | None = None
    created_at: str = ""
    created_by: str = ""
    source_module: str = ""
    source_version: str = ""
    advisory_only: bool = True
    pipeline_output_changed: bool = False

    def __post_init__(self) -> None:
        validate_outcome_maturity_row(asdict(self))

    def to_dict(self) -> dict[str, Any]:
        return validate_outcome_maturity_row(asdict(self))


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _parse_iso(name: str, value: Any) -> str:
    text = _safe_text(value)
    if not text:
        raise ValueError(f"missing_field:{name}")
    datetime.fromisoformat(text.replace("Z", "+00:00"))
    return text


def _normalize_int(name: str, value: Any) -> int | None:
    if value is None:
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


def build_kpi_category_map() -> dict[str, tuple[str, ...]]:
    return {key: tuple(values) for key, values in KPI_CATEGORY_MAP.items()}


def compute_outcome_record_id(record: dict[str, Any]) -> str:
    seed = "|".join(
        [
            _safe_text(record.get("decision_id")),
            _safe_text(record.get("learning_record_id")),
            _safe_text(record.get("correlation_id")),
            _safe_text(record.get("channel_id")),
            _safe_text(record.get("content_id")),
        ]
    )
    return "otr_" + _sha(seed)[:24]


def compute_record_hash(record: dict[str, Any]) -> str:
    payload = dict(record)
    payload.pop("record_hash", None)
    payload.pop("outcome_event_id", None)
    payload.pop("created_at", None)
    return "oth_" + _sha(_stable_json(payload))[:24]


def compute_outcome_event_id(record: dict[str, Any]) -> str:
    seed = "|".join(
        [
            _safe_text(record.get("outcome_record_id")),
            _safe_text(record.get("event_type")),
            _safe_text(record.get("maturity_state")),
            _safe_text(record.get("observation_window_type")),
            _safe_text(record.get("record_hash")),
        ]
    )
    return "ote_" + _sha(seed)[:24]


def validate_maturity_transition(previous_state: str, next_state: str) -> bool:
    prev = _safe_text(previous_state)
    nxt = _safe_text(next_state)
    if prev not in _MATURITY_TRANSITIONS:
        return False
    return nxt in _MATURITY_TRANSITIONS.get(prev, set())


def _defaults() -> dict[str, Any]:
    return {
        "schema_version": OUTCOME_MATURITY_SCHEMA_VERSION,
        "outcome_record_id": "",
        "outcome_event_id": "",
        "event_type": OutcomeEventType.INITIAL_OBSERVATION.value,
        "decision_id": "",
        "learning_record_id": "",
        "correlation_id": "",
        "channel_id": "",
        "content_id": "",
        "observation_window_type": ObservationWindowType.TWENTY_FOUR_HOURS.value,
        "observation_start": "",
        "observation_end": "",
        "observation_timestamp": "",
        "decision_record_ref": None,
        "learning_record_ref": None,
        "analytics_evidence_refs": [],
        "experiment_evidence_refs": [],
        "impressions": None,
        "ctr_ratio": None,
        "watch_time_hours": None,
        "average_view_duration_seconds": None,
        "average_percentage_viewed_ratio": None,
        "subscribers_gained": None,
        "likes": None,
        "comments": None,
        "maturity_state": OutcomeMaturityState.UNKNOWN.value,
        "metric_completeness": None,
        "evidence_completeness": None,
        "sample_sufficiency": None,
        "provisional_status": True,
        "unknown_reasons": [],
        "kpi_categories": build_kpi_category_map(),
        "record_hash": "",
        "previous_record_hash": None,
        "created_at": "",
        "created_by": "",
        "source_module": "",
        "source_version": "",
        "advisory_only": True,
        "pipeline_output_changed": False,
    }


def canonicalize_outcome_maturity_row(row: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ValueError("invalid_payload")

    forbidden = [key for key in _FORBIDDEN_FIELDS if key in row]
    if forbidden:
        raise ValueError(f"forbidden_field:{forbidden[0]}")

    normalized = _defaults()
    normalized.update(dict(row))

    if _safe_text(normalized.get("schema_version")) != OUTCOME_MATURITY_SCHEMA_VERSION:
        raise ValueError("invalid_field:schema_version")

    for key in [
        "decision_id",
        "learning_record_id",
        "correlation_id",
        "channel_id",
        "content_id",
        "observation_start",
        "observation_end",
        "observation_timestamp",
        "created_by",
        "source_module",
        "source_version",
    ]:
        normalized[key] = _safe_text(normalized.get(key))
        if not normalized[key]:
            raise ValueError(f"missing_field:{key}")

    normalized["created_at"] = _parse_iso("created_at", normalized.get("created_at"))
    normalized["observation_timestamp"] = _parse_iso("observation_timestamp", normalized.get("observation_timestamp"))
    normalized["observation_start"] = _parse_iso("observation_start", normalized.get("observation_start"))
    normalized["observation_end"] = _parse_iso("observation_end", normalized.get("observation_end"))

    try:
        ObservationWindowType(_safe_text(normalized.get("observation_window_type")))
    except Exception as exc:
        raise ValueError("invalid_field:observation_window_type") from exc

    try:
        OutcomeEventType(_safe_text(normalized.get("event_type")))
    except Exception as exc:
        raise ValueError("invalid_field:event_type") from exc

    try:
        OutcomeMaturityState(_safe_text(normalized.get("maturity_state")))
    except Exception as exc:
        raise ValueError("invalid_field:maturity_state") from exc

    normalized["outcome_record_id"] = _safe_text(normalized.get("outcome_record_id")) or compute_outcome_record_id(normalized)

    normalized["decision_record_ref"] = _normalize_ref(normalized.get("decision_record_ref"))
    normalized["learning_record_ref"] = _normalize_ref(normalized.get("learning_record_ref"))
    normalized["analytics_evidence_refs"] = _normalize_ref_list(normalized.get("analytics_evidence_refs"))
    normalized["experiment_evidence_refs"] = _normalize_ref_list(normalized.get("experiment_evidence_refs"))

    normalized["impressions"] = _normalize_int("impressions", normalized.get("impressions"))
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

    normalized["kpi_categories"] = build_kpi_category_map()

    normalized["previous_record_hash"] = _safe_text(normalized.get("previous_record_hash")) or None
    normalized["record_hash"] = compute_record_hash(normalized)
    normalized["outcome_event_id"] = compute_outcome_event_id(normalized)

    return normalized


def validate_outcome_maturity_row(row: dict[str, Any]) -> dict[str, Any]:
    return canonicalize_outcome_maturity_row(row)


def build_outcome_maturity_record(
    payload: dict[str, Any],
    *,
    created_by: str,
    source_module: str,
    source_version: str,
    created_at: str | None = None,
    previous_record_hash: str | None = None,
    event_type: str | OutcomeEventType | None = None,
    maturity_state: str | OutcomeMaturityState | None = None,
) -> dict[str, Any]:
    base = _defaults()
    base.update(dict(payload or {}))
    if event_type is not None:
        base["event_type"] = event_type.value if isinstance(event_type, OutcomeEventType) else str(event_type)
    if maturity_state is not None:
        base["maturity_state"] = maturity_state.value if isinstance(maturity_state, OutcomeMaturityState) else str(maturity_state)

    base["created_by"] = _safe_text(created_by)
    base["source_module"] = _safe_text(source_module)
    base["source_version"] = _safe_text(source_version)
    base["created_at"] = _safe_text(created_at) or datetime.now(timezone.utc).isoformat()
    base["previous_record_hash"] = _safe_text(previous_record_hash) or _safe_text(base.get("previous_record_hash")) or None

    return canonicalize_outcome_maturity_row(base)
