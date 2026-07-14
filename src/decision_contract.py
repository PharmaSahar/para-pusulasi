from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any

from .evidence_reference import EvidenceAvailabilityState, EvidenceReference, build_evidence_reference, validate_evidence_reference_row


DECISION_CONTRACT_SCHEMA_VERSION = "v1"


class DecisionState(str, Enum):
    DRAFT = "draft"
    ADVISORY = "advisory"
    SHADOW = "shadow"
    REVIEW_REQUIRED = "review_required"
    APPROVED = "approved"
    REJECTED = "rejected"
    QUARANTINED = "quarantined"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"
    EXECUTED = "executed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class ExplanationBasis(str, Enum):
    DETERMINISTIC_RULE = "deterministic_rule"
    HEURISTIC = "heuristic"
    OBSERVATIONAL_EVIDENCE = "observational_evidence"
    EXPERIMENT_SUPPORTED = "experiment_supported"
    HUMAN_DECISION = "human_decision"
    UNKNOWN = "unknown"


class HumanApprovalState(str, Enum):
    UNKNOWN = "unknown"
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    QUARANTINED = "quarantined"


class EvidenceClass(str, Enum):
    UNKNOWN = "unknown"
    OBSERVATIONAL = "observational"
    EXPERIMENTAL = "experimental"
    DETERMINISTIC = "deterministic"
    HUMAN_REVIEW = "human_review"
    RUNTIME = "runtime"
    EXECUTION = "execution"
    LINEAGE = "lineage"
    DASHBOARD = "dashboard"
    FEEDBACK = "feedback"


_STATE_TRANSITIONS: dict[str, set[str]] = {
    DecisionState.DRAFT.value: {DecisionState.ADVISORY.value, DecisionState.SHADOW.value, DecisionState.REVIEW_REQUIRED.value, DecisionState.APPROVED.value, DecisionState.REJECTED.value, DecisionState.QUARANTINED.value, DecisionState.SUPERSEDED.value},
    DecisionState.ADVISORY.value: {DecisionState.SHADOW.value, DecisionState.REVIEW_REQUIRED.value, DecisionState.APPROVED.value, DecisionState.REJECTED.value, DecisionState.QUARANTINED.value, DecisionState.SUPERSEDED.value},
    DecisionState.SHADOW.value: {DecisionState.REVIEW_REQUIRED.value, DecisionState.APPROVED.value, DecisionState.REJECTED.value, DecisionState.QUARANTINED.value, DecisionState.SUPERSEDED.value},
    DecisionState.REVIEW_REQUIRED.value: {DecisionState.APPROVED.value, DecisionState.REJECTED.value, DecisionState.QUARANTINED.value},
    DecisionState.APPROVED.value: {DecisionState.EXECUTED.value, DecisionState.EXPIRED.value, DecisionState.REJECTED.value, DecisionState.QUARANTINED.value, DecisionState.SUPERSEDED.value},
    DecisionState.EXECUTED.value: {DecisionState.ROLLED_BACK.value, DecisionState.FAILED.value, DecisionState.EXPIRED.value, DecisionState.QUARANTINED.value, DecisionState.SUPERSEDED.value},
    DecisionState.FAILED.value: {DecisionState.ROLLED_BACK.value, DecisionState.QUARANTINED.value},
    DecisionState.REJECTED.value: {DecisionState.SUPERSEDED.value, DecisionState.QUARANTINED.value},
    DecisionState.QUARANTINED.value: {DecisionState.SUPERSEDED.value},
    DecisionState.EXPIRED.value: {DecisionState.SUPERSEDED.value, DecisionState.QUARANTINED.value},
    DecisionState.SUPERSEDED.value: {DecisionState.QUARANTINED.value},
    DecisionState.ROLLED_BACK.value: {DecisionState.QUARANTINED.value},
}

