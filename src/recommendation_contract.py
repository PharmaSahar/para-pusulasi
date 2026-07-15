from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any


RECOMMENDATION_SCHEMA_VERSION = "v1"


class RecommendationState(str, Enum):
    NOT_RECOMMENDABLE = "NOT_RECOMMENDABLE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    ASSOCIATIONAL_ONLY = "ASSOCIATIONAL_ONLY"
    CAUSALLY_INCONCLUSIVE = "CAUSALLY_INCONCLUSIVE"
    CONTAMINATED = "CONTAMINATED"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    MODEL_LINEAGE_MISSING = "MODEL_LINEAGE_MISSING"
    PROMPT_LINEAGE_MISSING = "PROMPT_LINEAGE_MISSING"
    RECOMMENDATION_ELIGIBLE = "RECOMMENDATION_ELIGIBLE"
    ADVISORY_RECOMMENDATION = "ADVISORY_RECOMMENDATION"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
    INVALIDATED = "INVALIDATED"


class RecommendationPolicyStatus(str, Enum):
    UNKNOWN = "UNKNOWN"
    ALLOW = "ALLOW"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    BLOCKED = "BLOCKED"


class RecommendationEventType(str, Enum):
    RECOMMENDATION_ASSESSED = "recommendation_assessed"
    RECOMMENDATION_RECLASSIFIED = "recommendation_reclassified"
    RECOMMENDATION_POLICY_BLOCKED = "recommendation_policy_blocked"
    RECOMMENDATION_INVALIDATED = "recommendation_invalidated"
    RECOMMENDATION_REPLAYED = "recommendation_replayed"


_FORBIDDEN_RUNTIME_FIELDS = {
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
}

_REQUIRED_TEXT_FIELDS = (
    "schema_version",
    "decision_id",
    "learning_record_id",
    "outcome_record_id",
    "lifecycle_id",
    "evaluation_id",
    "confidence_id",
    "attribution_record_id",
    "created_at",
    "created_by",
    "source_module",
    "source_version",
)


@dataclass(frozen=True, slots=True)
class RecommendationRecord:
    schema_version: str
    recommendation_record_id: str
    recommendation_event_id: str
    event_type: str
    created_at: str
    created_by: str
    source_module: str
    source_version: str
    decision_id: str
    learning_record_id: str
    outcome_record_id: str
    lifecycle_id: str
    evaluation_id: str
    confidence_id: str
    attribution_record_id: str
    model_version_ref: str | None
    prompt_version_ref: str | None
    policy_version_ref: str | None
    feature_lineage_refs: tuple[dict[str, Any], ...]
    lifecycle_state: str | None
    evaluation_state: str | None
    confidence_state: str | None
    attribution_state: str | None
    outcome_maturity_state: str | None
    recommendation_state: str
    recommendation_reason: str
    recommendation_policy_status: str
    recommendation_eligible: bool
    human_review_required: bool
    contamination_state: str | None
    replay_integrity: bool
    evidence_is_synthetic: bool
    lineage_complete: bool | None
    upstream_records_resolved: bool | None
    invalidation_reasons: tuple[str, ...]
    advisory_recommendation: dict[str, Any] | None
    previous_record_hash: str | None
    record_hash: str

    def __post_init__(self) -> None:
        validate_recommendation_row(asdict(self))

    def to_dict(self) -> dict[str, Any]:
        return validate_recommendation_row(asdict(self))


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _optional_text(value: Any) -> str | None:
    text = _safe_text(value)
    return text or None


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
        if not isinstance(item, dict):
            raise ValueError(f"invalid_field:{name}")
        ref = json.loads(_stable_json(item))
        if not _safe_text(ref.get("ref_type")) or not _safe_text(ref.get("ref_id")):
            raise ValueError(f"invalid_field:{name}")
        out.append(ref)
    return tuple(out)


def _normalize_policy_status(value: Any) -> str:
    text = _safe_text(value).upper() or RecommendationPolicyStatus.UNKNOWN.value
    allowed = {item.value for item in RecommendationPolicyStatus}
    if text not in allowed:
        raise ValueError("invalid_field:recommendation_policy_status")
    return text


def _normalize_event_type(value: Any) -> str:
    text = _safe_text(value)
    if not text:
        return RecommendationEventType.RECOMMENDATION_ASSESSED.value
    allowed = {item.value for item in RecommendationEventType}
    if text not in allowed:
        raise ValueError("invalid_field:event_type")
    return text


