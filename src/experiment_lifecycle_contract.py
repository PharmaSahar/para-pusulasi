from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any


EXPERIMENT_LIFECYCLE_SCHEMA_VERSION = "v1"
ASSIGNMENT_VERSION = "v1"


class LifecycleEventType(str, Enum):
    ASSIGNMENT = "assignment"
    EXPOSURE = "exposure"
    CONTAMINATION = "contamination"


class ContaminationSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


_REQUIRED_ASSIGNMENT_FIELDS = (
    "experiment_id",
    "experiment_version",
    "assignment_id",
    "assignment_seed",
    "assignment_hash",
    "assignment_version",
    "randomization_unit",
    "eligibility_snapshot_hash",
)


@dataclass(frozen=True, slots=True)
class ExperimentLifecycleEvent:
    schema_version: str
    lifecycle_event_id: str
    event_type: str
    experiment_id: str
    experiment_version: str
    assignment_id: str
    assignment_seed: str
    assignment_hash: str
    assignment_version: str
    randomization_unit: str
    randomization_key: str
    eligibility_snapshot: dict[str, Any]
    eligibility_snapshot_hash: str
    assigned_variant: str
    exposure_name: str | None = None
    exposure_timestamp: str | None = None
    exposure_dedupe_key: str | None = None
    contamination_severity: str | None = None
    contamination_reason: str | None = None
    intervention_action: str | None = "record_only"
    record_hash: str = ""
    previous_record_hash: str | None = None
    created_at: str = ""
    created_by: str = ""
    source_module: str = ""
    source_version: str = ""
    advisory_only: bool = True
    pipeline_output_changed: bool = False

    def __post_init__(self) -> None:
        validate_experiment_lifecycle_event_row(asdict(self))

    def to_dict(self) -> dict[str, Any]:
        return validate_experiment_lifecycle_event_row(asdict(self))


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _sha(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def _parse_iso(name: str, value: Any, *, allow_none: bool = False) -> str | None:
    text = _safe_text(value)
    if not text:
        if allow_none:
            return None
        raise ValueError(f"missing_field:{name}")
    datetime.fromisoformat(text.replace("Z", "+00:00"))
    return text


def _normalize_bool(name: str, value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = _safe_text(value).lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid_field:{name}")


def _normalize_event_type(value: Any) -> str:
    text = _safe_text(value).lower()
    allowed = {item.value for item in LifecycleEventType}
    if text not in allowed:
        raise ValueError("invalid_field:event_type")
    return text


def _normalize_severity(value: Any) -> str | None:
    text = _safe_text(value).upper()
    if not text:
        return None
    allowed = {item.value for item in ContaminationSeverity}
    if text not in allowed:
        raise ValueError("invalid_field:contamination_severity")
    return text


def _normalize_snapshot(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("invalid_field:eligibility_snapshot")
    return json.loads(_stable_json(value))


def compute_eligibility_snapshot_hash(snapshot: dict[str, Any]) -> str:
    return "esh_" + _sha(_stable_json(snapshot))[:24]


def compute_assignment_seed(record: dict[str, Any]) -> str:
    seed = "|".join(
        [
            _safe_text(record.get("experiment_id")),
            _safe_text(record.get("experiment_version")),
            _safe_text(record.get("randomization_unit")),
            _safe_text(record.get("randomization_key")),
            _safe_text(record.get("eligibility_snapshot_hash")),
            _safe_text(record.get("assignment_version")) or ASSIGNMENT_VERSION,
        ]
    )
    return "asd_" + _sha(seed)[:24]


def compute_assignment_id(record: dict[str, Any]) -> str:
    seed = "|".join(
        [
            _safe_text(record.get("experiment_id")),
            _safe_text(record.get("experiment_version")),
            _safe_text(record.get("randomization_unit")),
            _safe_text(record.get("randomization_key")),
            _safe_text(record.get("assignment_version")) or ASSIGNMENT_VERSION,
        ]
    )
    return "asn_" + _sha(seed)[:24]


def compute_assignment_hash(record: dict[str, Any]) -> str:
    payload = {
        "assignment_id": _safe_text(record.get("assignment_id")),
        "assignment_seed": _safe_text(record.get("assignment_seed")),
        "assigned_variant": _safe_text(record.get("assigned_variant")),
        "eligibility_snapshot_hash": _safe_text(record.get("eligibility_snapshot_hash")),
        "experiment_id": _safe_text(record.get("experiment_id")),
        "experiment_version": _safe_text(record.get("experiment_version")),
        "randomization_key": _safe_text(record.get("randomization_key")),
        "randomization_unit": _safe_text(record.get("randomization_unit")),
    }
    return "ash_" + _sha(_stable_json(payload))[:24]


def compute_exposure_dedupe_key(record: dict[str, Any]) -> str:
    seed = "|".join(
        [
            _safe_text(record.get("assignment_id")),
            _safe_text(record.get("assignment_hash")),
            _safe_text(record.get("exposure_name")),
            _safe_text(record.get("exposure_timestamp")),
        ]
    )
    return "exd_" + _sha(seed)[:24]


def compute_record_hash(record: dict[str, Any]) -> str:
    payload = dict(record)
    payload.pop("record_hash", None)
    payload.pop("lifecycle_event_id", None)
    payload.pop("created_at", None)
    return "elh_" + _sha(_stable_json(payload))[:24]


def compute_lifecycle_event_id(record: dict[str, Any]) -> str:
    seed = "|".join(
        [
            _safe_text(record.get("assignment_id")),
            _safe_text(record.get("event_type")),
            _safe_text(record.get("record_hash")),
        ]
    )
    return "ele_" + _sha(seed)[:24]


def _defaults() -> dict[str, Any]:
    return {
        "schema_version": EXPERIMENT_LIFECYCLE_SCHEMA_VERSION,
        "lifecycle_event_id": "",
        "event_type": LifecycleEventType.ASSIGNMENT.value,
        "experiment_id": "",
        "experiment_version": "",
        "assignment_id": "",
        "assignment_seed": "",
        "assignment_hash": "",
        "assignment_version": ASSIGNMENT_VERSION,
        "randomization_unit": "",
        "randomization_key": "",
        "eligibility_snapshot": {},
        "eligibility_snapshot_hash": "",
        "assigned_variant": "",
        "exposure_name": None,
        "exposure_timestamp": None,
        "exposure_dedupe_key": None,
        "contamination_severity": None,
        "contamination_reason": None,
        "intervention_action": "record_only",
        "record_hash": "",
        "previous_record_hash": None,
        "created_at": "",
        "created_by": "",
        "source_module": "",
        "source_version": "",
        "advisory_only": True,
        "pipeline_output_changed": False,
    }


def validate_experiment_lifecycle_event_row(row: dict[str, Any]) -> dict[str, Any]:
    merged = _defaults()
    merged.update(dict(row))

    if _safe_text(merged.get("schema_version")) != EXPERIMENT_LIFECYCLE_SCHEMA_VERSION:
        raise ValueError("invalid_field:schema_version")

    merged["event_type"] = _normalize_event_type(merged.get("event_type"))
    merged["experiment_id"] = _safe_text(merged.get("experiment_id"))
    merged["experiment_version"] = _safe_text(merged.get("experiment_version"))
    merged["assignment_version"] = _safe_text(merged.get("assignment_version")) or ASSIGNMENT_VERSION
    merged["randomization_unit"] = _safe_text(merged.get("randomization_unit"))
    merged["randomization_key"] = _safe_text(merged.get("randomization_key"))
    merged["assigned_variant"] = _safe_text(merged.get("assigned_variant"))

    merged["eligibility_snapshot"] = _normalize_snapshot(merged.get("eligibility_snapshot"))
    expected_snapshot_hash = compute_eligibility_snapshot_hash(merged["eligibility_snapshot"])
    supplied_snapshot_hash = _safe_text(merged.get("eligibility_snapshot_hash"))
    if supplied_snapshot_hash and supplied_snapshot_hash != expected_snapshot_hash:
        raise ValueError("invalid_field:eligibility_snapshot_hash")
    merged["eligibility_snapshot_hash"] = expected_snapshot_hash

    merged["assignment_seed"] = _safe_text(merged.get("assignment_seed")) or compute_assignment_seed(merged)
    merged["assignment_id"] = _safe_text(merged.get("assignment_id")) or compute_assignment_id(merged)

    expected_assignment_hash = compute_assignment_hash(merged)
    supplied_assignment_hash = _safe_text(merged.get("assignment_hash"))
    if supplied_assignment_hash and supplied_assignment_hash != expected_assignment_hash:
        raise ValueError("invalid_field:assignment_hash")
    merged["assignment_hash"] = expected_assignment_hash

    if merged["event_type"] in {LifecycleEventType.ASSIGNMENT.value, LifecycleEventType.EXPOSURE.value}:
        for field in _REQUIRED_ASSIGNMENT_FIELDS:
            if not _safe_text(merged.get(field)):
                raise ValueError(f"missing_field:{field}")

    merged["exposure_name"] = _safe_text(merged.get("exposure_name")) or None
    merged["exposure_timestamp"] = _parse_iso("exposure_timestamp", merged.get("exposure_timestamp"), allow_none=True)

    if merged["event_type"] == LifecycleEventType.EXPOSURE.value:
        if not merged["exposure_name"]:
            raise ValueError("missing_field:exposure_name")
        if not merged["exposure_timestamp"]:
            raise ValueError("missing_field:exposure_timestamp")
        merged["exposure_dedupe_key"] = _safe_text(merged.get("exposure_dedupe_key")) or compute_exposure_dedupe_key(merged)
    else:
        merged["exposure_dedupe_key"] = _safe_text(merged.get("exposure_dedupe_key")) or None

    merged["contamination_severity"] = _normalize_severity(merged.get("contamination_severity"))
    merged["contamination_reason"] = _safe_text(merged.get("contamination_reason")) or None
    merged["intervention_action"] = _safe_text(merged.get("intervention_action")) or "record_only"
    if merged["event_type"] == LifecycleEventType.CONTAMINATION.value:
        if merged["contamination_severity"] is None:
            raise ValueError("missing_field:contamination_severity")
        if merged["intervention_action"] != "record_only":
            raise ValueError("invalid_field:intervention_action")

    merged["previous_record_hash"] = _safe_text(merged.get("previous_record_hash")) or None
    merged["created_by"] = _safe_text(merged.get("created_by"))
    merged["created_at"] = _parse_iso("created_at", merged.get("created_at"))
    merged["source_module"] = _safe_text(merged.get("source_module"))
    merged["source_version"] = _safe_text(merged.get("source_version"))
    merged["advisory_only"] = _normalize_bool("advisory_only", merged.get("advisory_only"))
    merged["pipeline_output_changed"] = _normalize_bool("pipeline_output_changed", merged.get("pipeline_output_changed"))

    if not merged["created_by"]:
        raise ValueError("missing_field:created_by")
    if not merged["source_module"]:
        raise ValueError("missing_field:source_module")
    if not merged["source_version"]:
        raise ValueError("missing_field:source_version")
    if not merged["experiment_id"]:
        raise ValueError("missing_field:experiment_id")
    if not merged["experiment_version"]:
        raise ValueError("missing_field:experiment_version")
    if not merged["randomization_unit"]:
        raise ValueError("missing_field:randomization_unit")
    if not merged["randomization_key"]:
        raise ValueError("missing_field:randomization_key")
    if not merged["assigned_variant"]:
        raise ValueError("missing_field:assigned_variant")

    expected_record_hash = compute_record_hash(merged)
    supplied_record_hash = _safe_text(merged.get("record_hash"))
    if supplied_record_hash and supplied_record_hash != expected_record_hash:
        raise ValueError("invalid_field:record_hash")
    merged["record_hash"] = expected_record_hash

    expected_event_id = compute_lifecycle_event_id(merged)
    supplied_event_id = _safe_text(merged.get("lifecycle_event_id"))
    if supplied_event_id and supplied_event_id != expected_event_id:
        raise ValueError("invalid_field:lifecycle_event_id")
    merged["lifecycle_event_id"] = expected_event_id

    return merged


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_experiment_lifecycle_event(
    payload: dict[str, Any],
    *,
    created_by: str,
    source_module: str,
    source_version: str,
    created_at: str | None = None,
    previous_record_hash: str | None = None,
    event_type: str | LifecycleEventType | None = None,
) -> dict[str, Any]:
    merged = _defaults()
    merged.update(dict(payload))
    if event_type is not None:
        merged["event_type"] = event_type.value if isinstance(event_type, LifecycleEventType) else str(event_type)
    merged["created_by"] = created_by
    merged["source_module"] = source_module
    merged["source_version"] = source_version
    merged["created_at"] = created_at or _now_iso()
    merged["previous_record_hash"] = previous_record_hash
    return validate_experiment_lifecycle_event_row(merged)
