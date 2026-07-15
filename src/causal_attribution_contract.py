from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any


CAUSAL_ATTRIBUTION_SCHEMA_VERSION = "v1"


class CausalAttributionState(str, Enum):
    NOT_ATTRIBUTABLE = "NOT_ATTRIBUTABLE"
    INSUFFICIENT_LINEAGE = "INSUFFICIENT_LINEAGE"
    INSUFFICIENT_CONTROL = "INSUFFICIENT_CONTROL"
    IMMATURE_OUTCOME = "IMMATURE_OUTCOME"
    CONTAMINATED = "CONTAMINATED"
    CONFOUNDED = "CONFOUNDED"
    UNDERPOWERED = "UNDERPOWERED"
    ASSOCIATIONAL_ONLY = "ASSOCIATIONAL_ONLY"
    ATTRIBUTION_ELIGIBLE = "ATTRIBUTION_ELIGIBLE"
    CAUSALLY_INCONCLUSIVE = "CAUSALLY_INCONCLUSIVE"
    CAUSALLY_SUPPORTED = "CAUSALLY_SUPPORTED"
    INVALIDATED = "INVALIDATED"


class ConfounderStatus(str, Enum):
    NOT_DECLARED = "NOT_DECLARED"
    DECLARED = "DECLARED"
    PARTIALLY_RESOLVED = "PARTIALLY_RESOLVED"
    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"
    INVALID = "INVALID"


class CounterfactualStatus(str, Enum):
    OBSERVED_CONTROL_OUTCOME = "OBSERVED_CONTROL_OUTCOME"
    EXPERIMENT_DERIVED_COUNTERFACTUAL = "EXPERIMENT_DERIVED_COUNTERFACTUAL"
    UNAVAILABLE = "UNAVAILABLE"
    SYNTHETIC_OR_SIMULATED = "SYNTHETIC_OR_SIMULATED"


_MATURE_OUTCOME_STATES = {"mature", "archived", "superseded"}

_REQUIRED_TEXT_FIELDS = (
    "schema_version",
    "experiment_id",
    "experiment_version",
    "evaluation_id",
    "confidence_id",
    "decision_id",
    "learning_record_id",
    "outcome_record_id",
    "assignment_id",
    "correlation_id",
    "channel_id",
    "content_id",
    "created_at",
)


@dataclass(frozen=True, slots=True)
class CausalAttributionRecord:
    schema_version: str
    attribution_record_id: str
    attribution_event_id: str
    experiment_id: str
    experiment_version: str
    evaluation_id: str
    confidence_id: str
    decision_id: str
    learning_record_id: str
    outcome_record_id: str
    assignment_id: str
    correlation_id: str
    channel_id: str
    content_id: str
    treatment_variant: str
    control_variant: str
    treatment_assignment_ref: str
    control_assignment_ref: str
    treatment_exposure_refs: tuple[dict[str, Any], ...]
    control_exposure_refs: tuple[dict[str, Any], ...]
    assignment_method: str
    randomized_assignment_proven: bool
    control_group_present: bool
    treatment_group_present: bool
    exposure_completeness: bool
    observation_window: dict[str, Any]
    observation_window_type: str
    outcome_maturity_state: str
    treatment_outcome_ref: str
    control_outcome_ref: str
    outcome_completeness: bool
    confidence_state: str
    sample_sufficiency: bool
    power_sufficiency: bool
    multiple_comparison_governed: bool
    effect_size_available: bool
    uncertainty_available: bool
    confounder_set_id: str
    declared_confounders: tuple[str, ...]
    unresolved_confounders: tuple[str, ...]
    confounder_status: str
    confounder_evidence_refs: tuple[dict[str, Any], ...]
    counterfactual_method: str
    counterfactual_status: str
    counterfactual_evidence_refs: tuple[dict[str, Any], ...]
    counterfactual_is_observed: bool
    counterfactual_is_synthetic: bool
    contamination_state: str
    contamination_severity: str
    lineage_complete: bool
    replay_integrity: bool
    evidence_is_synthetic: bool
    invalidation_reasons: tuple[str, ...]
    attribution_state: str
    attribution_reason: str
    treatment_effect_absolute: float | None
    treatment_effect_relative: float | None
    created_at: str
    created_by: str
    source_module: str
    source_version: str
    previous_record_hash: str | None = None
    record_hash: str = ""

    def __post_init__(self) -> None:
        validate_causal_attribution_row(asdict(self))

    def to_dict(self) -> dict[str, Any]:
        return validate_causal_attribution_row(asdict(self))


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


