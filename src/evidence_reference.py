from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any


class EvidenceAvailabilityState(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"
    MISSING = "missing"


SUPPORTED_EVIDENCE_TYPES: dict[str, str] = {
    "forward_evidence": "forward_evidence",
    "planning_blueprint_lineage": "planning_blueprint_lineage",
    "script_lineage": "script_lineage",
    "thumbnail_metadata_lineage": "thumbnail_metadata_lineage",
    "analytics_evidence_join": "analytics_evidence_join",
    "analytics_feedback": "analytics_feedback",
    "cqga_revalidation": "cqga_revalidation",
    "experiment_assignment": "experiment_assignment",
    "channel_capability_state": "channel_capability_state",
    "channel_dna": "channel_dna",
    "runtime_evidence": "runtime_evidence",
    "execution_evidence": "execution_evidence",
    "dashboard_evidence": "dashboard_evidence",
    "analytics": "analytics_evidence_join",
}

_CONTENT_HASH_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _parse_iso(value: str) -> str:
    text = _safe_text(value)
    if not text:
        raise ValueError("missing_field:created_at")
    datetime.fromisoformat(text.replace("Z", "+00:00"))
    return text


def _normalize_availability_state(value: object) -> EvidenceAvailabilityState:
    if isinstance(value, EvidenceAvailabilityState):
        return value
    text = _safe_text(value).lower()
    if text in EvidenceAvailabilityState._value2member_map_:
        return EvidenceAvailabilityState(text)
    return EvidenceAvailabilityState.UNKNOWN


def normalize_evidence_type(value: Any) -> str:
    text = _safe_text(value)
    if not text:
        raise ValueError("missing_field:evidence_type")
    normalized = SUPPORTED_EVIDENCE_TYPES.get(text, text)
    if normalized not in SUPPORTED_EVIDENCE_TYPES.values():
        raise ValueError("unsupported_field:evidence_type")
    return normalized


def validate_content_hash(value: Any) -> str | None:
    text = _safe_text(value)
    if not text:
        return None
    if not _CONTENT_HASH_RE.fullmatch(text):
        raise ValueError("invalid_field:content_hash")
    return text.lower()


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    evidence_type: str
    evidence_id: str | None = None
    source_path: str | None = None
    source_module: str | None = None
    schema_version: str | None = None
    content_hash: str | None = None
    created_at: str = ""
    availability_state: EvidenceAvailabilityState = EvidenceAvailabilityState.UNKNOWN

    def __post_init__(self) -> None:
        validate_evidence_reference_row(asdict(self))

    def to_dict(self) -> dict[str, Any]:
        return validate_evidence_reference_row(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EvidenceReference":
        return cls(**validate_evidence_reference_row(dict(payload or {})))


def build_evidence_reference(
    *,
    evidence_type: str,
    evidence_id: str | None = None,
    source_path: str | None = None,
    source_module: str | None = None,
    schema_version: str | None = None,
    content_hash: str | None = None,
    created_at: str | None = None,
    availability_state: EvidenceAvailabilityState | str = EvidenceAvailabilityState.UNKNOWN,
) -> EvidenceReference:
    return EvidenceReference(
        evidence_type=normalize_evidence_type(evidence_type),
        evidence_id=_safe_text(evidence_id) or None,
        source_path=_safe_text(source_path) or None,
        source_module=_safe_text(source_module) or None,
        schema_version=_safe_text(schema_version) or None,
        content_hash=validate_content_hash(content_hash),
        created_at=_safe_text(created_at) or _now_iso(),
        availability_state=_normalize_availability_state(availability_state),
    )


def validate_evidence_reference_row(row: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ValueError("invalid_payload")

    if "evidence_type" not in row:
        raise ValueError("missing_field:evidence_type")
    if "created_at" not in row:
        raise ValueError("missing_field:created_at")
    if "availability_state" not in row:
        raise ValueError("missing_field:availability_state")

    evidence_type = normalize_evidence_type(row.get("evidence_type"))

    created_at = _parse_iso(_safe_text(row.get("created_at")))
    availability_state = _normalize_availability_state(row.get("availability_state"))

    normalized = {
        "evidence_type": evidence_type,
        "evidence_id": _safe_text(row.get("evidence_id")) or None,
        "source_path": _safe_text(row.get("source_path")) or None,
        "source_module": _safe_text(row.get("source_module")) or None,
        "schema_version": _safe_text(row.get("schema_version")) or None,
        "content_hash": validate_content_hash(row.get("content_hash")),
        "created_at": created_at,
        "availability_state": availability_state.value,
    }

    if normalized["availability_state"] == EvidenceAvailabilityState.AVAILABLE.value:
        if not (normalized["evidence_id"] or normalized["source_path"]):
            raise ValueError("missing_field:evidence_identity")

    return normalized
