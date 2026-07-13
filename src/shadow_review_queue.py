from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Literal

from .shadow_content_quality import validate_shadow_row
from .shadow_quality_taxonomy import get_finding_spec


REVIEW_QUEUE_SCHEMA_VERSION = "v1"
REVIEW_QUEUE_EVENT_SCHEMA_VERSION = "v1"
DEFAULT_REVIEW_QUEUE_EVENTS_PATH = Path("logs/shadow_review_queue_events.jsonl")

ReviewStatus = Literal["OPEN", "IN_REVIEW", "RESOLVED", "DISMISSED", "SUPERSEDED", "INVALID"]
ReviewDisposition = Literal[
    "CONFIRMED_ISSUE",
    "FALSE_POSITIVE",
    "ACCEPTABLE_RISK",
    "NEEDS_SOURCE_VERIFICATION",
    "NEEDS_CONTENT_REWRITE",
    "NEEDS_TITLE_REVIEW",
    "NEEDS_THUMBNAIL_REVIEW",
    "NEEDS_SHORTS_REVIEW",
    "NEEDS_TECHNICAL_REVIEW",
    "NO_ACTION",
    "UNDECIDED",
]
QueuePriority = Literal["P0_CRITICAL", "P1_HIGH", "P2_MEDIUM", "P3_LOW", "P4_INFO"]
QueueEventType = Literal[
    "ITEM_CREATED",
    "STATUS_CHANGED",
    "DISPOSITION_SET",
    "NOTE_ADDED",
    "ITEM_SUPERSEDED",
    "ITEM_INVALIDATED",
]

_ALLOWED_STATUSES = {"OPEN", "IN_REVIEW", "RESOLVED", "DISMISSED", "SUPERSEDED", "INVALID"}
_ALLOWED_DISPOSITIONS = {
    "CONFIRMED_ISSUE",
    "FALSE_POSITIVE",
    "ACCEPTABLE_RISK",
    "NEEDS_SOURCE_VERIFICATION",
    "NEEDS_CONTENT_REWRITE",
    "NEEDS_TITLE_REVIEW",
    "NEEDS_THUMBNAIL_REVIEW",
    "NEEDS_SHORTS_REVIEW",
    "NEEDS_TECHNICAL_REVIEW",
    "NO_ACTION",
    "UNDECIDED",
}
_ALLOWED_PRIORITIES = {"P0_CRITICAL", "P1_HIGH", "P2_MEDIUM", "P3_LOW", "P4_INFO"}
_ALLOWED_EVENT_TYPES = {
    "ITEM_CREATED",
    "STATUS_CHANGED",
    "DISPOSITION_SET",
    "NOTE_ADDED",
    "ITEM_SUPERSEDED",
    "ITEM_INVALIDATED",
}

_ALLOWED_TRANSITIONS: set[tuple[ReviewStatus, ReviewStatus]] = {
    ("OPEN", "IN_REVIEW"),
    ("OPEN", "DISMISSED"),
    ("OPEN", "RESOLVED"),
    ("OPEN", "SUPERSEDED"),
    ("OPEN", "INVALID"),
    ("IN_REVIEW", "RESOLVED"),
    ("IN_REVIEW", "DISMISSED"),
    ("IN_REVIEW", "SUPERSEDED"),
    ("IN_REVIEW", "INVALID"),
}