DECISION_RECORD_FIELD_DEFAULTS: dict[str, Any] = {
    "schema_version": DECISION_CONTRACT_SCHEMA_VERSION,
    "decision_id": "",
    "correlation_id": "",
    "decision_event_id": "",
    "parent_decision_id": None,
    "supersedes_decision_id": None,
    "channel_id": "",
    "content_id": "",
    "content_type": "",
    "decision_type": "",
    "decision_stage": "",
    "decision_timestamp": "",
    "topic_candidate_set": [],
    "selected_topic": None,
    "rejected_topic_candidates": [],
    "trend_evidence_refs": [],
    "planning_blueprint_ref": None,
    "planning_blueprint_version": None,
    "script_ref": None,
    "script_version": None,
    "thumbnail_candidates": [],
    "selected_thumbnail": None,
    "rejected_thumbnail_candidates": [],
    "analytics_evidence_refs": [],
    "cqga_evidence_refs": [],
    "experiment_assignment_refs": [],
    "channel_capability_refs": [],
    "channel_capability_version": None,
    "channel_dna_refs": [],
    "channel_dna_version": None,
    "audience_segment": None,
    "prompt_ref": None,
    "prompt_version": None,
    "model_ref": None,
    "model_provider": None,
    "model_version": None,
    "policy_ref": None,
    "policy_version": None,
    "policy_mode": None,
    "title_candidates": [],
    "selected_title": None,
    "rejected_title_candidates": [],
    "tag_set": [],
    "hashtag_set": [],
    "publish_timing_decision": None,
    "playlist_decision": None,
    "shorts_strategy": None,
    "cross_channel_reuse_decision": None,
    "upload_intent": None,
    "recommendation_confidence": None,
    "risk_score": None,
    "human_approval_state": HumanApprovalState.UNKNOWN.value,
    "reviewer_ref": None,
    "review_timestamp": None,
    "review_reason": None,
    "decision_rationale": "",
    "decision_explanation": None,
    "supporting_evidence_refs": [],
    "rejected_alternative_rationales": [],
    "expected_kpi_impact": {},
    "uncertainty_reasons": [],
    "fallback_status": None,
    "final_execution_status": None,
    "execution_evidence_refs": [],
    "observed_outcome_refs": [],
    "attribution_result_refs": [],
    "rollback_state": None,
    "rollback_reason": None,
    "record_hash": "",
    "previous_record_hash": None,
    "created_by": "",
    "created_at": "",
    "source_module": "",
    "source_version": "",
    "decision_state": DecisionState.DRAFT.value,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _decision_record_defaults() -> dict[str, Any]:
    return {
        "schema_version": DECISION_CONTRACT_SCHEMA_VERSION,
        "decision_id": "",
        "correlation_id": "",
        "decision_event_id": "",
        "parent_decision_id": None,
        "supersedes_decision_id": None,
        "channel_id": "",
        "content_id": "",
        "content_type": "",
        "decision_type": "",
        "decision_stage": "",
        "decision_timestamp": "",
        "topic_candidate_set": [],
        "selected_topic": None,
        "rejected_topic_candidates": [],
        "trend_evidence_refs": [],
        "planning_blueprint_ref": None,
        "planning_blueprint_version": None,
        "script_ref": None,
        "script_version": None,
        "thumbnail_candidates": [],
        "selected_thumbnail": None,
        "rejected_thumbnail_candidates": [],
        "analytics_evidence_refs": [],
        "cqga_evidence_refs": [],
        "experiment_assignment_refs": [],
        "channel_capability_refs": [],
        "channel_capability_version": None,
        "channel_dna_refs": [],
        "channel_dna_version": None,
        "audience_segment": None,
        "prompt_ref": None,
        "prompt_version": None,
        "model_ref": None,
        "model_provider": None,
        "model_version": None,
        "policy_ref": None,
        "policy_version": None,
        "policy_mode": None,
        "title_candidates": [],
        "selected_title": None,
        "rejected_title_candidates": [],
        "tag_set": [],
        "hashtag_set": [],
        "publish_timing_decision": None,
        "playlist_decision": None,
        "shorts_strategy": None,
        "cross_channel_reuse_decision": None,
        "upload_intent": None,
        "recommendation_confidence": None,
        "risk_score": None,
        "human_approval_state": HumanApprovalState.UNKNOWN.value,
        "reviewer_ref": None,
        "review_timestamp": None,
        "review_reason": None,
        "decision_rationale": "",
        "decision_explanation": None,
        "supporting_evidence_refs": [],
        "rejected_alternative_rationales": [],
        "expected_kpi_impact": {},
        "uncertainty_reasons": [],
        "fallback_status": None,
        "final_execution_status": None,
        "execution_evidence_refs": [],
        "observed_outcome_refs": [],
        "attribution_result_refs": [],
        "rollback_state": None,
        "rollback_reason": None,
        "record_hash": "",
        "previous_record_hash": None,
        "created_by": "",
        "created_at": "",
        "source_module": "",
        "source_version": "",
        "decision_state": DecisionState.DRAFT.value,
    }


def _normalize_structured_reference_value(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        if "evidence_type" in value:
            return validate_evidence_reference_row(dict(value))
        if {"prompt_ref", "prompt_version"}.issubset(value.keys()):
            return validate_prompt_reference_row(dict(value))
        if {"model_ref", "model_provider", "model_version"}.issubset(value.keys()):
            return validate_model_reference_row(dict(value))
        if {"policy_ref", "policy_version", "policy_mode"}.issubset(value.keys()):
            return validate_policy_reference_row(dict(value))
        return dict(value)
    if isinstance(value, EvidenceReference):
        return value.to_dict()
    if isinstance(value, PromptReference):
        return value.to_dict()
    if isinstance(value, ModelReference):
        return value.to_dict()
    if isinstance(value, PolicyReference):
        return value.to_dict()
    raise ValueError("invalid_field:structured_reference")


def _normalize_decision_explanation_value(value: Any) -> dict[str, Any]:
    if value is None:
        return DecisionExplanation(
            summary="unknown",
            selected_candidate_reason="unknown",
            rejected_candidate_reasons=tuple(),
            supporting_evidence_refs=tuple(),
            expected_kpi_impact={},
            confidence=None,
            uncertainty_reasons=tuple(),
            fallback_reason=None,
            risk_factors=tuple(),
            human_review_requirement=False,
            evidence_basis=ExplanationBasis.UNKNOWN.value,
            evidence_class=EvidenceClass.UNKNOWN,
            decision_basis=ExplanationBasis.UNKNOWN,
        ).to_dict()
    if isinstance(value, DecisionExplanation):
        return value.to_dict()
    if isinstance(value, dict):
        return validate_decision_explanation_row(dict(value))
    raise ValueError("invalid_field:decision_explanation")


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _sha(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def _normalize_list(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return tuple(_safe_text(item) for item in value if _safe_text(item))
    if isinstance(value, list):
        return tuple(_safe_text(item) for item in value if _safe_text(item))
    if isinstance(value, set):
        return tuple(sorted(_safe_text(item) for item in value if _safe_text(item)))
    if _safe_text(value):
        return (_safe_text(value),)
    return ()


def _normalize_timestamp(name: str, value: Any, *, allow_empty: bool = False) -> str | None:
    text = _safe_text(value)
    if not text:
        if allow_empty:
            return None
        raise ValueError(f"missing_field:{name}")
    datetime.fromisoformat(text.replace("Z", "+00:00"))
    return text


def _normalize_float(name: str, value: Any, *, allow_none: bool = False) -> float | None:
    if value is None:
        if allow_none:
            return None
        raise ValueError(f"missing_field:{name}")
    try:
        number = float(value)
    except Exception as exc:
        raise ValueError(f"invalid_field:{name}") from exc
    return number


def _normalize_bool(name: str, value: Any, *, allow_none: bool = False) -> bool | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool):
        return value
    text = _safe_text(value).lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    if allow_none and not text:
        return None
    raise ValueError(f"invalid_field:{name}")


def _normalize_enum(name: str, value: Any, enum_cls: type[Enum]) -> str:
    if isinstance(value, enum_cls):
        return value.value  # type: ignore[return-value]
    text = _safe_text(value)
    try:
        return enum_cls(text).value  # type: ignore[arg-type]
    except Exception as exc:
        raise ValueError(f"invalid_field:{name}") from exc


def _normalize_optional_enum(name: str, value: Any, enum_cls: type[Enum], *, default: str) -> str:
    if isinstance(value, enum_cls):
        return value.value  # type: ignore[return-value]
    text = _safe_text(value)
    if not text:
        return default
    try:
        return enum_cls(text).value  # type: ignore[arg-type]
    except Exception as exc:
        raise ValueError(f"invalid_field:{name}") from exc


def _normalize_reference_dict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, EvidenceReference):
        return value.to_dict()
    if isinstance(value, dict):
        return validate_evidence_reference_row(dict(value))
    raise ValueError("invalid_field:evidence_reference")


def _normalize_reference_list(value: Any) -> tuple[dict[str, Any], ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError("invalid_field:evidence_reference_list")
    refs: list[dict[str, Any]] = []
    for item in value:
        normalized = _normalize_reference_dict(item)
        if normalized is not None:
            refs.append(normalized)
    return tuple(refs)


def _normalize_prompt_reference(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, PromptReference):
        return value.to_dict()
    if isinstance(value, dict):
        return validate_prompt_reference_row(dict(value))
    raise ValueError("invalid_field:prompt_reference")


def _normalize_model_reference(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, ModelReference):
        return value.to_dict()
    if isinstance(value, dict):
        return validate_model_reference_row(dict(value))
    raise ValueError("invalid_field:model_reference")


def _normalize_policy_reference(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, PolicyReference):
        return value.to_dict()
    if isinstance(value, dict):
        return validate_policy_reference_row(dict(value))
    raise ValueError("invalid_field:policy_reference")


@dataclass(frozen=True, slots=True)
class PromptReference:
    prompt_ref: str
    prompt_version: str
    source_module: str | None = None

    def __post_init__(self) -> None:
        validate_prompt_reference_row(asdict(self))

    def to_dict(self) -> dict[str, Any]:
        return validate_prompt_reference_row(asdict(self))


@dataclass(frozen=True, slots=True)
class ModelReference:
    model_ref: str
    model_provider: str
    model_version: str

    def __post_init__(self) -> None:
        validate_model_reference_row(asdict(self))

    def to_dict(self) -> dict[str, Any]:
        return validate_model_reference_row(asdict(self))


@dataclass(frozen=True, slots=True)
class PolicyReference:
    policy_ref: str
    policy_version: str
    policy_mode: str

    def __post_init__(self) -> None:
        validate_policy_reference_row(asdict(self))

    def to_dict(self) -> dict[str, Any]:
        return validate_policy_reference_row(asdict(self))


@dataclass(frozen=True, slots=True)
class DecisionExplanation:
    summary: str
    selected_candidate_reason: str
    rejected_candidate_reasons: tuple[str, ...] = ()
    supporting_evidence_refs: tuple[dict[str, Any], ...] = ()
    expected_kpi_impact: dict[str, Any] = field(default_factory=dict)
    confidence: float | None = None
    uncertainty_reasons: tuple[str, ...] = ()
    fallback_reason: str | None = None
    risk_factors: tuple[str, ...] = ()
    human_review_requirement: bool = False
    evidence_basis: str = ExplanationBasis.UNKNOWN.value
    evidence_class: EvidenceClass = EvidenceClass.UNKNOWN
    decision_basis: ExplanationBasis = ExplanationBasis.UNKNOWN

    def __post_init__(self) -> None:
        validate_decision_explanation_row(asdict(self))

    def to_dict(self) -> dict[str, Any]:
        return validate_decision_explanation_row(asdict(self))


def validate_prompt_reference_row(row: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ValueError("invalid_payload")
    prompt_ref = _safe_text(row.get("prompt_ref"))
    prompt_version = _safe_text(row.get("prompt_version"))
    if not prompt_ref:
        raise ValueError("missing_field:prompt_ref")
    if not prompt_version:
        raise ValueError("missing_field:prompt_version")
    return {
        "prompt_ref": prompt_ref,
        "prompt_version": prompt_version,
        "source_module": _safe_text(row.get("source_module")) or None,
    }


def validate_model_reference_row(row: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ValueError("invalid_payload")
    model_ref = _safe_text(row.get("model_ref"))
    model_provider = _safe_text(row.get("model_provider"))
    model_version = _safe_text(row.get("model_version"))
    if not model_ref:
        raise ValueError("missing_field:model_ref")
    if not model_provider:
        raise ValueError("missing_field:model_provider")
    if not model_version:
        raise ValueError("missing_field:model_version")
    return {
        "model_ref": model_ref,
        "model_provider": model_provider,
        "model_version": model_version,
    }


def validate_policy_reference_row(row: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ValueError("invalid_payload")
    policy_ref = _safe_text(row.get("policy_ref"))
    policy_version = _safe_text(row.get("policy_version"))
    policy_mode = _safe_text(row.get("policy_mode"))
    if not policy_ref:
        raise ValueError("missing_field:policy_ref")
    if not policy_version:
        raise ValueError("missing_field:policy_version")
    if not policy_mode:
        raise ValueError("missing_field:policy_mode")
    return {
        "policy_ref": policy_ref,
        "policy_version": policy_version,
        "policy_mode": policy_mode,
    }


def validate_decision_explanation_row(row: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ValueError("invalid_payload")

    summary = _safe_text(row.get("summary"))
    selected_candidate_reason = _safe_text(row.get("selected_candidate_reason"))
    if not summary:
        raise ValueError("missing_field:summary")
    if not selected_candidate_reason:
        raise ValueError("missing_field:selected_candidate_reason")

    evidence_basis = _normalize_optional_enum(
        "evidence_basis",
        row.get("evidence_basis") if row.get("evidence_basis") is not None else row.get("decision_basis"),
        ExplanationBasis,
        default=ExplanationBasis.UNKNOWN.value,
    )
    basis = _normalize_optional_enum(
        "decision_basis",
        row.get("decision_basis"),
        ExplanationBasis,
        default=evidence_basis,
    )
    if evidence_basis != basis:
        raise ValueError("conflicting_field:evidence_basis")
    evidence_class = _normalize_optional_enum(
        "evidence_class",
        row.get("evidence_class"),
        EvidenceClass,
        default=EvidenceClass.UNKNOWN.value,
    )
    confidence = _normalize_float("confidence", row.get("confidence"), allow_none=True)
    human_review_requirement = _normalize_bool("human_review_requirement", row.get("human_review_requirement"), allow_none=False)

    expected_kpi_impact = row.get("expected_kpi_impact")
    if expected_kpi_impact is None:
        expected_kpi_impact = {}
    if not isinstance(expected_kpi_impact, dict):
        raise ValueError("invalid_field:expected_kpi_impact")

    supporting_refs: list[dict[str, Any]] = []
    for ref in list(row.get("supporting_evidence_refs") or []):
        normalized_ref = _normalize_reference_dict(ref)
        if normalized_ref is not None:
            supporting_refs.append(normalized_ref)

    normalized = {
        "summary": summary,
        "selected_candidate_reason": selected_candidate_reason,
        "rejected_candidate_reasons": list(_normalize_list(row.get("rejected_candidate_reasons"))),
        "supporting_evidence_refs": supporting_refs,
        "expected_kpi_impact": dict(expected_kpi_impact),
        "confidence": confidence,
        "uncertainty_reasons": list(_normalize_list(row.get("uncertainty_reasons"))),
        "fallback_reason": _safe_text(row.get("fallback_reason")) or None,
        "risk_factors": list(_normalize_list(row.get("risk_factors"))),
        "human_review_requirement": bool(human_review_requirement),
        "evidence_basis": evidence_basis,
        "evidence_class": evidence_class,
        "decision_basis": basis,
    }
    return normalized


def _decision_identity_seed(record: dict[str, Any]) -> str:
    return "|".join(
        [
            _safe_text(record.get("correlation_id")),
            _safe_text(record.get("channel_id")),
            _safe_text(record.get("content_id")),
            _safe_text(record.get("decision_type")),
            _safe_text(record.get("decision_stage")),
        ]
    )


def compute_decision_id(record: dict[str, Any]) -> str:
    return "dcn_" + _sha(_decision_identity_seed(record))[:24]


def _stable_hash_payload(record: dict[str, Any]) -> dict[str, Any]:
    payload = dict(record)
    payload.pop("record_hash", None)
    payload.pop("decision_event_id", None)
    payload.pop("created_at", None)
    return payload


def compute_record_hash(record: dict[str, Any]) -> str:
    return "rkh_" + _sha(_stable_json(_stable_hash_payload(record)))[:24]


def compute_decision_event_id(record: dict[str, Any]) -> str:
    payload = "|".join([
        _safe_text(record.get("decision_id")),
        _safe_text(record.get("decision_state")),
        _safe_text(record.get("record_hash")),
    ])
    return "dev_" + _sha(payload)[:24]


def validate_decision_state_transition(previous_state: str, next_state: str) -> bool:
    prev = _safe_text(previous_state)
    nxt = _safe_text(next_state)
    if not prev or not nxt:
        raise ValueError("missing_field:decision_state")
    if prev not in _STATE_TRANSITIONS:
        raise ValueError("invalid_field:previous_decision_state")
    try:
        DecisionState(nxt)
    except Exception as exc:
        raise ValueError("invalid_field:decision_state") from exc
    return nxt in _STATE_TRANSITIONS.get(prev, set())


def is_terminal_state(state: str) -> bool:
    return _safe_text(state) in {
        DecisionState.REJECTED.value,
        DecisionState.QUARANTINED.value,
        DecisionState.EXPIRED.value,
        DecisionState.SUPERSEDED.value,
        DecisionState.FAILED.value,
        DecisionState.ROLLED_BACK.value,
    }


def canonicalize_decision_record_row(row: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ValueError("invalid_payload")
    missing_fields = [field_name for field_name in _decision_record_defaults().keys() if field_name not in row]
    if missing_fields:
        raise ValueError(f"missing_field:{missing_fields[0]}")

    normalized = _decision_record_defaults()
    normalized.update(row)

    if _safe_text(normalized.get("schema_version")) != DECISION_CONTRACT_SCHEMA_VERSION:
        raise ValueError("invalid_field:schema_version")

    for key in [
        "correlation_id",
        "channel_id",
        "content_id",
        "content_type",
        "decision_type",
        "decision_stage",
        "created_by",
        "source_module",
        "source_version",
        "decision_timestamp",
        "created_at",
    ]:
        value = _safe_text(normalized.get(key))
        if not value:
            raise ValueError(f"missing_field:{key}")
        normalized[key] = value

    normalized["decision_id"] = _safe_text(normalized.get("decision_id")) or compute_decision_id(normalized)

    for key in [
        "parent_decision_id",
        "supersedes_decision_id",
        "selected_topic",
        "audience_segment",
        "channel_dna_version",
        "channel_capability_version",
        "planning_blueprint_version",
        "prompt_version",
        "model_provider",
        "model_version",
        "script_version",
        "selected_title",
        "selected_thumbnail",
        "description_version",
        "publish_timing_decision",
        "playlist_decision",
        "shorts_strategy",
        "cross_channel_reuse_decision",
        "reviewer_ref",
        "review_reason",
        "rollback_reason",
        "fallback_status",
        "final_execution_status",
        "rollback_state",
        "previous_record_hash",
    ]:
        normalized[key] = _safe_text(normalized.get(key)) or None

    normalized["created_at"] = _normalize_timestamp("created_at", normalized.get("created_at"), allow_empty=False)
    normalized["decision_timestamp"] = _normalize_timestamp("decision_timestamp", normalized.get("decision_timestamp"), allow_empty=False)
    normalized["review_timestamp"] = _normalize_timestamp("review_timestamp", normalized.get("review_timestamp"), allow_empty=True)

    normalized["decision_state"] = _normalize_enum("decision_state", normalized.get("decision_state"), DecisionState)
    normalized["human_approval_state"] = _normalize_optional_enum("human_approval_state", normalized.get("human_approval_state"), HumanApprovalState, default=HumanApprovalState.UNKNOWN.value)

    for key in [
        "topic_candidate_set",
        "rejected_topic_candidates",
        "title_candidates",
        "rejected_title_candidates",
        "thumbnail_candidates",
        "rejected_thumbnail_candidates",
        "tag_set",
        "hashtag_set",
        "rejected_alternative_rationales",
        "uncertainty_reasons",
    ]:
        normalized[key] = list(_normalize_list(normalized.get(key)))

    for key in [
        "trend_evidence_refs",
        "analytics_evidence_refs",
        "cqga_evidence_refs",
        "experiment_assignment_refs",
        "channel_capability_refs",
        "channel_dna_refs",
        "supporting_evidence_refs",
        "execution_evidence_refs",
        "observed_outcome_refs",
        "attribution_result_refs",
    ]:
        normalized[key] = list(_normalize_reference_list(normalized.get(key)))

    normalized["planning_blueprint_ref"] = _normalize_structured_reference_value(normalized.get("planning_blueprint_ref"))
    normalized["script_ref"] = _normalize_structured_reference_value(normalized.get("script_ref"))
    normalized["prompt_ref"] = _normalize_structured_reference_value(normalized.get("prompt_ref"))
    normalized["model_ref"] = _normalize_structured_reference_value(normalized.get("model_ref"))
    normalized["policy_ref"] = _normalize_structured_reference_value(normalized.get("policy_ref"))

    if normalized["topic_candidate_set"] and normalized["selected_topic"] and normalized["selected_topic"] not in normalized["topic_candidate_set"]:
        raise ValueError("invalid_field:selected_topic_not_in_candidates")
    if normalized["title_candidates"] and normalized["selected_title"] and normalized["selected_title"] not in normalized["title_candidates"]:
        raise ValueError("invalid_field:selected_title_not_in_candidates")
    if normalized["thumbnail_candidates"] and normalized["selected_thumbnail"] and normalized["selected_thumbnail"] not in normalized["thumbnail_candidates"]:
        raise ValueError("invalid_field:selected_thumbnail_not_in_candidates")

    for key in ["recommendation_confidence", "risk_score"]:
        value = normalized.get(key)
        if value is not None:
            normalized[key] = _normalize_float(key, value)
            if normalized[key] is not None and not 0.0 <= normalized[key] <= 1.0:
                raise ValueError(f"invalid_field:{key}_range")

    normalized["upload_intent"] = _normalize_bool("upload_intent", normalized.get("upload_intent"), allow_none=True)

    expected_kpi_impact = normalized.get("expected_kpi_impact")
    if expected_kpi_impact is None:
        expected_kpi_impact = {}
    if not isinstance(expected_kpi_impact, dict):
        raise ValueError("invalid_field:expected_kpi_impact")
    normalized["expected_kpi_impact"] = dict(expected_kpi_impact)

    normalized["decision_explanation"] = _normalize_decision_explanation_value(normalized.get("decision_explanation"))

    normalized["decision_rationale"] = _safe_text(normalized.get("decision_rationale")) or normalized["decision_explanation"]["summary"]

    hash_ready = dict(normalized)
    hash_ready["decision_explanation"] = _normalize_decision_explanation_value(hash_ready.get("decision_explanation"))
    for key in [
        "planning_blueprint_ref",
        "script_ref",
        "prompt_ref",
        "model_ref",
        "policy_ref",
    ]:
        hash_ready[key] = _normalize_structured_reference_value(hash_ready.get(key))
    expected_record_hash = compute_record_hash(hash_ready)
    normalized["record_hash"] = expected_record_hash

    expected_event_id = compute_decision_event_id(normalized)
    normalized["decision_event_id"] = expected_event_id

    if normalized["decision_state"] not in {state.value for state in DecisionState}:
        raise ValueError("invalid_field:decision_state")
    if normalized["human_approval_state"] not in {state.value for state in HumanApprovalState}:
        raise ValueError("invalid_field:human_approval_state")

    return normalized


def validate_decision_record_row(row: dict[str, Any]) -> dict[str, Any]:
    return canonicalize_decision_record_row(row)


def build_decision_record(
    payload: dict[str, Any],
    *,
    created_by: str,
    source_module: str,
    source_version: str,
    created_at: str | None = None,
    decision_timestamp: str | None = None,
    decision_state: str | DecisionState | None = None,
    previous_record_hash: str | None = None,
) -> dict[str, Any]:
    base = _decision_record_defaults()
    base.update(dict(payload or {}))
    supplied_decision_id = _safe_text(base.get("decision_id"))
    if decision_state is not None:
        base["decision_state"] = decision_state.value if isinstance(decision_state, DecisionState) else str(decision_state)
    base.setdefault("decision_state", DecisionState.DRAFT.value)
    base["created_by"] = _safe_text(created_by)
    base["source_module"] = _safe_text(source_module)
    base["source_version"] = _safe_text(source_version)
    base["created_at"] = _safe_text(created_at) or _now_iso()
    if decision_timestamp is not None:
        base["decision_timestamp"] = _safe_text(decision_timestamp)
    if not _safe_text(base.get("decision_timestamp")):
        base["decision_timestamp"] = base["created_at"]
    base["schema_version"] = DECISION_CONTRACT_SCHEMA_VERSION

    if not _safe_text(base.get("correlation_id")):
        raise ValueError("missing_field:correlation_id")
    if not _safe_text(base.get("channel_id")):
        raise ValueError("missing_field:channel_id")
    if not _safe_text(base.get("content_id")):
        raise ValueError("missing_field:content_id")
    if not _safe_text(base.get("content_type")):
        raise ValueError("missing_field:content_type")
    if not _safe_text(base.get("decision_type")):
        raise ValueError("missing_field:decision_type")
    if not _safe_text(base.get("decision_stage")):
        raise ValueError("missing_field:decision_stage")
    base["previous_record_hash"] = _safe_text(previous_record_hash) or _safe_text(base.get("previous_record_hash")) or None

    canonical = canonicalize_decision_record_row(base)
    if supplied_decision_id and supplied_decision_id != canonical["decision_id"]:
        raise ValueError("conflicting_field:decision_id")
    return canonical


def decision_transition_is_valid(previous_state: str, next_state: str) -> bool:
    prev = _safe_text(previous_state)
    nxt = _safe_text(next_state)
    if prev not in _STATE_TRANSITIONS:
        return False
    return nxt in _STATE_TRANSITIONS.get(prev, set())
