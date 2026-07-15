from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any

from .experiment_evaluation_contract import ContaminationSeverity, OutcomeMaturityState


STATISTICAL_CONFIDENCE_SCHEMA_VERSION = "v1"
DEFAULT_MINIMUM_SAMPLE_REQUIRED = 100
DEFAULT_MINIMUM_POWER_REQUIRED = 0.8
DEFAULT_MINIMUM_DETECTABLE_EFFECT = 0.05


class StatisticalConfidenceState(str, Enum):
    NOT_ASSESSED = "NOT_ASSESSED"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    IMMATURE_WINDOW = "IMMATURE_WINDOW"
    CONTAMINATED = "CONTAMINATED"
    UNDERPOWERED = "UNDERPOWERED"
    DIRECTIONAL_SIGNAL = "DIRECTIONAL_SIGNAL"
    STATISTICALLY_INCONCLUSIVE = "STATISTICALLY_INCONCLUSIVE"
    STATISTICALLY_SUPPORTED = "STATISTICALLY_SUPPORTED"
    INVALIDATED = "INVALIDATED"


_MATURE_WINDOWS = {
    OutcomeMaturityState.MATURE.value,
    OutcomeMaturityState.ARCHIVED.value,
    OutcomeMaturityState.SUPERSEDED.value,
}

_REQUIRED_TEXT_FIELDS = (
    "experiment_id",
    "evaluation_id",
    "created_at",
    "schema_version",
)