_SEVERITY_ORDER = {"INFO": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
_CONFIDENCE_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
_PRIORITY_ORDER = {"P0_CRITICAL": 0, "P1_HIGH": 1, "P2_MEDIUM": 2, "P3_LOW": 3, "P4_INFO": 4}

_FINANCE_ASSERTIVE_CODES = {
    "guaranteed_return_wording_detection",
    "unverifiable_insider_information_detection",
    "not_priced_in_claim_detection",
    "secret_institutional_claim_detection",
    "urgent_trade_pressure_detection",
    "extreme_return_claim_detection",
    "unsupported_financial_claim_detection",
    "fabricated_authority_detection",
    "specific_security_certainty_detection",
}

_ALWAYS_ELIGIBLE_CODES = {
    "ticker_company_mismatch_detection",
    "thumbnail_ticker_company_mismatch",
    "title_script_semantic_consistency",
    "title_thumbnail_text_consistency",
    "duplicate_script_detection",
    "shorts_sentence_completeness",
    "shorts_abrupt_beginning",
    "shorts_abrupt_ending",
    "shorts_missing_context",
    "validator_exception",
}

_NON_REVIEWABLE_CODES = {
    "card_recommendation_not_implemented",
    "end_screen_recommendation_not_implemented",
}

_EQUIVALENT_FINDING_GROUPS = {
    "guaranteed_return_wording_detection": "finance_guarantee_equivalent",
    "unsupported_financial_claim_detection": "finance_guarantee_equivalent",
    "repetitive_opening_detection": "duplicate_opening_equivalent",
    "duplicate_script_detection": "duplicate_opening_equivalent",
    "shorts_payoff_without_context": "shorts_context_equivalent",
    "shorts_missing_context": "shorts_context_equivalent",
}

_SECRET_PATTERN = re.compile(
    r"(oauth|token|api[_-]?key|client[_-]?secret|refresh[_-]?token|access[_-]?token|bearer\s+[a-z0-9._-]+|password|cookie)",
    re.IGNORECASE,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_excerpt(value: str | None, *, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if _SECRET_PATTERN.search(text):
        raise ReviewQueueValidationError("secret_like_content_in_excerpt")
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


class ReviewQueueValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ReviewQueueTransitionError(ReviewQueueValidationError):
    review_item_id: str
    from_status: str
    to_status: str

    def to_dict(self) -> dict[str, str]:
        return {
            "error": "invalid_transition",
            "review_item_id": self.review_item_id,
            "from_status": self.from_status,
            "to_status": self.to_status,
        }


@dataclass(frozen=True)
class ReviewQueueItem:
    schema_version: str
    review_item_id: str
    evaluation_id: str
    run_id: str
    content_id: str
    canonical_channel_id: str
    content_type: str
    checkpoint: str
    finding_code: str
    category: str
    severity: str
    confidence: str
    validator_version: str
    affected_artifact: str
    bounded_evidence_excerpt: str
    evidence_hash: str
    explanation: str
    remediation_class: str
    suggested_review_action: str
    blocking_eligible_future: bool
    advisory_only: bool
    queue_priority: QueuePriority
    queue_reason: str
    source_row_schema_version: str
    source_created_at: str
    queue_created_at: str
    status: ReviewStatus
    disposition: ReviewDisposition
    reviewer_note: str
    reviewed_at: str
    supersedes_review_item_id: str
    bundle_id: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReviewQueueEvent:
    schema_version: str
    event_type: QueueEventType
    event_id: str
    review_item_id: str
    created_at: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QueueIngestionResult:
    source_rows_seen: int
    source_rows_valid: int
    source_rows_invalid: int
    findings_seen: int
    findings_eligible: int
    review_items_created: int
    review_items_existing: int
    bundles_created: int
    malformed_rows: list[dict[str, Any]]
    errors: list[dict[str, Any]]
    advisory_only: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QueueQueryDiagnostics:
    malformed_row_count: int
    replay_errors: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _finding_group_key(item: dict[str, Any]) -> str:
    code = str(item.get("finding_code") or "")
    return _EQUIVALENT_FINDING_GROUPS.get(code, code)


def _make_review_item_id(*, source_identity: str) -> str:
    return "rq_" + _sha(source_identity)[:24]


def _make_bundle_id(*, run_id: str, content_id: str, channel_id: str, checkpoint: str, category: str, artifact: str) -> str:
    raw = "|".join([run_id, content_id, channel_id, checkpoint, category, artifact])
    return "rb_" + _sha(raw)[:20]


def _make_event_id(*, event_type: str, review_item_id: str, created_at: str, payload: dict[str, Any]) -> str:
    raw = json.dumps(
        {
            "event_type": event_type,
            "review_item_id": review_item_id,
            "created_at": created_at,
            "payload": payload,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "rqe_" + _sha(raw)[:28]


def _source_identity(*, row: dict[str, Any], finding: dict[str, Any]) -> str:
    return "|".join(
        [
            str(row.get("evaluation_id") or ""),
            str(finding.get("code") or ""),
            str(finding.get("affected_artifact") or ""),
            str(finding.get("evidence_hash") or ""),
            str(row.get("schema_version") or ""),
        ]
    )


def _supersede_identity(*, row: dict[str, Any], finding: dict[str, Any]) -> str:
    return "|".join(
        [
            str(row.get("run_id") or ""),
            str(row.get("content_id") or ""),
            str(row.get("channel_id") or ""),
            str(finding.get("code") or ""),
            str(finding.get("affected_artifact") or ""),
            str(row.get("schema_version") or ""),
        ]
    )


def _finance_reason(code: str, details: dict[str, Any]) -> str:
    mapping = {
        "guaranteed_return_wording_detection": "finance_guaranteed_return_claim",
        "unverifiable_insider_information_detection": "finance_insider_information_claim",
        "not_priced_in_claim_detection": "finance_not_yet_priced_in_claim",
        "secret_institutional_claim_detection": "finance_secret_institutional_activity_claim",
        "urgent_trade_pressure_detection": "finance_urgent_trade_pressure_claim",
        "extreme_return_claim_detection": "finance_extreme_return_claim",
        "fabricated_authority_detection": "finance_unnamed_or_fabricated_authority_claim",
        "specific_security_certainty_detection": "finance_specific_security_certainty_claim",
        "ticker_company_mismatch_detection": "finance_specific_security_mismatch",
        "pump_style_title_detection": "finance_pump_style_title_amplification",
    }
    if details.get("contextual_classification") == "negated":
        return "finance_educational_warning_or_negation"
    return mapping.get(code, "finance_advisory_review")


def _shorts_reason(code: str) -> str:
    mapping = {
        "shorts_sentence_completeness": "shorts_starts_or_ends_mid_sentence",
        "shorts_abrupt_beginning": "shorts_abrupt_beginning",
        "shorts_abrupt_ending": "shorts_abrupt_termination",
        "shorts_missing_context": "shorts_missing_context",
        "shorts_context_without_payoff": "shorts_context_without_payoff",
        "shorts_payoff_without_context": "shorts_payoff_without_context",
        "shorts_title_content_consistency": "shorts_title_content_mismatch",
        "duplicate_shorts_content": "shorts_repeated_source_segment",
        "shorts_duration_signal": "shorts_duration_issue",
        "shorts_hook_quality": "shorts_missing_usable_hook",
    }
    return mapping.get(code, "shorts_advisory_review")


def _duplication_reason(code: str, details: dict[str, Any]) -> str:
    dup_type = str(details.get("duplicate_type") or "")
    if code == "duplicate_title_detection" and dup_type == "exact":
        return "duplication_exact_duplicate_title"
    if code == "duplicate_title_detection":
        return "duplication_near_duplicate_title"
    if code == "duplicate_script_detection" and dup_type in {"exact", "exact_hash"}:
        return "duplication_exact_duplicate_script"
    if code == "duplicate_script_detection":
        return "duplication_near_duplicate_script"
    if code == "repetitive_opening_detection":
        return "duplication_repeated_opening"
    if code == "repeated_cta_detection":
        return "duplication_repeated_cta"
    if code == "duplicate_thumbnail_text_detection":
        return "duplication_duplicate_thumbnail_phrase"
    if code == "duplicate_shorts_content":
        return "duplication_repeated_shorts_hook_or_segment"
    return "duplication_or_repetition_advisory_review"


def build_suggested_review_action(*, finding_code: str, category: str, affected_artifact: str) -> str:
    by_finding = {
        "ticker_company_mismatch_detection": "inspect_ticker_company_mapping",
        "thumbnail_ticker_company_mismatch": "inspect_ticker_company_mapping",
        "validator_exception": "technical_validator_review",
        "shorts_sentence_completeness": "inspect_short_boundaries",
        "shorts_abrupt_beginning": "inspect_short_boundaries",
        "shorts_abrupt_ending": "inspect_short_boundaries",
        "shorts_missing_context": "inspect_short_boundaries",
        "duplicate_script_detection": "compare_with_recent_content",
        "repetitive_opening_detection": "compare_with_recent_content",
    }
    if finding_code in by_finding:
        return by_finding[finding_code]
    if category == "financial_claim_risk":
        return "verify_source"
    if affected_artifact == "title":
        return "inspect_title"
    if affected_artifact in {"thumbnail_metadata", "thumbnail"}:
        return "inspect_thumbnail_prompt_or_text"
    if affected_artifact == "script":
        return "inspect_script"
    if category == "shorts_structure":
        return "inspect_short_boundaries"
    if category == "validator_failure":
        return "technical_validator_review"
    return "no_action"


def _contains_specific_security(row: dict[str, Any], finding_code: str) -> bool:
    if finding_code in {
        "ticker_company_mismatch_detection",
        "thumbnail_ticker_company_mismatch",
        "specific_security_certainty_detection",
    }:
        return True
    hashes = row.get("hashes")
    if isinstance(hashes, dict):
        title_excerpt = str(hashes.get("title_excerpt") or "")
        return bool(re.search(r"\b[A-Z]{3,5}\b", title_excerpt))
    return False


def _is_negated_educational_finding(finding: dict[str, Any]) -> bool:
    details = finding.get("details")
    if not isinstance(details, dict):
        return False
    return str(details.get("contextual_classification") or "").lower() in {"negated", "hypothetical", "quoted"}


def is_finding_review_eligible(*, row: dict[str, Any], finding: dict[str, Any], related_findings: list[dict[str, Any]]) -> tuple[bool, str]:
    code = str(finding.get("code") or "")
    severity = str(finding.get("severity") or "").upper()
    confidence = str(finding.get("confidence") or "").upper()
    category = str(finding.get("category") or get_finding_spec(code).category)

    if _is_negated_educational_finding(finding):
        return False, "non_reviewable_safe_educational_negation"

    if code in _NON_REVIEWABLE_CODES:
        return False, "non_reviewable_unsupported_feature"

    if severity in {"CRITICAL", "HIGH"}:
        return True, "always_eligible_high_severity"

    if category == "financial_claim_risk" and confidence in {"MEDIUM", "HIGH"}:
        return True, "always_eligible_financial_claim"

    if code in _ALWAYS_ELIGIBLE_CODES and confidence in {"MEDIUM", "HIGH"}:
        return True, "always_eligible_finding_code"

    related_count = len(related_findings)
    if severity == "MEDIUM":
        return True, "conditionally_eligible_medium_severity"

    if severity in {"LOW", "INFO"} and related_count >= 3:
        return True, "conditionally_eligible_correlated_low_signals"

    if category == "unsupported_feature" and confidence == "HIGH":
        return True, "conditionally_eligible_operational_followup"

    return False, "non_reviewable_low_confidence_or_informational"


def calculate_queue_priority(
    *,
    row: dict[str, Any],
    finding: dict[str, Any],
    related_findings: list[dict[str, Any]],
    now_iso: str,
) -> tuple[QueuePriority, str]:
    severity = str(finding.get("severity") or "LOW").upper()
    confidence = str(finding.get("confidence") or "LOW").upper()
    code = str(finding.get("code") or "")
    category = str(finding.get("category") or get_finding_spec(code).category)
    checkpoint = str(row.get("checkpoint") or "")
    content_type = str(row.get("content_type") or "")

    score = {
        "CRITICAL": 100,
        "HIGH": 80,
        "MEDIUM": 56,
        "LOW": 30,
        "INFO": 15,
    }.get(severity, 20)
    score += {"HIGH": 15, "MEDIUM": 8, "LOW": 0}.get(confidence, 0)
    score += {
        "financial_claim_risk": 22,
        "semantic_consistency": 14,
        "duplication": 12,
        "repetition": 10,
        "shorts_structure": 11,
        "validator_failure": 6,
        "unsupported_feature": -8,
        "seo_observability": -5,
    }.get(category, 0)

    if code in _FINANCE_ASSERTIVE_CODES:
        score += 18
    if code in {"ticker_company_mismatch_detection", "thumbnail_ticker_company_mismatch"}:
        score += 14
    if code in {"pump_style_title_detection", "title_thumbnail_text_consistency"}:
        score += 8
    if code == "validator_exception":
        score += 10
    if code in {"card_recommendation_not_implemented", "end_screen_recommendation_not_implemented"}:
        score -= 18

    if checkpoint in {"generation", "shorts"}:
        score += 4
    if content_type in {"short", "mixed"} and category == "shorts_structure":
        score += 5

    related_count = len(related_findings)
    score += min(20, related_count * 4)

    if _contains_specific_security(row, code):
        score += 10

    related_codes = {str(item.get("code") or "") for item in related_findings}
    if category == "financial_claim_risk" and (
        "pump_style_title_detection" in related_codes
        or "title_thumbnail_text_consistency" in related_codes
        or "thumbnail_text_financial_safety" in related_codes
    ):
        score += 12

    related_artifacts = {str(item.get("affected_artifact") or "") for item in related_findings}
    if len(related_artifacts) >= 2:
        score += 8

    try:
        source_dt = _parse_iso(str(row.get("created_at") or now_iso))
        now_dt = _parse_iso(now_iso)
        age_days = max(0, int((now_dt - source_dt).total_seconds() // 86400))
        score += min(10, age_days // 2)
    except Exception:
        pass

    if score >= 125:
        return "P0_CRITICAL", "priority_score>=125"
    if score >= 95:
        return "P1_HIGH", "priority_score>=95"
    if score >= 70:
        return "P2_MEDIUM", "priority_score>=70"
    if score >= 40:
        return "P3_LOW", "priority_score>=40"
    return "P4_INFO", "priority_score<40"


def build_queue_reason(*, row: dict[str, Any], finding: dict[str, Any], related_findings: list[dict[str, Any]]) -> str:
    code = str(finding.get("code") or "")
    category = str(finding.get("category") or get_finding_spec(code).category)
    details = finding.get("details") if isinstance(finding.get("details"), dict) else {}

    if category == "financial_claim_risk" or code in {
        "ticker_company_mismatch_detection",
        "thumbnail_ticker_company_mismatch",
        "pump_style_title_detection",
    }:
        return _finance_reason(code, details)
    if category == "shorts_structure":
        return _shorts_reason(code)
    if category in {"duplication", "repetition"}:
        return _duplication_reason(code, details)
    if category == "validator_failure":
        return "technical_validator_review_required"

    if len(related_findings) >= 3:
        return "correlated_multi_finding_bundle"
    return "advisory_quality_review"


def _validate_item_payload(payload: dict[str, Any]) -> dict[str, Any]:
    required = [
        "schema_version",
        "review_item_id",
        "evaluation_id",
        "run_id",
        "content_id",
        "canonical_channel_id",
        "content_type",
        "checkpoint",
        "finding_code",
        "category",
        "severity",
        "confidence",
        "validator_version",
        "affected_artifact",
        "bounded_evidence_excerpt",
        "evidence_hash",
        "explanation",
        "remediation_class",
        "suggested_review_action",
        "blocking_eligible_future",
        "advisory_only",
        "queue_priority",
        "queue_reason",
        "source_row_schema_version",
        "source_created_at",
        "queue_created_at",
        "status",
        "disposition",
        "reviewer_note",
        "reviewed_at",
        "supersedes_review_item_id",
        "bundle_id",
    ]
    for key in required:
        if key not in payload:
            raise ReviewQueueValidationError(f"missing_field:{key}")

    if str(payload.get("schema_version") or "") != REVIEW_QUEUE_SCHEMA_VERSION:
        raise ReviewQueueValidationError("invalid_field:schema_version")
    if str(payload.get("status") or "") not in _ALLOWED_STATUSES:
        raise ReviewQueueValidationError("invalid_field:status")
    if str(payload.get("disposition") or "") not in _ALLOWED_DISPOSITIONS:
        raise ReviewQueueValidationError("invalid_field:disposition")
    if str(payload.get("queue_priority") or "") not in _ALLOWED_PRIORITIES:
        raise ReviewQueueValidationError("invalid_field:queue_priority")

    _parse_iso(str(payload.get("source_created_at") or ""))
    _parse_iso(str(payload.get("queue_created_at") or ""))
    if str(payload.get("reviewed_at") or ""):
        _parse_iso(str(payload.get("reviewed_at") or ""))

    excerpt = str(payload.get("bounded_evidence_excerpt") or "")
    if len(excerpt) > 240:
        raise ReviewQueueValidationError("invalid_field:bounded_evidence_excerpt")
    if _SECRET_PATTERN.search(excerpt):
        raise ReviewQueueValidationError("secret_like_content_in_excerpt")

    return payload


def make_review_queue_item(
    *,
    row: dict[str, Any],
    finding: dict[str, Any],
    queue_priority: QueuePriority,
    queue_reason: str,
    queue_created_at: str,
    bundle_id: str = "",
    supersedes_review_item_id: str = "",
) -> ReviewQueueItem:
    spec = get_finding_spec(str(finding.get("code") or ""))
    source_id = _source_identity(row=row, finding=finding)
    payload = {
        "schema_version": REVIEW_QUEUE_SCHEMA_VERSION,
        "review_item_id": _make_review_item_id(source_identity=source_id),
        "evaluation_id": str(row.get("evaluation_id") or ""),
        "run_id": str(row.get("run_id") or ""),
        "content_id": str(row.get("content_id") or ""),
        "canonical_channel_id": str(row.get("channel_id") or ""),
        "content_type": str(row.get("content_type") or ""),
        "checkpoint": str(row.get("checkpoint") or ""),
        "finding_code": str(finding.get("code") or ""),
        "category": str(finding.get("category") or spec.category),
        "severity": str(finding.get("severity") or spec.default_severity),
        "confidence": str(finding.get("confidence") or spec.default_confidence),
        "validator_version": str(finding.get("validator_version") or spec.validator_version),
        "affected_artifact": str(finding.get("affected_artifact") or spec.affected_artifact),
        "bounded_evidence_excerpt": _normalize_excerpt(str(finding.get("evidence_excerpt") or "")),
        "evidence_hash": str(finding.get("evidence_hash") or ""),
        "explanation": _normalize_excerpt(str(finding.get("message") or spec.explanation), limit=400),
        "remediation_class": str(finding.get("remediation_class") or spec.remediation_class),
        "suggested_review_action": build_suggested_review_action(
            finding_code=str(finding.get("code") or ""),
            category=str(finding.get("category") or spec.category),
            affected_artifact=str(finding.get("affected_artifact") or spec.affected_artifact),
        ),
        "blocking_eligible_future": bool(finding.get("blocking_eligible_future", spec.blocking_eligible_future)),
        "advisory_only": True,
        "queue_priority": queue_priority,
        "queue_reason": str(queue_reason or "advisory_quality_review"),
        "source_row_schema_version": str(row.get("schema_version") or ""),
        "source_created_at": str(row.get("created_at") or queue_created_at),
        "queue_created_at": str(queue_created_at),
        "status": "OPEN",
        "disposition": "UNDECIDED",
        "reviewer_note": "",
        "reviewed_at": "",
        "supersedes_review_item_id": str(supersedes_review_item_id or ""),
        "bundle_id": str(bundle_id or ""),
    }
    normalized = _validate_item_payload(payload)
    return ReviewQueueItem(**normalized)


def _validate_event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    required = ["schema_version", "event_type", "event_id", "review_item_id", "created_at", "payload"]
    for key in required:
        if key not in payload:
            raise ReviewQueueValidationError(f"missing_field:{key}")
    if str(payload.get("schema_version") or "") != REVIEW_QUEUE_EVENT_SCHEMA_VERSION:
        raise ReviewQueueValidationError("invalid_field:event.schema_version")
    if str(payload.get("event_type") or "") not in _ALLOWED_EVENT_TYPES:
        raise ReviewQueueValidationError("invalid_field:event.event_type")
    _parse_iso(str(payload.get("created_at") or ""))
    if not isinstance(payload.get("payload"), dict):
        raise ReviewQueueValidationError("invalid_field:event.payload")
    return payload


def make_event(*, event_type: QueueEventType, review_item_id: str, created_at: str, payload: dict[str, Any]) -> ReviewQueueEvent:
    event_payload = {
        "schema_version": REVIEW_QUEUE_EVENT_SCHEMA_VERSION,
        "event_type": str(event_type),
        "event_id": _make_event_id(
            event_type=str(event_type),
            review_item_id=str(review_item_id),
            created_at=str(created_at),
            payload=payload,
        ),
        "review_item_id": str(review_item_id),
        "created_at": str(created_at),
        "payload": dict(payload),
    }
    normalized = _validate_event_payload(event_payload)
    return ReviewQueueEvent(**normalized)


def append_review_queue_event(
    event: ReviewQueueEvent,
    *,
    output_path: Path | str = DEFAULT_REVIEW_QUEUE_EVENTS_PATH,
) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
    try:
        os.write(fd, data.encode("utf-8"))
    finally:
        os.close(fd)


def load_review_queue_events(
    *,
    input_path: Path | str = DEFAULT_REVIEW_QUEUE_EVENTS_PATH,
) -> tuple[list[ReviewQueueEvent], int, list[dict[str, Any]]]:
    path = Path(input_path)
    if not path.exists():
        return [], 0, []

    events: list[ReviewQueueEvent] = []
    malformed = 0
    errors: list[dict[str, Any]] = []

    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
            normalized = _validate_event_payload(payload)
            events.append(ReviewQueueEvent(**normalized))
        except Exception as exc:
            malformed += 1
            errors.append({"line": line_no, "error": str(exc.__class__.__name__)})

    events.sort(key=lambda x: (x.created_at, x.event_id))
    return events, malformed, errors


def validate_status_transition(*, review_item_id: str, from_status: ReviewStatus, to_status: ReviewStatus) -> None:
    if from_status == to_status:
        return
    if (from_status, to_status) not in _ALLOWED_TRANSITIONS:
        raise ReviewQueueTransitionError(review_item_id=review_item_id, from_status=from_status, to_status=to_status)


def replay_review_queue_state(
    *,
    events: list[ReviewQueueEvent],
) -> tuple[dict[str, dict[str, Any]], QueueQueryDiagnostics]:
    state: dict[str, dict[str, Any]] = {}
    replay_errors: list[dict[str, Any]] = []

    for event in sorted(events, key=lambda x: (x.created_at, x.event_id)):
        item_id = event.review_item_id
        payload = event.payload
        etype = event.event_type

        if etype == "ITEM_CREATED":
            try:
                item_payload = _validate_item_payload(dict(payload.get("item") or {}))
                state[item_id] = dict(item_payload)
            except Exception as exc:
                replay_errors.append({"event_id": event.event_id, "error": f"ITEM_CREATED:{exc.__class__.__name__}"})
            continue

        current = state.get(item_id)
        if not current:
            replay_errors.append({"event_id": event.event_id, "error": f"missing_item:{item_id}"})
            continue

        try:
            if etype == "STATUS_CHANGED":
                to_status = str(payload.get("to_status") or "")
                validate_status_transition(
                    review_item_id=item_id,
                    from_status=str(current.get("status") or "OPEN"),
                    to_status=to_status,  # type: ignore[arg-type]
                )
                current["status"] = to_status
                current["reviewed_at"] = str(payload.get("reviewed_at") or event.created_at)
            elif etype == "DISPOSITION_SET":
                disposition = str(payload.get("disposition") or "")
                if disposition not in _ALLOWED_DISPOSITIONS:
                    raise ReviewQueueValidationError("invalid_field:disposition")
                current["disposition"] = disposition
                current["reviewed_at"] = str(payload.get("reviewed_at") or event.created_at)
            elif etype == "NOTE_ADDED":
                note = _normalize_excerpt(str(payload.get("note") or ""), limit=400)
                current["reviewer_note"] = note
                current["reviewed_at"] = str(payload.get("reviewed_at") or event.created_at)
            elif etype == "ITEM_SUPERSEDED":
                validate_status_transition(
                    review_item_id=item_id,
                    from_status=str(current.get("status") or "OPEN"),
                    to_status="SUPERSEDED",
                )
                current["status"] = "SUPERSEDED"
                current["reviewed_at"] = str(payload.get("reviewed_at") or event.created_at)
            elif etype == "ITEM_INVALIDATED":
                validate_status_transition(
                    review_item_id=item_id,
                    from_status=str(current.get("status") or "OPEN"),
                    to_status="INVALID",
                )
                current["status"] = "INVALID"
                current["reviewed_at"] = str(payload.get("reviewed_at") or event.created_at)
        except Exception as exc:
            replay_errors.append({"event_id": event.event_id, "error": f"{etype}:{exc.__class__.__name__}"})

    diagnostics = QueueQueryDiagnostics(malformed_row_count=0, replay_errors=replay_errors)
    return state, diagnostics


def apply_status_transition(
    *,
    review_item_id: str,
    to_status: ReviewStatus,
    events_path: Path | str = DEFAULT_REVIEW_QUEUE_EVENTS_PATH,
    reviewed_at: str | None = None,
) -> ReviewQueueEvent:
    events, _, _ = load_review_queue_events(input_path=events_path)
    state, _ = replay_review_queue_state(events=events)
    current = state.get(review_item_id)
    if not current:
        raise ReviewQueueValidationError("missing_item")

    from_status = str(current.get("status") or "OPEN")
    validate_status_transition(review_item_id=review_item_id, from_status=from_status, to_status=to_status)

    event = make_event(
        event_type="STATUS_CHANGED",
        review_item_id=review_item_id,
        created_at=_now_iso(),
        payload={
            "from_status": from_status,
            "to_status": to_status,
            "reviewed_at": reviewed_at or _now_iso(),
        },
    )
    append_review_queue_event(event, output_path=events_path)
    return event


def apply_disposition(
    *,
    review_item_id: str,
    disposition: ReviewDisposition,
    events_path: Path | str = DEFAULT_REVIEW_QUEUE_EVENTS_PATH,
    reviewed_at: str | None = None,
) -> ReviewQueueEvent:
    if disposition not in _ALLOWED_DISPOSITIONS:
        raise ReviewQueueValidationError("invalid_field:disposition")
    event = make_event(
        event_type="DISPOSITION_SET",
        review_item_id=review_item_id,
        created_at=_now_iso(),
        payload={
            "disposition": disposition,
            "reviewed_at": reviewed_at or _now_iso(),
        },
    )
    append_review_queue_event(event, output_path=events_path)
    return event


def add_reviewer_note(
    *,
    review_item_id: str,
    note: str,
    events_path: Path | str = DEFAULT_REVIEW_QUEUE_EVENTS_PATH,
    reviewed_at: str | None = None,
) -> ReviewQueueEvent:
    event = make_event(
        event_type="NOTE_ADDED",
        review_item_id=review_item_id,
        created_at=_now_iso(),
        payload={
            "note": _normalize_excerpt(note, limit=400),
            "reviewed_at": reviewed_at or _now_iso(),
        },
    )
    append_review_queue_event(event, output_path=events_path)
    return event


def _sort_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        items,
        key=lambda item: (
            _PRIORITY_ORDER.get(str(item.get("queue_priority") or "P4_INFO"), 4),
            -_SEVERITY_ORDER.get(str(item.get("severity") or "INFO"), 0),
            -_CONFIDENCE_ORDER.get(str(item.get("confidence") or "LOW"), 0),
            str(item.get("queue_created_at") or ""),
            str(item.get("review_item_id") or ""),
        ),
    )


def query_review_items(
    *,
    items: list[dict[str, Any]],
    status: set[str] | None = None,
    disposition: set[str] | None = None,
    priority: set[str] | None = None,
    severity: set[str] | None = None,
    confidence: set[str] | None = None,
    category: set[str] | None = None,
    finding_code: set[str] | None = None,
    channel_id: set[str] | None = None,
    content_type: set[str] | None = None,
    checkpoint: set[str] | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    unresolved_only: bool = False,
    specific_security_financial_only: bool = False,
    shorts_only: bool = False,
    duplicates_only: bool = False,
    validator_failures_only: bool = False,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    dt_from = _parse_iso(created_from) if created_from else None
    dt_to = _parse_iso(created_to) if created_to else None

    for item in items:
        if status and str(item.get("status") or "") not in status:
            continue
        if disposition and str(item.get("disposition") or "") not in disposition:
            continue
        if priority and str(item.get("queue_priority") or "") not in priority:
            continue
        if severity and str(item.get("severity") or "") not in severity:
            continue
        if confidence and str(item.get("confidence") or "") not in confidence:
            continue
        if category and str(item.get("category") or "") not in category:
            continue
        if finding_code and str(item.get("finding_code") or "") not in finding_code:
            continue
        if channel_id and str(item.get("canonical_channel_id") or "") not in channel_id:
            continue
        if content_type and str(item.get("content_type") or "") not in content_type:
            continue
        if checkpoint and str(item.get("checkpoint") or "") not in checkpoint:
            continue

        if unresolved_only and str(item.get("status") or "") not in {"OPEN", "IN_REVIEW"}:
            continue

        if specific_security_financial_only:
            if str(item.get("category") or "") != "financial_claim_risk" and str(item.get("finding_code") or "") not in {
                "ticker_company_mismatch_detection",
                "thumbnail_ticker_company_mismatch",
            }:
                continue

        if shorts_only and str(item.get("category") or "") != "shorts_structure":
            continue

        if duplicates_only and str(item.get("category") or "") not in {"duplication", "repetition"}:
            continue

        if validator_failures_only and str(item.get("category") or "") != "validator_failure":
            continue

        if dt_from or dt_to:
            try:
                created = _parse_iso(str(item.get("queue_created_at") or item.get("source_created_at") or ""))
            except Exception:
                continue
            if dt_from and created < dt_from:
                continue
            if dt_to and created > dt_to:
                continue

        out.append(dict(item))

    return _sort_items(out)


def summarize_review_items(*, items: list[dict[str, Any]], malformed_row_count: int) -> dict[str, Any]:
    open_items = [item for item in items if str(item.get("status") or "") in {"OPEN", "IN_REVIEW"}]
    counts_by_priority: dict[str, int] = {}
    counts_by_category: dict[str, int] = {}
    counts_by_channel: dict[str, int] = {}
    counts_by_finding: dict[str, int] = {}
    false_positive_count = 0

    for item in items:
        counts_by_priority[str(item.get("queue_priority") or "P4_INFO")] = counts_by_priority.get(str(item.get("queue_priority") or "P4_INFO"), 0) + 1
        counts_by_category[str(item.get("category") or "unknown")] = counts_by_category.get(str(item.get("category") or "unknown"), 0) + 1
        counts_by_channel[str(item.get("canonical_channel_id") or "unknown")] = counts_by_channel.get(str(item.get("canonical_channel_id") or "unknown"), 0) + 1
        counts_by_finding[str(item.get("finding_code") or "unknown")] = counts_by_finding.get(str(item.get("finding_code") or "unknown"), 0) + 1
        if str(item.get("disposition") or "") == "FALSE_POSITIVE":
            false_positive_count += 1

    sorted_open = _sort_items(open_items)
    oldest_open_item = min(open_items, key=lambda x: str(x.get("queue_created_at") or "")) if open_items else None

    high_risk_finance_count = sum(
        1
        for item in open_items
        if str(item.get("category") or "") == "financial_claim_risk"
        and str(item.get("queue_priority") or "") in {"P0_CRITICAL", "P1_HIGH"}
    )

    shorts_count = sum(1 for item in open_items if str(item.get("category") or "") == "shorts_structure")
    duplication_count = sum(1 for item in open_items if str(item.get("category") or "") in {"duplication", "repetition"})

    return {
        "open_item_count": len(open_items),
        "counts_by_priority": counts_by_priority,
        "counts_by_category": counts_by_category,
        "counts_by_channel": counts_by_channel,
        "counts_by_finding_code": counts_by_finding,
        "oldest_open_item": oldest_open_item,
        "high_risk_financial_item_count": high_risk_finance_count,
        "shorts_review_count": shorts_count,
        "duplication_review_count": duplication_count,
        "false_positive_disposition_count": false_positive_count,
        "malformed_row_count": int(malformed_row_count),
        "ordered_open_items": sorted_open,
    }


def build_related_finding_bundles(*, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str, str, str], list[dict[str, Any]]] = {}
    for item in items:
        key = (
            str(item.get("run_id") or ""),
            str(item.get("content_id") or ""),
            str(item.get("canonical_channel_id") or ""),
            str(item.get("checkpoint") or ""),
            str(item.get("category") or ""),
            str(item.get("affected_artifact") or ""),
        )
        grouped.setdefault(key, []).append(item)

    bundles: list[dict[str, Any]] = []
    for key, members in sorted(grouped.items(), key=lambda x: x[0]):
        if len(members) < 2:
            continue

        run_id, content_id, channel_id, checkpoint, category, artifact = key
        codes = [str(item.get("finding_code") or "") for item in members]
        grouped_codes = sorted({_finding_group_key(item) for item in members})

        bundle = {
            "bundle_id": _make_bundle_id(
                run_id=run_id,
                content_id=content_id,
                channel_id=channel_id,
                checkpoint=checkpoint,
                category=category,
                artifact=artifact,
            ),
            "run_id": run_id,
            "content_id": content_id,
            "canonical_channel_id": channel_id,
            "checkpoint": checkpoint,
            "category": category,
            "affected_artifact": artifact,
            "review_item_ids": sorted(str(item.get("review_item_id") or "") for item in members),
            "finding_codes": sorted(codes),
            "finding_groups": grouped_codes,
            "severity": sorted((str(item.get("severity") or "INFO") for item in members), key=lambda x: _SEVERITY_ORDER.get(x, 0))[-1],
            "confidence": sorted((str(item.get("confidence") or "LOW") for item in members), key=lambda x: _CONFIDENCE_ORDER.get(x, 0))[-1],
            "finding_count": len(codes),
            "grouped_finding_count": len(grouped_codes),
            "bounded_evidence_excerpt": _normalize_excerpt(" | ".join(str(item.get("bounded_evidence_excerpt") or "") for item in members), limit=220),
        }
        bundles.append(bundle)

    return bundles


class ShadowReviewQueueBuilder:
    def __init__(
        self,
        *,
        events_path: Path | str = DEFAULT_REVIEW_QUEUE_EVENTS_PATH,
        advisory_only: bool = True,
    ) -> None:
        self.events_path = Path(events_path)
        self.advisory_only = bool(advisory_only)

    def _current_state(self) -> tuple[dict[str, dict[str, Any]], int, list[dict[str, Any]]]:
        events, malformed, errors = load_review_queue_events(input_path=self.events_path)
        state, diagnostics = replay_review_queue_state(events=events)
        return state, malformed, diagnostics.replay_errors + errors

    def ingest_shadow_rows(self, rows: list[dict[str, Any]]) -> QueueIngestionResult:
        source_rows_seen = len(rows)
        source_rows_valid = 0
        source_rows_invalid = 0
        findings_seen = 0
        findings_eligible = 0
        review_items_created = 0
        review_items_existing = 0
        bundles_created = 0
        malformed_rows: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []

        state, _, replay_errors = self._current_state()
        errors.extend(replay_errors)

        open_item_by_source: dict[str, str] = {}
        open_item_by_supersede_key: dict[str, str] = {}
        known_item_ids = set(state.keys())

        for review_item_id, item in state.items():
            status = str(item.get("status") or "")
            if status in {"OPEN", "IN_REVIEW"}:
                src = "|".join(
                    [
                        str(item.get("evaluation_id") or ""),
                        str(item.get("finding_code") or ""),
                        str(item.get("affected_artifact") or ""),
                        str(item.get("evidence_hash") or ""),
                        str(item.get("source_row_schema_version") or ""),
                    ]
                )
                open_item_by_source[src] = review_item_id
                supersede_key = "|".join(
                    [
                        str(item.get("run_id") or ""),
                        str(item.get("content_id") or ""),
                        str(item.get("canonical_channel_id") or ""),
                        str(item.get("finding_code") or ""),
                        str(item.get("affected_artifact") or ""),
                        str(item.get("source_row_schema_version") or ""),
                    ]
                )
                open_item_by_supersede_key[supersede_key] = review_item_id

        for index, row in enumerate(rows):
            try:
                normalized_row = validate_shadow_row(dict(row))
                source_rows_valid += 1
            except Exception as exc:
                source_rows_invalid += 1
                malformed_rows.append({"index": index, "error": str(exc)})
                continue

            findings = [item for item in (normalized_row.get("findings") or []) if isinstance(item, dict)]
            findings_seen += len(findings)
            if not findings:
                continue

            grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
            for finding in findings:
                spec = get_finding_spec(str(finding.get("code") or ""))
                category = str(finding.get("category") or spec.category)
                artifact = str(finding.get("affected_artifact") or spec.affected_artifact)
                grouped.setdefault((str(normalized_row.get("checkpoint") or ""), category, artifact), []).append(finding)

            bundle_map: dict[int, str] = {}
            for (_checkpoint, category, artifact), members in grouped.items():
                if len(members) < 2:
                    continue
                bundle_id = _make_bundle_id(
                    run_id=str(normalized_row.get("run_id") or ""),
                    content_id=str(normalized_row.get("content_id") or ""),
                    channel_id=str(normalized_row.get("channel_id") or ""),
                    checkpoint=str(normalized_row.get("checkpoint") or ""),
                    category=category,
                    artifact=artifact,
                )
                bundles_created += 1
                for member in members:
                    bundle_map[id(member)] = bundle_id

            for finding in findings:
                eligible, _eligibility_reason = is_finding_review_eligible(
                    row=normalized_row,
                    finding=finding,
                    related_findings=findings,
                )
                if not eligible:
                    continue

                findings_eligible += 1
                queue_priority, _ = calculate_queue_priority(
                    row=normalized_row,
                    finding=finding,
                    related_findings=findings,
                    now_iso=_now_iso(),
                )
                queue_reason = build_queue_reason(row=normalized_row, finding=finding, related_findings=findings)
                source_identity = _source_identity(row=normalized_row, finding=finding)

                if source_identity in open_item_by_source:
                    review_items_existing += 1
                    continue

                queue_created_at = _now_iso()
                supersede_key = _supersede_identity(row=normalized_row, finding=finding)
                supersedes_review_item_id = ""

                existing_open_id = open_item_by_supersede_key.get(supersede_key)
                if existing_open_id and existing_open_id in known_item_ids:
                    supersedes_review_item_id = existing_open_id

                item = make_review_queue_item(
                    row=normalized_row,
                    finding=finding,
                    queue_priority=queue_priority,
                    queue_reason=queue_reason,
                    queue_created_at=queue_created_at,
                    bundle_id=bundle_map.get(id(finding), ""),
                    supersedes_review_item_id=supersedes_review_item_id,
                )

                item_event = make_event(
                    event_type="ITEM_CREATED",
                    review_item_id=item.review_item_id,
                    created_at=queue_created_at,
                    payload={"item": item.to_dict()},
                )
                append_review_queue_event(item_event, output_path=self.events_path)
                review_items_created += 1
                known_item_ids.add(item.review_item_id)
                open_item_by_source[source_identity] = item.review_item_id
                open_item_by_supersede_key[supersede_key] = item.review_item_id

                if supersedes_review_item_id:
                    patch_event = make_event(
                        event_type="ITEM_SUPERSEDED",
                        review_item_id=supersedes_review_item_id,
                        created_at=queue_created_at,
                        payload={
                            "superseded_by_review_item_id": item.review_item_id,
                            "reviewed_at": queue_created_at,
                        },
                    )
                    append_review_queue_event(patch_event, output_path=self.events_path)

        return QueueIngestionResult(
            source_rows_seen=source_rows_seen,
            source_rows_valid=source_rows_valid,
            source_rows_invalid=source_rows_invalid,
            findings_seen=findings_seen,
            findings_eligible=findings_eligible,
            review_items_created=review_items_created,
            review_items_existing=review_items_existing,
            bundles_created=bundles_created,
            malformed_rows=malformed_rows,
            errors=errors,
            advisory_only=self.advisory_only,
        )

    def get_current_items(self) -> tuple[list[dict[str, Any]], QueueQueryDiagnostics]:
        events, malformed, errors = load_review_queue_events(input_path=self.events_path)
        state, diagnostics = replay_review_queue_state(events=events)
        merged = QueueQueryDiagnostics(
            malformed_row_count=malformed,
            replay_errors=diagnostics.replay_errors + errors,
        )
        return _sort_items([dict(item) for item in state.values()]), merged

    def query_current_items(self, **filters: Any) -> tuple[list[dict[str, Any]], QueueQueryDiagnostics]:
        items, diagnostics = self.get_current_items()
        return query_review_items(items=items, **filters), diagnostics

    def summarize_current_items(self) -> tuple[dict[str, Any], QueueQueryDiagnostics]:
        items, diagnostics = self.get_current_items()
        summary = summarize_review_items(items=items, malformed_row_count=diagnostics.malformed_row_count)
        return summary, diagnostics
