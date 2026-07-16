from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any


RECOMMENDATION_EVALUATION_SCHEMA_VERSION = "v1"
RECOMMENDATION_SCHEMA_VERSION = "v1"


class RecommendationEvaluationState(str, Enum):
    PENDING = "pending"
    ELIGIBLE = "eligible"
    BLOCKED = "blocked"
    ADVISORY_PASS = "advisory_pass"
    ADVISORY_FAIL = "advisory_fail"


class RecommendationAdvisoryResult(str, Enum):
    NONE = "none"
    PASS = "pass"
    FAIL = "fail"


_RUNTIME_ACTION_FIELDS = {
    "execute",
    "apply",
    "publish",
    "upload",
    "schedule",
    "mutate",
    "update_metadata",
    "change_thumbnail",
    "change_title",
    "activate",
    "deploy",
    "restart",
    "rollback",
    "quarantine_clear",
}

_REQUIRED_TEXT_FIELDS = (
    "evaluation_schema_version",
    "recommendation_id",
    "recommendation_schema_version",
    "created_at",
    "evaluator_version",
    "decision_id",
    "learning_record_id",
    "outcome_record_id",
    "confidence_id",
    "attribution_record_id",
    "policy_id",
    "model_id",
    "prompt_id",
    "confidence_state",
    "attribution_state",
)

_BLOCKED_PRECEDENCE = (
    "invalid_schema_version",
    "missing_required_reference",
    "missing_policy_lineage",
    "missing_confidence_evidence",
    "missing_attribution_evidence",
    "synthetic_evidence",
    "contaminated_evidence",
    "immature_evidence",
    "unresolved_evidence",
    "incomplete_lineage",
    "policy_blocked",
    "confidence_not_supported",
    "attribution_not_supported",
)

_REASON_RANK = {reason: index for index, reason in enumerate(_BLOCKED_PRECEDENCE)}


@dataclass(frozen=True, slots=True)
class RecommendationEvaluationRecord:
    evaluation_schema_version: str
    evaluation_id: str
    recommendation_id: str
    recommendation_schema_version: str
    created_at: str
    evaluator_version: str
    decision_id: str
    learning_record_id: str
    outcome_record_id: str
    confidence_id: str
    attribution_record_id: str
    experiment_id: str | None
    lifecycle_id: str | None
    policy_id: str
    model_id: str
    prompt_id: str
    evaluation_state: str
    advisory_result: str
    blocking_reasons: tuple[str, ...]
    evidence_summary: dict[str, Any]
    confidence_state: str
    attribution_state: str
    lineage_complete: bool
    human_review_required: bool
    input_fingerprint: str
    evaluation_fingerprint: str
    deterministic_identity: str

    def __post_init__(self) -> None:
        validate_recommendation_evaluation_row(asdict(self))

    def to_dict(self) -> dict[str, Any]:
        return validate_recommendation_evaluation_row(asdict(self))


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