@dataclass(frozen=True, slots=True)
class StatisticalConfidenceRecord:
    schema_version: str
    confidence_id: str
    experiment_id: str
    evaluation_id: str
    created_at: str
    confidence_state: str
    observation_window: dict[str, Any]
    sample_size: int
    treatment_size: int
    control_size: int
    minimum_sample_required: int
    minimum_power_required: float
    minimum_detectable_effect: float
    effect_size_absolute: float
    effect_size_relative: float
    confidence_inputs: dict[str, Any]
    contamination_state: str
    maturity_state: str
    lineage_reference: tuple[dict[str, Any], ...]
    confidence_reason: str = ""
    record_hash: str = ""
    previous_record_hash: str | None = None
    created_by: str = ""
    source_module: str = ""
    source_version: str = ""
    advisory_only: bool = True
    pipeline_output_changed: bool = False
    replay_integrity_verified: bool = True

    def __post_init__(self) -> None:
        validate_statistical_confidence_row(asdict(self))

    def to_dict(self) -> dict[str, Any]:
        return validate_statistical_confidence_row(asdict(self))


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _sha(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def _parse_iso(name: str, value: Any) -> str:
    text = _safe_text(value)
    if not text:
        raise ValueError(f"missing_field:{name}")
    datetime.fromisoformat(text.replace("Z", "+00:00"))
    return text


def _normalize_int(name: str, value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError(f"invalid_field:{name}")
    try:
        number = int(value)
    except Exception as exc:
        raise ValueError(f"invalid_field:{name}") from exc
    if number < 0:
        raise ValueError(f"invalid_field:{name}")
    return number


def _normalize_float(name: str, value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError(f"invalid_field:{name}")
    try:
        number = float(value)
    except Exception as exc:
        raise ValueError(f"invalid_field:{name}") from exc
    if not (number == number):
        raise ValueError(f"invalid_field:{name}")
    return number


def _normalize_bool(name: str, value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = _safe_text(value).lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid_field:{name}")


def _normalize_state(value: Any, *, allowed: set[str], field_name: str) -> str:
    text = _safe_text(value)
    if text not in allowed:
        raise ValueError(f"invalid_field:{field_name}")
    return text


def _normalize_observation_window(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("invalid_field:observation_window")
    window = json.loads(_stable_json(value))
    window_type = _safe_text(window.get("window_type"))
    if not window_type:
        raise ValueError("missing_field:observation_window.window_type")
    window_start = _parse_iso("observation_window.start", window.get("start"))
    window_end = _parse_iso("observation_window.end", window.get("end"))
    if window_start > window_end:
        raise ValueError("invalid_field:observation_window")
    window["window_type"] = window_type
    window["start"] = window_start
    window["end"] = window_end
    if _safe_text(window.get("window_state")):
        window["window_state"] = _safe_text(window.get("window_state"))
    return window


def _normalize_confidence_inputs(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("invalid_field:confidence_inputs")
    return json.loads(_stable_json(value))


def _normalize_lineage_reference(value: Any) -> tuple[dict[str, Any], ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError("invalid_field:lineage_reference")
    out: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("invalid_field:lineage_reference")
        ref = json.loads(_stable_json(item))
        if not _safe_text(ref.get("ref_type")) or not _safe_text(ref.get("ref_id")):
            raise ValueError("invalid_field:lineage_reference")
        out.append(ref)
    return tuple(out)


def compute_confidence_id(record: dict[str, Any]) -> str:
    payload = {
        "experiment_id": _safe_text(record.get("experiment_id")),
        "evaluation_id": _safe_text(record.get("evaluation_id")),
        "observation_window": record.get("observation_window"),
        "sample_size": int(record.get("sample_size") or 0),
        "treatment_size": int(record.get("treatment_size") or 0),
        "control_size": int(record.get("control_size") or 0),
        "minimum_sample_required": int(record.get("minimum_sample_required") or 0),
        "minimum_power_required": float(record.get("minimum_power_required") or 0.0),
        "minimum_detectable_effect": float(record.get("minimum_detectable_effect") or 0.0),
        "effect_size_absolute": float(record.get("effect_size_absolute") or 0.0),
        "effect_size_relative": float(record.get("effect_size_relative") or 0.0),
        "confidence_inputs": record.get("confidence_inputs") or {},
        "maturity_state": _safe_text(record.get("maturity_state")),
        "contamination_state": _safe_text(record.get("contamination_state")),
        "lineage_reference": record.get("lineage_reference") or (),
    }
    return "scid_" + _sha(_stable_json(payload))[:24]


def compute_record_hash(record: dict[str, Any]) -> str:
    payload = dict(record)
    payload.pop("record_hash", None)
    payload.pop("previous_record_hash", None)
    payload.pop("created_at", None)
    return "sch_" + _sha(_stable_json(payload))[:24]


def _estimate_power(record: dict[str, Any]) -> float:
    sample_size = int(record.get("sample_size") or 0)
    minimum_sample_required = int(record.get("minimum_sample_required") or 1)
    effect_magnitude = max(
        abs(float(record.get("effect_size_absolute") or 0.0)),
        abs(float(record.get("effect_size_relative") or 0.0)),
    )
    minimum_detectable_effect = abs(float(record.get("minimum_detectable_effect") or 0.0))
    if minimum_sample_required <= 0 or minimum_detectable_effect <= 0:
        return 0.0
    sample_ratio = sample_size / minimum_sample_required
    signal_ratio = effect_magnitude / minimum_detectable_effect
    return round(min(1.0, sample_ratio * signal_ratio), 4)


def _defaults() -> dict[str, Any]:
    return {
        "schema_version": STATISTICAL_CONFIDENCE_SCHEMA_VERSION,
        "confidence_id": "",
        "experiment_id": "",
        "evaluation_id": "",
        "created_at": "",
        "confidence_state": StatisticalConfidenceState.NOT_ASSESSED.value,
        "observation_window": {},
        "sample_size": 0,
        "treatment_size": 0,
        "control_size": 0,
        "minimum_sample_required": DEFAULT_MINIMUM_SAMPLE_REQUIRED,
        "minimum_power_required": DEFAULT_MINIMUM_POWER_REQUIRED,
        "minimum_detectable_effect": DEFAULT_MINIMUM_DETECTABLE_EFFECT,
        "effect_size_absolute": 0.0,
        "effect_size_relative": 0.0,
        "confidence_inputs": {},
        "contamination_state": ContaminationSeverity.NONE.value,
        "maturity_state": OutcomeMaturityState.UNKNOWN.value,
        "lineage_reference": (),
        "confidence_reason": "",
        "record_hash": "",
        "previous_record_hash": None,
        "created_by": "",
        "source_module": "",
        "source_version": "",
        "advisory_only": True,
        "pipeline_output_changed": False,
        "replay_integrity_verified": True,
    }


def build_statistical_confidence_record(
    payload: dict[str, Any],
    *,
    created_by: str,
    source_module: str,
    source_version: str,
    created_at: str | None = None,
    previous_record_hash: str | None = None,
) -> dict[str, Any]:
    original = dict(payload)
    merged = _defaults()
    merged.update(original)
    merged["created_by"] = created_by
    merged["source_module"] = source_module
    merged["source_version"] = source_version
    merged["created_at"] = created_at or datetime.now(timezone.utc).isoformat()
    merged["previous_record_hash"] = previous_record_hash
    return validate_statistical_confidence_row(merged, original_row=original)


def classify_statistical_confidence_state(record: dict[str, Any]) -> tuple[str, str]:
    for field in _REQUIRED_TEXT_FIELDS:
        if not _safe_text(record.get(field)):
            return StatisticalConfidenceState.NOT_ASSESSED.value, f"missing_field:{field}"

    if not record.get("replay_integrity_verified", True):
        return StatisticalConfidenceState.INVALIDATED.value, "replay_integrity_failed"

    confidence_inputs = record.get("confidence_inputs") or {}
    if not isinstance(confidence_inputs, dict):
        return StatisticalConfidenceState.NOT_ASSESSED.value, "invalid_field:confidence_inputs"

    if confidence_inputs.get("synthetic_evidence"):
        return StatisticalConfidenceState.INVALIDATED.value, "synthetic_evidence"

    lineage_reference = record.get("lineage_reference") or ()
    if not lineage_reference:
        return StatisticalConfidenceState.INVALIDATED.value, "missing_lineage_reference"

    if _safe_text(record.get("contamination_state")) != ContaminationSeverity.NONE.value:
        return StatisticalConfidenceState.CONTAMINATED.value, f"contamination:{_safe_text(record.get('contamination_state'))}"

    maturity_state = _safe_text(record.get("maturity_state"))
    if maturity_state not in _MATURE_WINDOWS:
        if maturity_state in {
            OutcomeMaturityState.UNKNOWN.value,
            OutcomeMaturityState.IMMATURE.value,
            OutcomeMaturityState.PARTIALLY_OBSERVED.value,
        }:
            return StatisticalConfidenceState.IMMATURE_WINDOW.value, f"immature_window:{maturity_state}"
        return StatisticalConfidenceState.NOT_ASSESSED.value, "invalid_field:maturity_state"

    sample_size = int(record.get("sample_size") or 0)
    control_size = int(record.get("control_size") or 0)
    treatment_size = int(record.get("treatment_size") or 0)
    minimum_sample_required = int(record.get("minimum_sample_required") or DEFAULT_MINIMUM_SAMPLE_REQUIRED)
    if sample_size <= 0 or control_size <= 0 or treatment_size <= 0:
        return StatisticalConfidenceState.INSUFFICIENT_SAMPLE.value, "missing_arm_sample"
    if sample_size != control_size + treatment_size:
        return StatisticalConfidenceState.INVALIDATED.value, "sample_inconsistency"
    if sample_size < minimum_sample_required:
        return StatisticalConfidenceState.INSUFFICIENT_SAMPLE.value, "sample_below_threshold"

    comparison_family = _safe_text(confidence_inputs.get("comparison_family"))
    correction_method = _safe_text(confidence_inputs.get("correction_method"))
    if not comparison_family or not correction_method:
        return StatisticalConfidenceState.INVALIDATED.value, "comparison_controls_missing"

    minimum_power_required = float(record.get("minimum_power_required") or DEFAULT_MINIMUM_POWER_REQUIRED)
    minimum_detectable_effect = abs(float(record.get("minimum_detectable_effect") or DEFAULT_MINIMUM_DETECTABLE_EFFECT))
    if minimum_power_required <= 0.0 or minimum_power_required > 1.0:
        return StatisticalConfidenceState.NOT_ASSESSED.value, "invalid_field:minimum_power_required"
    if minimum_detectable_effect <= 0.0:
        return StatisticalConfidenceState.NOT_ASSESSED.value, "invalid_field:minimum_detectable_effect"

    estimated_power = _estimate_power(record)
    if estimated_power < minimum_power_required:
        if abs(float(record.get("effect_size_absolute") or 0.0)) > 0.0 or abs(float(record.get("effect_size_relative") or 0.0)) > 0.0:
            return StatisticalConfidenceState.UNDERPOWERED.value, f"underpowered:{estimated_power:.4f}"
        return StatisticalConfidenceState.STATISTICALLY_INCONCLUSIVE.value, "no_signal"

    effect_magnitude = max(
        abs(float(record.get("effect_size_absolute") or 0.0)),
        abs(float(record.get("effect_size_relative") or 0.0)),
    )
    if effect_magnitude == 0.0:
        return StatisticalConfidenceState.STATISTICALLY_INCONCLUSIVE.value, "zero_effect"
    if effect_magnitude < minimum_detectable_effect:
        return StatisticalConfidenceState.DIRECTIONAL_SIGNAL.value, f"directional_signal:{effect_magnitude:.4f}"

    return StatisticalConfidenceState.STATISTICALLY_SUPPORTED.value, f"supported:{estimated_power:.4f}"


def validate_statistical_confidence_row(row: dict[str, Any], original_row: dict[str, Any] | None = None) -> dict[str, Any]:
    merged = _defaults()
    merged.update(dict(row))
    source_row = dict(original_row or row)

    if _safe_text(merged.get("schema_version")) != STATISTICAL_CONFIDENCE_SCHEMA_VERSION:
        raise ValueError("invalid_field:schema_version")

    merged["experiment_id"] = _safe_text(merged.get("experiment_id"))
    merged["evaluation_id"] = _safe_text(merged.get("evaluation_id"))
    merged["created_at"] = _parse_iso("created_at", merged.get("created_at"))
    merged["observation_window"] = _normalize_observation_window(merged.get("observation_window"))
    merged["sample_size"] = _normalize_int("sample_size", merged.get("sample_size"))
    merged["treatment_size"] = _normalize_int("treatment_size", merged.get("treatment_size"))
    merged["control_size"] = _normalize_int("control_size", merged.get("control_size"))
    merged["minimum_sample_required"] = _normalize_int("minimum_sample_required", merged.get("minimum_sample_required"))
    merged["minimum_power_required"] = _normalize_float("minimum_power_required", merged.get("minimum_power_required"))
    merged["minimum_detectable_effect"] = abs(_normalize_float("minimum_detectable_effect", merged.get("minimum_detectable_effect")))
    merged["effect_size_absolute"] = _normalize_float("effect_size_absolute", merged.get("effect_size_absolute"))
    merged["effect_size_relative"] = _normalize_float("effect_size_relative", merged.get("effect_size_relative"))
    merged["confidence_inputs"] = _normalize_confidence_inputs(merged.get("confidence_inputs"))
    merged["contamination_state"] = _normalize_state(
        merged.get("contamination_state"),
        allowed={item.value for item in ContaminationSeverity},
        field_name="contamination_state",
    )
    merged["maturity_state"] = _normalize_state(
        merged.get("maturity_state"),
        allowed={item.value for item in OutcomeMaturityState},
        field_name="maturity_state",
    )
    merged["lineage_reference"] = _normalize_lineage_reference(merged.get("lineage_reference"))
    merged["created_by"] = _safe_text(merged.get("created_by"))
    merged["source_module"] = _safe_text(merged.get("source_module"))
    merged["source_version"] = _safe_text(merged.get("source_version"))
    merged["advisory_only"] = _normalize_bool("advisory_only", merged.get("advisory_only"))
    merged["pipeline_output_changed"] = _normalize_bool("pipeline_output_changed", merged.get("pipeline_output_changed"))
    merged["replay_integrity_verified"] = _normalize_bool("replay_integrity_verified", merged.get("replay_integrity_verified"))

    if not merged["created_by"]:
        raise ValueError("missing_field:created_by")
    if not merged["source_module"]:
        raise ValueError("missing_field:source_module")
    if not merged["source_version"]:
        raise ValueError("missing_field:source_version")
    if not merged["experiment_id"]:
        raise ValueError("missing_field:experiment_id")
    if not merged["evaluation_id"]:
        raise ValueError("missing_field:evaluation_id")
    if not merged["lineage_reference"]:
        raise ValueError("missing_field:lineage_reference")

    derived_state, reason = classify_statistical_confidence_state(merged)
    supplied_state = _safe_text(source_row.get("confidence_state"))
    if supplied_state and supplied_state != derived_state:
        raise ValueError(f"invalid_field:confidence_state:{supplied_state}->{derived_state}")
    merged["confidence_state"] = derived_state
    merged["confidence_reason"] = _safe_text(merged.get("confidence_reason")) or reason

    merged["confidence_id"] = _safe_text(merged.get("confidence_id")) or compute_confidence_id(merged)
    expected_record_hash = compute_record_hash(merged)
    supplied_record_hash = _safe_text(merged.get("record_hash"))
    if supplied_record_hash and supplied_record_hash != expected_record_hash:
        raise ValueError("invalid_field:record_hash")
    merged["record_hash"] = expected_record_hash

    return merged