def _validate_advisory_payload(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("invalid_field:advisory_recommendation")

    payload = json.loads(_stable_json(value))

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, item in node.items():
                key_lower = _safe_text(key).lower()
                if key_lower in _FORBIDDEN_RUNTIME_FIELDS:
                    raise ValueError(f"invalid_field:advisory_recommendation.runtime_action_key:{key_lower}")
                if key_lower in {"action", "operation", "command"}:
                    action_value = _safe_text(item).lower()
                    if action_value in _FORBIDDEN_RUNTIME_FIELDS:
                        raise ValueError(
                            f"invalid_field:advisory_recommendation.runtime_action_value:{action_value}"
                        )
                _walk(item)
            return
        if isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(payload)
    return payload


def _defaults() -> dict[str, Any]:
    return {
        "schema_version": RECOMMENDATION_SCHEMA_VERSION,
        "recommendation_record_id": "",
        "recommendation_event_id": "",
        "event_type": RecommendationEventType.RECOMMENDATION_ASSESSED.value,
        "created_at": "",
        "created_by": "",
        "source_module": "",
        "source_version": "",
        "decision_id": "",
        "learning_record_id": "",
        "outcome_record_id": "",
        "lifecycle_id": "",
        "evaluation_id": "",
        "confidence_id": "",
        "attribution_record_id": "",
        "model_version_ref": None,
        "prompt_version_ref": None,
        "policy_version_ref": None,
        "feature_lineage_refs": (),
        "lifecycle_state": None,
        "evaluation_state": None,
        "confidence_state": None,
        "attribution_state": None,
        "outcome_maturity_state": None,
        "recommendation_state": RecommendationState.NOT_RECOMMENDABLE.value,
        "recommendation_reason": "",
        "recommendation_policy_status": RecommendationPolicyStatus.UNKNOWN.value,
        "recommendation_eligible": False,
        "human_review_required": True,
        "contamination_state": None,
        "replay_integrity": True,
        "evidence_is_synthetic": False,
        "lineage_complete": None,
        "upstream_records_resolved": None,
        "invalidation_reasons": (),
        "advisory_recommendation": None,
        "previous_record_hash": None,
        "record_hash": "",
    }


def compute_recommendation_record_id(record: dict[str, Any]) -> str:
    payload = {
        "decision_id": _safe_text(record.get("decision_id")),
        "learning_record_id": _safe_text(record.get("learning_record_id")),
        "outcome_record_id": _safe_text(record.get("outcome_record_id")),
        "lifecycle_id": _safe_text(record.get("lifecycle_id")),
        "evaluation_id": _safe_text(record.get("evaluation_id")),
        "confidence_id": _safe_text(record.get("confidence_id")),
        "attribution_record_id": _safe_text(record.get("attribution_record_id")),
        "model_version_ref": _safe_text(record.get("model_version_ref")),
        "prompt_version_ref": _safe_text(record.get("prompt_version_ref")),
        "policy_version_ref": _safe_text(record.get("policy_version_ref")),
        "feature_lineage_refs": record.get("feature_lineage_refs") or (),
    }
    return "rcr_" + _sha(_stable_json(payload))[:24]


def compute_record_hash(record: dict[str, Any]) -> str:
    payload = dict(record)
    payload.pop("record_hash", None)
    payload.pop("recommendation_event_id", None)
    payload.pop("created_at", None)
    payload.pop("previous_record_hash", None)
    return "rch_" + _sha(_stable_json(payload))[:24]


def compute_recommendation_event_id(record: dict[str, Any]) -> str:
    payload = {
        "recommendation_record_id": _safe_text(record.get("recommendation_record_id")),
        "recommendation_state": _safe_text(record.get("recommendation_state")),
        "record_hash": _safe_text(record.get("record_hash")),
        "event_type": _safe_text(record.get("event_type")),
    }
    return "rce_" + _sha(_stable_json(payload))[:24]


def _is_mature_outcome(value: str | None) -> bool:
    text = _safe_text(value).lower()
    return text in {"mature", "archived", "superseded"}


def classify_recommendation_state(record: dict[str, Any]) -> tuple[str, str]:
    if not bool(record.get("replay_integrity", False)):
        return RecommendationState.INVALIDATED.value, "replay_integrity_failed"

    invalidation_reasons = tuple(record.get("invalidation_reasons") or ())
    if invalidation_reasons:
        return RecommendationState.INVALIDATED.value, "explicit_invalidation"

    if bool(record.get("evidence_is_synthetic", False)):
        return RecommendationState.INVALIDATED.value, "synthetic_evidence"

    contamination_state = _safe_text(record.get("contamination_state")).upper()
    if contamination_state not in {"", "NONE"}:
        return RecommendationState.CONTAMINATED.value, f"contamination:{contamination_state}"

    if not _optional_text(record.get("model_version_ref")):
        return RecommendationState.MODEL_LINEAGE_MISSING.value, "missing_model_lineage"

    if not _optional_text(record.get("prompt_version_ref")):
        return RecommendationState.PROMPT_LINEAGE_MISSING.value, "missing_prompt_lineage"

    if not _optional_text(record.get("policy_version_ref")):
        return RecommendationState.POLICY_BLOCKED.value, "missing_policy_lineage"

    policy_status = _safe_text(record.get("recommendation_policy_status"))
    if policy_status == RecommendationPolicyStatus.BLOCKED.value:
        return RecommendationState.POLICY_BLOCKED.value, "policy_blocked"

    if not record.get("feature_lineage_refs"):
        return RecommendationState.INSUFFICIENT_EVIDENCE.value, "missing_feature_lineage"

    if not bool(record.get("lineage_complete", False)):
        return RecommendationState.INSUFFICIENT_EVIDENCE.value, "evidence_lineage_incomplete"

    if not bool(record.get("upstream_records_resolved", False)):
        return RecommendationState.INSUFFICIENT_EVIDENCE.value, "upstream_record_unresolved"

    lifecycle_state = _safe_text(record.get("lifecycle_state")).upper()
    if lifecycle_state in {"", "INVALID", "CORRUPTED", "UNRESOLVED"}:
        return RecommendationState.INSUFFICIENT_EVIDENCE.value, f"lifecycle_state:{lifecycle_state or 'missing'}"

    if _safe_text(record.get("evaluation_state")) != "VALIDATED_RESULT":
        return RecommendationState.INSUFFICIENT_EVIDENCE.value, "evaluation_not_validated"

    if not _is_mature_outcome(_optional_text(record.get("outcome_maturity_state"))):
        return RecommendationState.INSUFFICIENT_EVIDENCE.value, "outcome_not_mature"

    attribution_state = _safe_text(record.get("attribution_state"))
    if attribution_state == "ASSOCIATIONAL_ONLY":
        return RecommendationState.ASSOCIATIONAL_ONLY.value, "associational_only"
    if attribution_state in {"ATTRIBUTION_ELIGIBLE", "CAUSALLY_INCONCLUSIVE"}:
        return RecommendationState.CAUSALLY_INCONCLUSIVE.value, f"causal_state:{attribution_state}"
    if attribution_state != "CAUSALLY_SUPPORTED":
        return RecommendationState.INSUFFICIENT_EVIDENCE.value, f"causal_state:{attribution_state or 'missing'}"

    confidence_state = _safe_text(record.get("confidence_state"))
    if confidence_state in {"DIRECTIONAL_SIGNAL", "STATISTICALLY_INCONCLUSIVE"}:
        return RecommendationState.CAUSALLY_INCONCLUSIVE.value, f"confidence_state:{confidence_state}"
    if confidence_state != "STATISTICALLY_SUPPORTED":
        return RecommendationState.INSUFFICIENT_EVIDENCE.value, f"confidence_state:{confidence_state or 'missing'}"

    if policy_status == RecommendationPolicyStatus.REVIEW_REQUIRED.value:
        return RecommendationState.HUMAN_REVIEW_REQUIRED.value, "policy_requires_review"

    advisory_payload = record.get("advisory_recommendation")
    if advisory_payload is not None:
        if not bool(record.get("human_review_required", False)):
            return RecommendationState.HUMAN_REVIEW_REQUIRED.value, "human_review_required"
        return RecommendationState.ADVISORY_RECOMMENDATION.value, "advisory_recommendation_available"

    if record.get("recommendation_eligible") is False:
        return RecommendationState.NOT_RECOMMENDABLE.value, "explicit_not_recommendable"

    return RecommendationState.RECOMMENDATION_ELIGIBLE.value, "recommendation_eligible"


def validate_recommendation_row(row: dict[str, Any], original_row: dict[str, Any] | None = None) -> dict[str, Any]:
    merged = _defaults()
    merged.update(dict(row))
    source_row = dict(original_row or row)

    if _safe_text(merged.get("schema_version")) != RECOMMENDATION_SCHEMA_VERSION:
        raise ValueError("invalid_field:schema_version")

    merged["event_type"] = _normalize_event_type(merged.get("event_type"))
    merged["created_at"] = _parse_iso("created_at", merged.get("created_at"))

    for key in (
        "created_by",
        "source_module",
        "source_version",
        "decision_id",
        "learning_record_id",
        "outcome_record_id",
        "lifecycle_id",
        "evaluation_id",
        "confidence_id",
        "attribution_record_id",
    ):
        merged[key] = _optional_text(merged.get(key))

    merged["model_version_ref"] = _optional_text(merged.get("model_version_ref"))
    merged["prompt_version_ref"] = _optional_text(merged.get("prompt_version_ref"))
    merged["policy_version_ref"] = _optional_text(merged.get("policy_version_ref"))

    merged["lifecycle_state"] = _optional_text(merged.get("lifecycle_state"))
    merged["evaluation_state"] = _optional_text(merged.get("evaluation_state"))
    merged["confidence_state"] = _optional_text(merged.get("confidence_state"))
    merged["attribution_state"] = _optional_text(merged.get("attribution_state"))
    merged["outcome_maturity_state"] = _optional_text(merged.get("outcome_maturity_state"))
    merged["contamination_state"] = _optional_text(merged.get("contamination_state"))

    merged["feature_lineage_refs"] = _normalize_ref_list("feature_lineage_refs", merged.get("feature_lineage_refs"))
    merged["invalidation_reasons"] = _normalize_string_list("invalidation_reasons", merged.get("invalidation_reasons"))
    merged["advisory_recommendation"] = _validate_advisory_payload(merged.get("advisory_recommendation"))

    merged["recommendation_policy_status"] = _normalize_policy_status(merged.get("recommendation_policy_status"))

    merged["recommendation_eligible"] = _normalize_bool(
        "recommendation_eligible",
        merged.get("recommendation_eligible"),
        allow_none=True,
    )
    merged["human_review_required"] = _normalize_bool(
        "human_review_required",
        merged.get("human_review_required"),
        allow_none=True,
    )
    merged["replay_integrity"] = bool(
        _normalize_bool("replay_integrity", merged.get("replay_integrity"), allow_none=False)
    )
    merged["evidence_is_synthetic"] = bool(
        _normalize_bool("evidence_is_synthetic", merged.get("evidence_is_synthetic"), allow_none=False)
    )
    merged["lineage_complete"] = _normalize_bool("lineage_complete", merged.get("lineage_complete"), allow_none=True)
    merged["upstream_records_resolved"] = _normalize_bool(
        "upstream_records_resolved", merged.get("upstream_records_resolved"), allow_none=True
    )

    for field in _REQUIRED_TEXT_FIELDS:
        if not _optional_text(merged.get(field)):
            raise ValueError(f"missing_field:{field}")

    state, reason = classify_recommendation_state(merged)
    supplied_state = _safe_text(source_row.get("recommendation_state"))
    if supplied_state and supplied_state != state:
        raise ValueError(f"invalid_field:recommendation_state:{supplied_state}->{state}")
    merged["recommendation_state"] = state
    merged["recommendation_reason"] = _optional_text(merged.get("recommendation_reason")) or reason

    merged["recommendation_eligible"] = state in {
        RecommendationState.RECOMMENDATION_ELIGIBLE.value,
        RecommendationState.ADVISORY_RECOMMENDATION.value,
        RecommendationState.HUMAN_REVIEW_REQUIRED.value,
    }

    # Sprint 8 guarantee: any advisory recommendation remains human-review gated.
    merged["human_review_required"] = True

    expected_record_id = compute_recommendation_record_id(merged)
    supplied_record_id = _safe_text(source_row.get("recommendation_record_id"))
    if supplied_record_id and supplied_record_id != expected_record_id:
        raise ValueError("invalid_field:recommendation_record_id")
    merged["recommendation_record_id"] = expected_record_id

    expected_record_hash = compute_record_hash(merged)
    supplied_record_hash = _safe_text(source_row.get("record_hash"))
    if supplied_record_hash and supplied_record_hash != expected_record_hash:
        raise ValueError("invalid_field:record_hash")
    merged["record_hash"] = expected_record_hash

    expected_event_id = compute_recommendation_event_id(merged)
    supplied_event_id = _safe_text(source_row.get("recommendation_event_id"))
    if supplied_event_id and supplied_event_id != expected_event_id:
        raise ValueError("invalid_field:recommendation_event_id")
    merged["recommendation_event_id"] = expected_event_id

    merged["previous_record_hash"] = _optional_text(merged.get("previous_record_hash"))
    return merged


def build_recommendation_record(
    payload: dict[str, Any],
    *,
    created_by: str,
    source_module: str,
    source_version: str,
    created_at: str | None = None,
    previous_record_hash: str | None = None,
    event_type: str | None = None,
) -> dict[str, Any]:
    merged = _defaults()
    merged.update(dict(payload))
    merged["created_by"] = created_by
    merged["source_module"] = source_module
    merged["source_version"] = source_version
    merged["created_at"] = created_at or datetime.now(timezone.utc).isoformat()
    merged["previous_record_hash"] = previous_record_hash
    if event_type is not None:
        merged["event_type"] = event_type
    return validate_recommendation_row(merged, original_row=payload)