def _normalize_bool(name: str, value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = _safe_text(value).lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid_field:{name}")


def _normalize_float_or_none(name: str, value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"invalid_field:{name}")
    try:
        out = float(value)
    except Exception as exc:
        raise ValueError(f"invalid_field:{name}") from exc
    if not (out == out):
        raise ValueError(f"invalid_field:{name}")
    return out


def _normalize_string_list(name: str, value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"invalid_field:{name}")
    out: list[str] = []
    for item in value:
        text = _safe_text(item)
        if not text:
            raise ValueError(f"invalid_field:{name}")
        out.append(text)
    return tuple(out)


def _normalize_ref_list(name: str, value: Any) -> tuple[dict[str, Any], ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"invalid_field:{name}")
    out: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            ref = json.loads(_stable_json(item))
            if not _safe_text(ref.get("ref_type")) or not _safe_text(ref.get("ref_id")):
                raise ValueError(f"invalid_field:{name}")
            out.append(ref)
            continue
        text = _safe_text(item)
        if not text:
            raise ValueError(f"invalid_field:{name}")
        out.append({"ref_type": "generic", "ref_id": text})
    return tuple(out)


def _normalize_observation_window(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("invalid_field:observation_window")
    window = json.loads(_stable_json(value))
    start = _parse_iso("observation_window.start", window.get("start"))
    end = _parse_iso("observation_window.end", window.get("end"))
    if start > end:
        raise ValueError("invalid_field:observation_window")
    window_type = _safe_text(window.get("window_type"))
    if not window_type:
        raise ValueError("missing_field:observation_window.window_type")
    window["start"] = start
    window["end"] = end
    window["window_type"] = window_type
    return window


def _normalize_enum(name: str, value: Any, *, allowed: set[str]) -> str:
    text = _safe_text(value)
    if text not in allowed:
        raise ValueError(f"invalid_field:{name}")
    return text


def _defaults() -> dict[str, Any]:
    return {
        "schema_version": CAUSAL_ATTRIBUTION_SCHEMA_VERSION,
        "attribution_record_id": "",
        "attribution_event_id": "",
        "experiment_id": "",
        "experiment_version": "",
        "evaluation_id": "",
        "confidence_id": "",
        "decision_id": "",
        "learning_record_id": "",
        "outcome_record_id": "",
        "assignment_id": "",
        "correlation_id": "",
        "channel_id": "",
        "content_id": "",
        "treatment_variant": "",
        "control_variant": "",
        "treatment_assignment_ref": "",
        "control_assignment_ref": "",
        "treatment_exposure_refs": (),
        "control_exposure_refs": (),
        "assignment_method": "",
        "randomized_assignment_proven": False,
        "control_group_present": False,
        "treatment_group_present": False,
        "exposure_completeness": False,
        "observation_window": {},
        "observation_window_type": "",
        "outcome_maturity_state": "unknown",
        "treatment_outcome_ref": "",
        "control_outcome_ref": "",
        "outcome_completeness": False,
        "confidence_state": "",
        "sample_sufficiency": False,
        "power_sufficiency": False,
        "multiple_comparison_governed": False,
        "effect_size_available": False,
        "uncertainty_available": False,
        "confounder_set_id": "",
        "declared_confounders": (),
        "unresolved_confounders": (),
        "confounder_status": ConfounderStatus.NOT_DECLARED.value,
        "confounder_evidence_refs": (),
        "counterfactual_method": "",
        "counterfactual_status": CounterfactualStatus.UNAVAILABLE.value,
        "counterfactual_evidence_refs": (),
        "counterfactual_is_observed": False,
        "counterfactual_is_synthetic": False,
        "contamination_state": "NONE",
        "contamination_severity": "NONE",
        "lineage_complete": False,
        "replay_integrity": True,
        "evidence_is_synthetic": False,
        "invalidation_reasons": (),
        "attribution_state": CausalAttributionState.NOT_ATTRIBUTABLE.value,
        "attribution_reason": "",
        "treatment_effect_absolute": None,
        "treatment_effect_relative": None,
        "created_at": "",
        "created_by": "",
        "source_module": "",
        "source_version": "",
        "previous_record_hash": None,
        "record_hash": "",
    }


def compute_attribution_record_id(record: dict[str, Any]) -> str:
    payload = {
        "experiment_id": _safe_text(record.get("experiment_id")),
        "experiment_version": _safe_text(record.get("experiment_version")),
        "evaluation_id": _safe_text(record.get("evaluation_id")),
        "confidence_id": _safe_text(record.get("confidence_id")),
        "decision_id": _safe_text(record.get("decision_id")),
        "assignment_id": _safe_text(record.get("assignment_id")),
        "correlation_id": _safe_text(record.get("correlation_id")),
        "channel_id": _safe_text(record.get("channel_id")),
        "content_id": _safe_text(record.get("content_id")),
        "treatment_variant": _safe_text(record.get("treatment_variant")),
        "control_variant": _safe_text(record.get("control_variant")),
        "observation_window": record.get("observation_window"),
    }
    return "car_" + _sha(_stable_json(payload))[:24]


def compute_record_hash(record: dict[str, Any]) -> str:
    payload = dict(record)
    payload.pop("record_hash", None)
    payload.pop("attribution_event_id", None)
    payload.pop("created_at", None)
    payload.pop("previous_record_hash", None)
    return "cah_" + _sha(_stable_json(payload))[:24]


def compute_attribution_event_id(record: dict[str, Any]) -> str:
    payload = {
        "attribution_record_id": _safe_text(record.get("attribution_record_id")),
        "attribution_state": _safe_text(record.get("attribution_state")),
        "record_hash": _safe_text(record.get("record_hash")),
    }
    return "cae_" + _sha(_stable_json(payload))[:24]


def classify_causal_attribution_state(record: dict[str, Any]) -> tuple[str, str]:
    for field in _REQUIRED_TEXT_FIELDS:
        if not _safe_text(record.get(field)):
            return CausalAttributionState.NOT_ATTRIBUTABLE.value, f"missing_field:{field}"

    if not bool(record.get("replay_integrity", True)):
        return CausalAttributionState.INVALIDATED.value, "replay_integrity_failed"

    invalidation_reasons = {_safe_text(item) for item in (record.get("invalidation_reasons") or ())}
    invalidation_reasons.discard("")
    if "source_history_corrupted" in invalidation_reasons:
        return CausalAttributionState.INVALIDATED.value, "source_history_corrupted"
    if "fabricated_counterfactual" in invalidation_reasons:
        return CausalAttributionState.INVALIDATED.value, "fabricated_counterfactual"
    if invalidation_reasons:
        return CausalAttributionState.INVALIDATED.value, "explicit_invalidation"

    if bool(record.get("evidence_is_synthetic", False)):
        return CausalAttributionState.INVALIDATED.value, "synthetic_evidence"

    if not bool(record.get("lineage_complete", False)):
        return CausalAttributionState.INSUFFICIENT_LINEAGE.value, "lineage_incomplete"

    if not _safe_text(record.get("treatment_assignment_ref")) or not _safe_text(record.get("control_assignment_ref")):
        return CausalAttributionState.INSUFFICIENT_CONTROL.value, "missing_assignment_reference"

    if not bool(record.get("control_group_present", False)) or not bool(record.get("treatment_group_present", False)):
        return CausalAttributionState.INSUFFICIENT_CONTROL.value, "missing_control_or_treatment_group"

    if not bool(record.get("exposure_completeness", False)):
        return CausalAttributionState.INSUFFICIENT_CONTROL.value, "exposure_incomplete"

    if not (record.get("treatment_exposure_refs") and record.get("control_exposure_refs")):
        return CausalAttributionState.INSUFFICIENT_CONTROL.value, "missing_exposure_references"

    if not bool(record.get("outcome_completeness", False)):
        return CausalAttributionState.INSUFFICIENT_CONTROL.value, "outcome_incomplete"

    if not _safe_text(record.get("treatment_outcome_ref")) or not _safe_text(record.get("control_outcome_ref")):
        return CausalAttributionState.INSUFFICIENT_CONTROL.value, "missing_outcome_references"

    if _safe_text(record.get("outcome_maturity_state")) not in _MATURE_OUTCOME_STATES:
        return CausalAttributionState.IMMATURE_OUTCOME.value, f"immature_outcome:{_safe_text(record.get('outcome_maturity_state'))}"

    contamination_state = _safe_text(record.get("contamination_state")).upper()
    contamination_severity = _safe_text(record.get("contamination_severity")).upper()
    if contamination_state not in {"", "NONE"}:
        return CausalAttributionState.CONTAMINATED.value, f"contamination:{contamination_state}"
    if contamination_severity in {"LOW", "MEDIUM", "HIGH", "BLOCKING"} and contamination_severity != "NONE":
        return CausalAttributionState.CONTAMINATED.value, f"contamination_severity:{contamination_severity}"

    confounder_status = _safe_text(record.get("confounder_status"))
    unresolved = tuple(record.get("unresolved_confounders") or ())
    if not _safe_text(record.get("confounder_set_id")):
        return CausalAttributionState.CONFOUNDED.value, "confounder_set_missing"
    if confounder_status in {
        ConfounderStatus.NOT_DECLARED.value,
        ConfounderStatus.UNRESOLVED.value,
        ConfounderStatus.PARTIALLY_RESOLVED.value,
        ConfounderStatus.INVALID.value,
    }:
        return CausalAttributionState.CONFOUNDED.value, f"confounder_status:{confounder_status}"
    if unresolved:
        return CausalAttributionState.CONFOUNDED.value, "unresolved_confounders"

    if not bool(record.get("sample_sufficiency", False)) or not bool(record.get("power_sufficiency", False)):
        return CausalAttributionState.UNDERPOWERED.value, "sample_or_power_insufficient"

    assignment_method = _safe_text(record.get("assignment_method")).lower()
    if not bool(record.get("randomized_assignment_proven", False)) or assignment_method in {
        "observational",
        "natural_experiment",
        "unknown",
        "",
    }:
        return CausalAttributionState.ASSOCIATIONAL_ONLY.value, "non_randomized_or_observational"

    confidence_state = _safe_text(record.get("confidence_state"))
    if confidence_state in {"INSUFFICIENT_SAMPLE", "UNDERPOWERED"}:
        return CausalAttributionState.UNDERPOWERED.value, f"confidence:{confidence_state}"

    if not bool(record.get("multiple_comparison_governed", False)):
        return CausalAttributionState.CAUSALLY_INCONCLUSIVE.value, "multiple_comparison_not_governed"

    if bool(record.get("counterfactual_is_synthetic", False)):
        return CausalAttributionState.CAUSALLY_INCONCLUSIVE.value, "synthetic_counterfactual"

    counterfactual_status = _safe_text(record.get("counterfactual_status"))
    if counterfactual_status == CounterfactualStatus.SYNTHETIC_OR_SIMULATED.value:
        return CausalAttributionState.CAUSALLY_INCONCLUSIVE.value, "synthetic_counterfactual"

    if not bool(record.get("counterfactual_is_observed", False)) and counterfactual_status == CounterfactualStatus.UNAVAILABLE.value:
        return CausalAttributionState.ATTRIBUTION_ELIGIBLE.value, "eligible_counterfactual_unavailable"

    if not bool(record.get("effect_size_available", False)) or not bool(record.get("uncertainty_available", False)):
        return CausalAttributionState.CAUSALLY_INCONCLUSIVE.value, "effect_or_uncertainty_unavailable"

    if record.get("treatment_effect_absolute") is None or record.get("treatment_effect_relative") is None:
        return CausalAttributionState.CAUSALLY_INCONCLUSIVE.value, "effect_values_missing"

    if confidence_state in {"DIRECTIONAL_SIGNAL", "STATISTICALLY_INCONCLUSIVE"}:
        return CausalAttributionState.CAUSALLY_INCONCLUSIVE.value, f"confidence:{confidence_state}"

    if confidence_state != "STATISTICALLY_SUPPORTED":
        return CausalAttributionState.CAUSALLY_INCONCLUSIVE.value, f"confidence:{confidence_state or 'missing'}"

    return CausalAttributionState.CAUSALLY_SUPPORTED.value, "causal_support_prerequisites_met"


def validate_causal_attribution_row(row: dict[str, Any], original_row: dict[str, Any] | None = None) -> dict[str, Any]:
    merged = _defaults()
    merged.update(dict(row))
    source_row = dict(original_row or row)

    if _safe_text(merged.get("schema_version")) != CAUSAL_ATTRIBUTION_SCHEMA_VERSION:
        raise ValueError("invalid_field:schema_version")

    for key in (
        "experiment_id",
        "experiment_version",
        "evaluation_id",
        "confidence_id",
        "decision_id",
        "learning_record_id",
        "outcome_record_id",
        "assignment_id",
        "correlation_id",
        "channel_id",
        "content_id",
        "treatment_variant",
        "control_variant",
        "treatment_assignment_ref",
        "control_assignment_ref",
        "assignment_method",
        "observation_window_type",
        "outcome_maturity_state",
        "treatment_outcome_ref",
        "control_outcome_ref",
        "confidence_state",
        "confounder_set_id",
        "counterfactual_method",
        "created_by",
        "source_module",
        "source_version",
    ):
        merged[key] = _safe_text(merged.get(key))

    merged["created_at"] = _parse_iso("created_at", merged.get("created_at"))
    merged["observation_window"] = _normalize_observation_window(merged.get("observation_window"))
    merged["treatment_exposure_refs"] = _normalize_ref_list("treatment_exposure_refs", merged.get("treatment_exposure_refs"))
    merged["control_exposure_refs"] = _normalize_ref_list("control_exposure_refs", merged.get("control_exposure_refs"))
    merged["declared_confounders"] = _normalize_string_list("declared_confounders", merged.get("declared_confounders"))
    merged["unresolved_confounders"] = _normalize_string_list("unresolved_confounders", merged.get("unresolved_confounders"))
    merged["confounder_evidence_refs"] = _normalize_ref_list("confounder_evidence_refs", merged.get("confounder_evidence_refs"))
    merged["counterfactual_evidence_refs"] = _normalize_ref_list("counterfactual_evidence_refs", merged.get("counterfactual_evidence_refs"))
    merged["invalidation_reasons"] = _normalize_string_list("invalidation_reasons", merged.get("invalidation_reasons"))

    for key in (
        "randomized_assignment_proven",
        "control_group_present",
        "treatment_group_present",
        "exposure_completeness",
        "outcome_completeness",
        "sample_sufficiency",
        "power_sufficiency",
        "multiple_comparison_governed",
        "effect_size_available",
        "uncertainty_available",
        "counterfactual_is_observed",
        "counterfactual_is_synthetic",
        "lineage_complete",
        "replay_integrity",
        "evidence_is_synthetic",
    ):
        merged[key] = _normalize_bool(key, merged.get(key))

    merged["confounder_status"] = _normalize_enum(
        "confounder_status",
        merged.get("confounder_status"),
        allowed={item.value for item in ConfounderStatus},
    )
    merged["counterfactual_status"] = _normalize_enum(
        "counterfactual_status",
        merged.get("counterfactual_status"),
        allowed={item.value for item in CounterfactualStatus},
    )

    for field in _REQUIRED_TEXT_FIELDS:
        if not _safe_text(merged.get(field)):
            raise ValueError(f"missing_field:{field}")

    merged["treatment_effect_absolute"] = _normalize_float_or_none("treatment_effect_absolute", merged.get("treatment_effect_absolute"))
    merged["treatment_effect_relative"] = _normalize_float_or_none("treatment_effect_relative", merged.get("treatment_effect_relative"))

    if not merged["declared_confounders"]:
        raise ValueError("missing_field:declared_confounders")

    derived_state, reason = classify_causal_attribution_state(merged)
    supplied_state = _safe_text(source_row.get("attribution_state"))
    if supplied_state and supplied_state != derived_state:
        raise ValueError(f"invalid_field:attribution_state:{supplied_state}->{derived_state}")
    merged["attribution_state"] = derived_state
    merged["attribution_reason"] = _safe_text(merged.get("attribution_reason")) or reason

    expected_record_id = compute_attribution_record_id(merged)
    supplied_record_id = _safe_text(source_row.get("attribution_record_id"))
    if supplied_record_id and supplied_record_id != expected_record_id:
        raise ValueError("invalid_field:attribution_record_id")
    merged["attribution_record_id"] = expected_record_id

    expected_hash = compute_record_hash(merged)
    supplied_hash = _safe_text(source_row.get("record_hash"))
    if supplied_hash and supplied_hash != expected_hash:
        raise ValueError("invalid_field:record_hash")
    merged["record_hash"] = expected_hash

    expected_event_id = compute_attribution_event_id(merged)
    supplied_event_id = _safe_text(source_row.get("attribution_event_id"))
    if supplied_event_id and supplied_event_id != expected_event_id:
        raise ValueError("invalid_field:attribution_event_id")
    merged["attribution_event_id"] = expected_event_id

    return merged


def build_causal_attribution_record(
    payload: dict[str, Any],
    *,
    created_by: str,
    source_module: str,
    source_version: str,
    created_at: str | None = None,
    previous_record_hash: str | None = None,
) -> dict[str, Any]:
    merged = _defaults()
    merged.update(dict(payload))
    merged["created_by"] = created_by
    merged["source_module"] = source_module
    merged["source_version"] = source_version
    merged["created_at"] = created_at or datetime.now(timezone.utc).isoformat()
    merged["previous_record_hash"] = previous_record_hash
    return validate_causal_attribution_row(merged, original_row=payload)
