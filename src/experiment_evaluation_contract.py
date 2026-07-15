from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any


EXPERIMENT_EVALUATION_SCHEMA_VERSION = "v1"
DEFAULT_MINIMUM_SAMPLE_SIZE = 100
DEFAULT_MINIMUM_EXPOSURE_COUNT = 20


class ExperimentEvaluationState(str, Enum):
    NOT_READY = "NOT_READY"
    INSUFFICIENT_EXPOSURE = "INSUFFICIENT_EXPOSURE"
    IMMATURE_OUTCOME = "IMMATURE_OUTCOME"
    CONTAMINATED = "CONTAMINATED"
    EVALUABLE = "EVALUABLE"
    INCONCLUSIVE = "INCONCLUSIVE"
    DIRECTIONAL_ONLY = "DIRECTIONAL_ONLY"
    VALIDATED_RESULT = "VALIDATED_RESULT"


class ContaminationSeverity(str, Enum):
    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class OutcomeMaturityState(str, Enum):
    UNKNOWN = "unknown"
    IMMATURE = "immature"
    PARTIALLY_OBSERVED = "partially_observed"
    MATURE = "mature"
    ARCHIVED = "archived"
    SUPERSEDED = "superseded"


_REQUIRED_FIELDS = (
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
class ExperimentEvaluationRecord:
    schema_version: str
    evaluation_record_id: str
    evaluation_event_id: str
    experiment_id: str
    experiment_version: str
    assignment_id: str
    assignment_seed: str
    assignment_hash: str
    assignment_version: str
    randomization_unit: str
    eligibility_snapshot_hash: str
    control_exposure_count: int
    treatment_exposure_count: int
    total_exposure_count: int
    minimum_exposure_count: int
    control_sample_size: int
    treatment_sample_size: int
    total_sample_size: int
    minimum_sample_size: int
    control_metric_value: float | None
    treatment_metric_value: float | None
    observation_window_type: str
    observation_window_start: str
    observation_window_end: str
    observation_timestamp: str
    outcome_maturity_state: str
    contamination_severity: str
    evidence_lineage_refs: tuple[dict[str, Any], ...] = ()
    evidence_lineage_count: int = 0
    evidence_lineage_required_count: int = 0
    evidence_lineage_completeness: float = 0.0
    replay_integrity_verified: bool = True
    evaluation_state: str = ExperimentEvaluationState.NOT_READY.value
    evaluation_reason: str = ""
    record_hash: str = ""
    previous_record_hash: str | None = None
    created_at: str = ""
    created_by: str = ""
    source_module: str = ""
    source_version: str = ""
    advisory_only: bool = True
    pipeline_output_changed: bool = False

    def __post_init__(self) -> None:
        validate_experiment_evaluation_row(asdict(self))

    def to_dict(self) -> dict[str, Any]:
        return validate_experiment_evaluation_row(asdict(self))


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


def _normalize_float(name: str, value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"invalid_field:{name}")
    try:
        return float(value)
    except Exception as exc:
        raise ValueError(f"invalid_field:{name}") from exc


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


def _normalize_ref_list(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ValueError("invalid_field:evidence_lineage_refs")
    out: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("invalid_field:evidence_lineage_refs")
        out.append(json.loads(_stable_json(item)))
    return out


def compute_evaluation_record_id(record: dict[str, Any]) -> str:
    seed = "|".join(
        [
            _safe_text(record.get("experiment_id")),
            _safe_text(record.get("experiment_version")),
            _safe_text(record.get("assignment_id")),
            _safe_text(record.get("assignment_hash")),
            _safe_text(record.get("eligibility_snapshot_hash")),
            _safe_text(record.get("observation_timestamp")),
        ]
    )
    return "evr_" + _sha(seed)[:24]


def compute_evaluation_event_id(record: dict[str, Any]) -> str:
    seed = "|".join(
        [
            _safe_text(record.get("evaluation_record_id")),
            _safe_text(record.get("evaluation_state")),
            _safe_text(record.get("record_hash")),
        ]
    )
    return "eve_" + _sha(seed)[:24]


def compute_record_hash(record: dict[str, Any]) -> str:
    payload = dict(record)
    payload.pop("record_hash", None)
    payload.pop("evaluation_event_id", None)
    payload.pop("created_at", None)
    payload.pop("previous_record_hash", None)
    return "evh_" + _sha(_stable_json(payload))[:24]


def _defaults() -> dict[str, Any]:
    return {
        "schema_version": EXPERIMENT_EVALUATION_SCHEMA_VERSION,
        "evaluation_record_id": "",
        "evaluation_event_id": "",
        "experiment_id": "",
        "experiment_version": "",
        "assignment_id": "",
        "assignment_seed": "",
        "assignment_hash": "",
        "assignment_version": "",
        "randomization_unit": "",
        "eligibility_snapshot_hash": "",
        "control_exposure_count": 0,
        "treatment_exposure_count": 0,
        "total_exposure_count": 0,
        "minimum_exposure_count": DEFAULT_MINIMUM_EXPOSURE_COUNT,
        "control_sample_size": 0,
        "treatment_sample_size": 0,
        "total_sample_size": 0,
        "minimum_sample_size": DEFAULT_MINIMUM_SAMPLE_SIZE,
        "control_metric_value": None,
        "treatment_metric_value": None,
        "observation_window_type": "",
        "observation_window_start": "",
        "observation_window_end": "",
        "observation_timestamp": "",
        "outcome_maturity_state": OutcomeMaturityState.UNKNOWN.value,
        "contamination_severity": ContaminationSeverity.NONE.value,
        "evidence_lineage_refs": [],
        "evidence_lineage_count": 0,
        "evidence_lineage_required_count": 0,
        "evidence_lineage_completeness": 0.0,
        "replay_integrity_verified": True,
        "evaluation_state": ExperimentEvaluationState.NOT_READY.value,
        "evaluation_reason": "",
        "record_hash": "",
        "previous_record_hash": None,
        "created_at": "",
        "created_by": "",
        "source_module": "",
        "source_version": "",
        "advisory_only": True,
        "pipeline_output_changed": False,
    }


def build_experiment_evaluation_record(
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
    return validate_experiment_evaluation_row(merged, original_row=original)


def classify_experiment_evaluation_state(record: dict[str, Any]) -> tuple[str, str]:
    required_text_fields = (
        "experiment_id",
        "experiment_version",
        "assignment_id",
        "assignment_seed",
        "assignment_hash",
        "assignment_version",
        "randomization_unit",
        "eligibility_snapshot_hash",
        "observation_window_type",
        "observation_window_start",
        "observation_window_end",
        "observation_timestamp",
        "outcome_maturity_state",
    )
    for field in required_text_fields:
        if not _safe_text(record.get(field)):
            return ExperimentEvaluationState.NOT_READY.value, f"missing_field:{field}"

    if _safe_text(record.get("evaluation_record_id")) and _safe_text(record.get("record_hash")):
        pass

    if _safe_text(record.get("contamination_severity")) in {ContaminationSeverity.LOW.value, ContaminationSeverity.MEDIUM.value, ContaminationSeverity.HIGH.value}:
        if _safe_text(record.get("contamination_severity")) != ContaminationSeverity.NONE.value:
            return ExperimentEvaluationState.CONTAMINATED.value, f"contamination:{_safe_text(record.get('contamination_severity'))}"

    total_exposure_count = int(record.get("total_exposure_count") or 0)
    minimum_exposure_count = int(record.get("minimum_exposure_count") or DEFAULT_MINIMUM_EXPOSURE_COUNT)
    control_exposure_count = int(record.get("control_exposure_count") or 0)
    treatment_exposure_count = int(record.get("treatment_exposure_count") or 0)
    if total_exposure_count < minimum_exposure_count or control_exposure_count <= 0 or treatment_exposure_count <= 0:
        return ExperimentEvaluationState.INSUFFICIENT_EXPOSURE.value, "insufficient_exposure"

    maturity_state = _safe_text(record.get("outcome_maturity_state"))
    if maturity_state not in {OutcomeMaturityState.MATURE.value, OutcomeMaturityState.ARCHIVED.value, OutcomeMaturityState.SUPERSEDED.value}:
        return ExperimentEvaluationState.IMMATURE_OUTCOME.value, f"outcome_maturity:{maturity_state}"

    total_sample_size = int(record.get("total_sample_size") or 0)
    minimum_sample_size = int(record.get("minimum_sample_size") or DEFAULT_MINIMUM_SAMPLE_SIZE)
    control_sample_size = int(record.get("control_sample_size") or 0)
    treatment_sample_size = int(record.get("treatment_sample_size") or 0)
    if total_sample_size < minimum_sample_size:
        control_metric = record.get("control_metric_value")
        treatment_metric = record.get("treatment_metric_value")
        if control_metric is not None and treatment_metric is not None and float(control_metric) != float(treatment_metric):
            return ExperimentEvaluationState.DIRECTIONAL_ONLY.value, "directional_signal_below_sample_threshold"
        return ExperimentEvaluationState.INCONCLUSIVE.value, "sample_below_threshold"

    lineage_count = int(record.get("evidence_lineage_count") or 0)
    lineage_required = int(record.get("evidence_lineage_required_count") or 0)
    lineage_completeness = float(record.get("evidence_lineage_completeness") or 0.0)
    if lineage_required > 0 and lineage_count < lineage_required:
        return ExperimentEvaluationState.EVALUABLE.value, "lineage_partial"
    if lineage_required > 0 and lineage_completeness >= 1.0:
        return ExperimentEvaluationState.VALIDATED_RESULT.value, "lineage_complete"
    if control_sample_size > 0 and treatment_sample_size > 0:
        return ExperimentEvaluationState.EVALUABLE.value, "sample_sufficient"
    return ExperimentEvaluationState.INCONCLUSIVE.value, "insufficient_signal"


def validate_experiment_evaluation_row(row: dict[str, Any], original_row: dict[str, Any] | None = None) -> dict[str, Any]:
    merged = _defaults()
    merged.update(dict(row))
    source_row = dict(original_row or row)

    if _safe_text(merged.get("schema_version")) != EXPERIMENT_EVALUATION_SCHEMA_VERSION:
        raise ValueError("invalid_field:schema_version")

    merged["experiment_id"] = _safe_text(merged.get("experiment_id"))
    merged["experiment_version"] = _safe_text(merged.get("experiment_version"))
    merged["assignment_id"] = _safe_text(merged.get("assignment_id"))
    merged["assignment_seed"] = _safe_text(merged.get("assignment_seed"))
    merged["assignment_hash"] = _safe_text(merged.get("assignment_hash"))
    merged["assignment_version"] = _safe_text(merged.get("assignment_version"))
    merged["randomization_unit"] = _safe_text(merged.get("randomization_unit"))
    merged["eligibility_snapshot_hash"] = _safe_text(merged.get("eligibility_snapshot_hash"))
    merged["control_exposure_count"] = _normalize_int("control_exposure_count", merged.get("control_exposure_count"))
    merged["treatment_exposure_count"] = _normalize_int("treatment_exposure_count", merged.get("treatment_exposure_count"))
    merged["total_exposure_count"] = _normalize_int("total_exposure_count", merged.get("total_exposure_count"))
    merged["minimum_exposure_count"] = _normalize_int("minimum_exposure_count", merged.get("minimum_exposure_count"))
    merged["control_sample_size"] = _normalize_int("control_sample_size", merged.get("control_sample_size"))
    merged["treatment_sample_size"] = _normalize_int("treatment_sample_size", merged.get("treatment_sample_size"))
    merged["total_sample_size"] = _normalize_int("total_sample_size", merged.get("total_sample_size"))
    merged["minimum_sample_size"] = _normalize_int("minimum_sample_size", merged.get("minimum_sample_size"))
    merged["control_metric_value"] = _normalize_float("control_metric_value", merged.get("control_metric_value"))
    merged["treatment_metric_value"] = _normalize_float("treatment_metric_value", merged.get("treatment_metric_value"))
    merged["observation_window_type"] = _safe_text(merged.get("observation_window_type"))
    merged["observation_window_start"] = _parse_iso("observation_window_start", merged.get("observation_window_start"))
    merged["observation_window_end"] = _parse_iso("observation_window_end", merged.get("observation_window_end"))
    merged["observation_timestamp"] = _parse_iso("observation_timestamp", merged.get("observation_timestamp"))
    merged["outcome_maturity_state"] = _normalize_state(
        merged.get("outcome_maturity_state"),
        allowed={item.value for item in OutcomeMaturityState},
        field_name="outcome_maturity_state",
    )
    merged["contamination_severity"] = _normalize_state(
        merged.get("contamination_severity"),
        allowed={item.value for item in ContaminationSeverity},
        field_name="contamination_severity",
    )
    merged["evidence_lineage_refs"] = _normalize_ref_list(merged.get("evidence_lineage_refs"))
    merged["evidence_lineage_count"] = _normalize_int("evidence_lineage_count", merged.get("evidence_lineage_count"))
    merged["evidence_lineage_required_count"] = _normalize_int("evidence_lineage_required_count", merged.get("evidence_lineage_required_count"))
    merged["evidence_lineage_completeness"] = float(merged.get("evidence_lineage_completeness") or 0.0)
    merged["replay_integrity_verified"] = _normalize_bool("replay_integrity_verified", merged.get("replay_integrity_verified"))
    merged["created_by"] = _safe_text(merged.get("created_by"))
    merged["source_module"] = _safe_text(merged.get("source_module"))
    merged["source_version"] = _safe_text(merged.get("source_version"))
    merged["created_at"] = _parse_iso("created_at", merged.get("created_at"))
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
    if not merged["assignment_id"]:
        raise ValueError("missing_field:assignment_id")
    if not merged["assignment_seed"]:
        raise ValueError("missing_field:assignment_seed")
    if not merged["assignment_hash"]:
        raise ValueError("missing_field:assignment_hash")
    if not merged["assignment_version"]:
        raise ValueError("missing_field:assignment_version")
    if not merged["randomization_unit"]:
        raise ValueError("missing_field:randomization_unit")
    if not merged["eligibility_snapshot_hash"]:
        raise ValueError("missing_field:eligibility_snapshot_hash")

    derived_state, reason = classify_experiment_evaluation_state(merged)
    supplied_state = _safe_text(source_row.get("evaluation_state"))
    if supplied_state and supplied_state != derived_state:
        raise ValueError(f"invalid_field:evaluation_state:{supplied_state}->{derived_state}")
    merged["evaluation_state"] = derived_state
    merged["evaluation_reason"] = _safe_text(merged.get("evaluation_reason")) or reason

    merged["evaluation_record_id"] = _safe_text(merged.get("evaluation_record_id")) or compute_evaluation_record_id(merged)
    expected_record_hash = compute_record_hash(merged)
    supplied_record_hash = _safe_text(merged.get("record_hash"))
    if supplied_record_hash and supplied_record_hash != expected_record_hash:
        raise ValueError("invalid_field:record_hash")
    merged["record_hash"] = expected_record_hash

    merged["evaluation_event_id"] = _safe_text(merged.get("evaluation_event_id")) or compute_evaluation_event_id(merged)
    if _safe_text(merged.get("evaluation_event_id")) and merged["evaluation_event_id"] != _safe_text(merged.get("evaluation_event_id")):
        raise ValueError("invalid_field:evaluation_event_id")

    if not merged["replay_integrity_verified"]:
        raise ValueError("invalid_field:replay_integrity_verified")

    return merged
