from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class HumanReviewItem:
    channel_id: str
    run_id: str
    content_type: str
    finding_code: str
    severity: str
    confidence: str
    affected_artifact: str
    bounded_excerpt: str
    explanation: str
    suggested_review_action: str
    evidence_hashes: dict[str, str]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_human_review_item(
    *,
    channel_id: str,
    run_id: str,
    content_type: str,
    finding_code: str,
    severity: str,
    confidence: str,
    affected_artifact: str,
    bounded_excerpt: str,
    explanation: str,
    suggested_review_action: str,
    evidence_hashes: dict[str, str] | None,
    created_at: str,
) -> HumanReviewItem:
    return HumanReviewItem(
        channel_id=str(channel_id or ""),
        run_id=str(run_id or ""),
        content_type=str(content_type or ""),
        finding_code=str(finding_code or ""),
        severity=str(severity or ""),
        confidence=str(confidence or ""),
        affected_artifact=str(affected_artifact or ""),
        bounded_excerpt=str(bounded_excerpt or "")[:220],
        explanation=str(explanation or "")[:400],
        suggested_review_action=str(suggested_review_action or "")[:200],
        evidence_hashes=dict(evidence_hashes or {}),
        created_at=str(created_at or ""),
    )