def _validate_evidence_summary(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("invalid_field:evidence_summary")
    payload = json.loads(_stable_json(value))

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, item in node.items():
                key_lower = _safe_text(key).lower()
                if key_lower in _RUNTIME_ACTION_FIELDS:
                    raise ValueError(f"invalid_field:evidence_summary.runtime_action_key:{key_lower}")
                if key_lower in {"action", "command", "operation", "step"}:
                    action_value = _safe_text(item).lower()
                    if action_value in _RUNTIME_ACTION_FIELDS:
                        raise ValueError(
                            f"invalid_field:evidence_summary.runtime_action_value:{action_value}"
                        )
                _walk(item)
            return
        if isinstance(node, list):
            for item in node:
                _walk(item)
            return
        if isinstance(node, str) and _safe_text(node).lower() in _RUNTIME_ACTION_FIELDS:
            raise ValueError(f"invalid_field:evidence_summary.runtime_action_value:{_safe_text(node).lower()}")

    _walk(payload)
    return payload


def _defaults() -> dict[str, Any]:
    return {
        "evaluation_schema_version": RECOMMENDATION_EVALUATION_SCHEMA_VERSION,
        "evaluation_id": "",
        "recommendation_id": "",
        "recommendation_schema_version": RECOMMENDATION_SCHEMA_VERSION,
        "created_at": "",
        "evaluator_version": "",
        "decision_id": "",
        "learning_record_id": "",
        "outcome_record_id": "",
        "confidence_id": "",
        "attribution_record_id": "",
        "experiment_id": None,
        "lifecycle_id": None,
        "policy_id": "",
        "model_id": "",
        "prompt_id": "",
        "evaluation_state": RecommendationEvaluationState.PENDING.value,
        "advisory_result": RecommendationAdvisoryResult.NONE.value,
        "blocking_reasons": (),
        "evidence_summary": {},
        "confidence_state": "",
        "attribution_state": "",
        "lineage_complete": False,
        "human_review_required": True,
        "input_fingerprint": "",
        "evaluation_fingerprint": "",
        "deterministic_identity": "",
    }


def _normalize_optional_text(value: Any) -> str | None:
    text = _safe_text(value)
    return text or None


def _normalize_blocking_reasons(value: Any) -> tuple[str, ...]:
    reasons = _normalize_string_list("blocking_reasons", value)
    deduped = sorted(set(reasons), key=lambda item: (_REASON_RANK.get(item, len(_REASON_RANK)), item))
    return tuple(deduped)


def compute_input_fingerprint(record: dict[str, Any]) -> str:
    payload = {
        "recommendation_id": _safe_text(record.get("recommendation_id")),
        "recommendation_schema_version": _safe_text(record.get("recommendation_schema_version")),
        "decision_id": _safe_text(record.get("decision_id")),
        "learning_record_id": _safe_text(record.get("learning_record_id")),
        "outcome_record_id": _safe_text(record.get("outcome_record_id")),
        "confidence_id": _safe_text(record.get("confidence_id")),
        "attribution_record_id": _safe_text(record.get("attribution_record_id")),
        "experiment_id": _safe_text(record.get("experiment_id")),
        "lifecycle_id": _safe_text(record.get("lifecycle_id")),
        "policy_id": _safe_text(record.get("policy_id")),
        "model_id": _safe_text(record.get("model_id")),
        "prompt_id": _safe_text(record.get("prompt_id")),
        "confidence_state": _safe_text(record.get("confidence_state")),
        "attribution_state": _safe_text(record.get("attribution_state")),
        "lineage_complete": bool(record.get("lineage_complete", False)),
        "evidence_summary": record.get("evidence_summary") or {},
    }
    return "reif_" + _sha(_stable_json(payload))[:24]


def compute_evaluation_fingerprint(record: dict[str, Any]) -> str:
    payload = {
        "evaluation_state": _safe_text(record.get("evaluation_state")),
        "advisory_result": _safe_text(record.get("advisory_result")),
        "blocking_reasons": tuple(record.get("blocking_reasons") or ()),
        "confidence_state": _safe_text(record.get("confidence_state")),
        "attribution_state": _safe_text(record.get("attribution_state")),
        "lineage_complete": bool(record.get("lineage_complete", False)),
        "human_review_required": bool(record.get("human_review_required", False)),
    }
    return "reef_" + _sha(_stable_json(payload))[:24]


def compute_deterministic_identity(record: dict[str, Any]) -> str:
    payload = {
        "recommendation_id": _safe_text(record.get("recommendation_id")),
        "recommendation_schema_version": _safe_text(record.get("recommendation_schema_version")),
        "input_fingerprint": _safe_text(record.get("input_fingerprint")),
    }
    return "redi_" + _sha(_stable_json(payload))[:24]


def compute_evaluation_id(record: dict[str, Any]) -> str:
    payload = {
        "deterministic_identity": _safe_text(record.get("deterministic_identity")),
        "evaluation_schema_version": _safe_text(record.get("evaluation_schema_version")),
    }
    return "reid_" + _sha(_stable_json(payload))[:24]


def _derive_blocking_reasons(record: dict[str, Any]) -> tuple[str, ...]:
    reasons: list[str] = []
    for field in (
        "recommendation_id",
        "decision_id",
        "learning_record_id",
        "outcome_record_id",
        "confidence_id",
        "attribution_record_id",
        "policy_id",
        "model_id",
        "prompt_id",
    ):
        if not _safe_text(record.get(field)):
            reasons.append("missing_required_reference")
            break

    if not _safe_text(record.get("policy_id")):
        reasons.append("missing_policy_lineage")
    if not _safe_text(record.get("confidence_id")):
        reasons.append("missing_confidence_evidence")
    if not _safe_text(record.get("attribution_record_id")):
        reasons.append("missing_attribution_evidence")

    evidence_summary = record.get("evidence_summary") or {}
    if bool(evidence_summary.get("synthetic_evidence", False)):
        reasons.append("synthetic_evidence")
    if str(evidence_summary.get("contamination_state") or "").strip().upper() not in {"", "NONE"}:
        reasons.append("contaminated_evidence")
    maturity_state = str(evidence_summary.get("outcome_maturity_state") or "").strip().lower()
    if maturity_state in {"", "unknown", "immature", "partially_observed"}:
        reasons.append("immature_evidence")
    if bool(evidence_summary.get("unresolved_evidence", False)):
        reasons.append("unresolved_evidence")

    if not bool(record.get("lineage_complete", False)):
        reasons.append("incomplete_lineage")

    policy_state = str(evidence_summary.get("policy_state") or "ALLOW").strip().upper()
    if policy_state in {"BLOCKED", "DENY"}:
        reasons.append("policy_blocked")

    confidence_state = _safe_text(record.get("confidence_state")).upper()
    if confidence_state in {"", "UNKNOWN", "MISSING", "NOT_ASSESSED", "INSUFFICIENT_SAMPLE", "IMMATURE_WINDOW", "CONTAMINATED", "UNDERPOWERED"}:
        reasons.append("confidence_not_supported")

    attribution_state = _safe_text(record.get("attribution_state")).upper()
    if attribution_state in {"", "UNKNOWN", "MISSING", "NOT_ATTRIBUTABLE", "INSUFFICIENT_LINEAGE", "INSUFFICIENT_CONTROL", "IMMATURE_OUTCOME", "CONTAMINATED", "CONFOUNDED", "UNDERPOWERED", "ASSOCIATIONAL_ONLY", "ATTRIBUTION_ELIGIBLE"}:
        reasons.append("attribution_not_supported")

    return _normalize_blocking_reasons(reasons)


def classify_recommendation_evaluation(record: dict[str, Any]) -> tuple[str, str, tuple[str, ...]]:
    blocking_reasons = _derive_blocking_reasons(record)
    if blocking_reasons:
        return (
            RecommendationEvaluationState.BLOCKED.value,
            RecommendationAdvisoryResult.NONE.value,
            blocking_reasons,
        )

    evidence_summary = record.get("evidence_summary") or {}
    recommendation_eligible = bool(evidence_summary.get("recommendation_eligible", True))
    if not recommendation_eligible:
        return (
            RecommendationEvaluationState.ADVISORY_FAIL.value,
            RecommendationAdvisoryResult.FAIL.value,
            (),
        )

    if _safe_text(record.get("confidence_state")).upper() == "STATISTICALLY_SUPPORTED" and _safe_text(record.get("attribution_state")).upper() == "CAUSALLY_SUPPORTED":
        return (
            RecommendationEvaluationState.ADVISORY_PASS.value,
            RecommendationAdvisoryResult.PASS.value,
            (),
        )

    return (
        RecommendationEvaluationState.ELIGIBLE.value,
        RecommendationAdvisoryResult.NONE.value,
        (),
    )


def validate_recommendation_evaluation_row(row: dict[str, Any], original_row: dict[str, Any] | None = None) -> dict[str, Any]:
    merged = _defaults()
    merged.update(dict(row))
    source_row = dict(original_row or row)

    if _safe_text(merged.get("evaluation_schema_version")) != RECOMMENDATION_EVALUATION_SCHEMA_VERSION:
        raise ValueError("invalid_field:evaluation_schema_version")
    if _safe_text(merged.get("recommendation_schema_version")) != RECOMMENDATION_SCHEMA_VERSION:
        raise ValueError("invalid_field:recommendation_schema_version")

    merged["created_at"] = _parse_iso("created_at", merged.get("created_at"))
    merged["experiment_id"] = _normalize_optional_text(merged.get("experiment_id"))
    merged["lifecycle_id"] = _normalize_optional_text(merged.get("lifecycle_id"))
    merged["evidence_summary"] = _validate_evidence_summary(merged.get("evidence_summary"))
    merged["lineage_complete"] = _normalize_bool("lineage_complete", merged.get("lineage_complete"))
    merged["human_review_required"] = _normalize_bool("human_review_required", merged.get("human_review_required"))
    if merged["human_review_required"] is not True:
        raise ValueError("invalid_field:human_review_required")

    for field in _REQUIRED_TEXT_FIELDS:
        if not _safe_text(merged.get(field)):
            raise ValueError(f"missing_field:{field}")

    merged["blocking_reasons"] = _normalize_blocking_reasons(merged.get("blocking_reasons"))

    allowed_states = {item.value for item in RecommendationEvaluationState}
    allowed_results = {item.value for item in RecommendationAdvisoryResult}
    supplied_state = _safe_text(merged.get("evaluation_state")) or RecommendationEvaluationState.PENDING.value
    supplied_result = _safe_text(merged.get("advisory_result")) or RecommendationAdvisoryResult.NONE.value
    if supplied_state not in allowed_states:
        raise ValueError("invalid_field:evaluation_state")
    if supplied_result not in allowed_results:
        raise ValueError("invalid_field:advisory_result")

    derived_state, derived_result, derived_blocking_reasons = classify_recommendation_evaluation(merged)
    if supplied_state not in {RecommendationEvaluationState.PENDING.value, derived_state}:
        raise ValueError(f"invalid_field:evaluation_state:{supplied_state}->{derived_state}")
    if supplied_result not in {RecommendationAdvisoryResult.NONE.value, derived_result}:
        raise ValueError(f"invalid_field:advisory_result:{supplied_result}->{derived_result}")

    if merged["blocking_reasons"] and merged["blocking_reasons"] != derived_blocking_reasons:
        raise ValueError("invalid_field:blocking_reasons")

    merged["evaluation_state"] = derived_state
    merged["advisory_result"] = derived_result
    merged["blocking_reasons"] = derived_blocking_reasons

    if derived_state == RecommendationEvaluationState.BLOCKED.value and not merged["blocking_reasons"]:
        raise ValueError("invalid_field:blocking_reasons")
    if derived_state == RecommendationEvaluationState.ADVISORY_PASS.value and merged["blocking_reasons"]:
        raise ValueError("invalid_field:blocking_reasons")
    if derived_state == RecommendationEvaluationState.ADVISORY_PASS.value and not merged["lineage_complete"]:
        raise ValueError("invalid_field:lineage_complete")
    if derived_state == RecommendationEvaluationState.ADVISORY_PASS.value and derived_result != RecommendationAdvisoryResult.PASS.value:
        raise ValueError("invalid_field:advisory_result")
    if derived_state == RecommendationEvaluationState.ADVISORY_FAIL.value and derived_result != RecommendationAdvisoryResult.FAIL.value:
        raise ValueError("invalid_field:advisory_result")
    if derived_state in {RecommendationEvaluationState.PENDING.value, RecommendationEvaluationState.ELIGIBLE.value} and derived_result != RecommendationAdvisoryResult.NONE.value:
        raise ValueError("invalid_field:advisory_result")

    expected_input_fingerprint = compute_input_fingerprint(merged)
    supplied_input_fingerprint = _safe_text(source_row.get("input_fingerprint"))
    if supplied_input_fingerprint and supplied_input_fingerprint != expected_input_fingerprint:
        raise ValueError("invalid_field:input_fingerprint")
    merged["input_fingerprint"] = expected_input_fingerprint

    expected_evaluation_fingerprint = compute_evaluation_fingerprint(merged)
    supplied_evaluation_fingerprint = _safe_text(source_row.get("evaluation_fingerprint"))
    if supplied_evaluation_fingerprint and supplied_evaluation_fingerprint != expected_evaluation_fingerprint:
        raise ValueError("invalid_field:evaluation_fingerprint")
    merged["evaluation_fingerprint"] = expected_evaluation_fingerprint

    expected_deterministic_identity = compute_deterministic_identity(merged)
    supplied_deterministic_identity = _safe_text(source_row.get("deterministic_identity"))
    if supplied_deterministic_identity and supplied_deterministic_identity != expected_deterministic_identity:
        raise ValueError("invalid_field:deterministic_identity")
    merged["deterministic_identity"] = expected_deterministic_identity

    expected_evaluation_id = compute_evaluation_id(merged)
    supplied_evaluation_id = _safe_text(source_row.get("evaluation_id"))
    if supplied_evaluation_id and supplied_evaluation_id != expected_evaluation_id:
        raise ValueError("invalid_field:evaluation_id")
    merged["evaluation_id"] = expected_evaluation_id

    return merged


def build_recommendation_evaluation_record(
    payload: dict[str, Any],
    *,
    evaluator_version: str,
    created_at: str | None = None,
) -> dict[str, Any]:
    merged = _defaults()
    merged.update(dict(payload))
    merged["evaluator_version"] = evaluator_version
    merged["created_at"] = created_at or datetime.now(timezone.utc).isoformat()
    return validate_recommendation_evaluation_row(merged, original_row=payload)