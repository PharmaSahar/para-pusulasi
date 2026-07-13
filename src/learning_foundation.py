"""Slice 3 Phase 1 learning foundation primitives.

This module is intentionally pipeline-agnostic and side-effect free.
It provides typed models, semantic/duplicate helpers, and read-only
quality checkpoint evaluation that never mutates content.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import re
from typing import Any, Literal, Protocol


QUALITY_SCORE_SCHEMA_VERSION = "v1"
LEARNING_SIGNAL_SCHEMA_VERSION = "v1"
RECOMMENDATION_SCHEMA_VERSION = "v1"
VALIDATOR_RESULT_SCHEMA_VERSION = "v1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_text(value: str | None) -> str:
    return " ".join(str(value or "").strip().lower().split())


def tokenize_text(value: str | None) -> list[str]:
    """Simple tokenizer used by deterministic semantic helpers."""
    return re.findall(r"[a-zA-Z0-9ığüşöçİĞÜŞÖÇ]{2,}", _normalize_text(value))


def semantic_similarity_score(left: str | None, right: str | None) -> float:
    """Token-set overlap score in range [0,1]."""
    a = set(tokenize_text(left))
    b = set(tokenize_text(right))
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def content_hash(value: str | None) -> str:
    return hashlib.sha256(_normalize_text(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class QualityScore:
    schema_version: str
    score_name: str
    score_value: float
    status: Literal["pass", "warn", "fail"]
    details: dict[str, Any] = field(default_factory=dict)
    generated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LearningSignal:
    schema_version: str
    signal_type: str
    channel_id: str
    content_id: str
    severity: Literal["low", "medium", "high"]
    payload: dict[str, Any] = field(default_factory=dict)
    generated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Recommendation:
    schema_version: str
    recommendation_type: str
    priority: Literal["low", "medium", "high"]
    rationale: str
    actions: list[str] = field(default_factory=list)
    generated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QualityValidationInput:
    channel_id: str
    content_id: str
    title: str
    script: str
    description: str
    thumbnail_prompt: str
    thumbnail_text: str = ""
    short_script: str = ""
    rendered_video_text: str = ""
    hook_text: str = ""
    cta_text: str = ""
    historical_titles: list[str] = field(default_factory=list)
    historical_scripts: list[str] = field(default_factory=list)
    historical_thumbnail_texts: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ValidatorResult:
    schema_version: str
    channel_id: str
    content_id: str
    checks: list[QualityScore]
    generated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "channel_id": self.channel_id,
            "content_id": self.content_id,
            "checks": [item.to_dict() for item in self.checks],
            "generated_at": self.generated_at,
        }


class ContentQualityEvaluator(Protocol):
    def evaluate(self, payload: QualityValidationInput) -> ValidatorResult:
        ...


class PerformanceAnalyzer(Protocol):
    def analyze(self, analytics_rows: list[dict[str, Any]]) -> list[LearningSignal]:
        ...


class FeedbackCollector(Protocol):
    def collect(self, source_payload: dict[str, Any]) -> list[dict[str, Any]]:
        ...


def _to_status(score_value: float, *, warn_below: float = 0.7, fail_below: float = 0.45) -> Literal["pass", "warn", "fail"]:
    if score_value < fail_below:
        return "fail"
    if score_value < warn_below:
        return "warn"
    return "pass"


def detect_duplicate_text(candidate: str, historical_items: list[str], *, threshold: float = 0.85) -> tuple[bool, float]:
    max_score = 0.0
    for item in historical_items:
        score = semantic_similarity_score(candidate, item)
        if score > max_score:
            max_score = score
    return max_score >= threshold, round(max_score, 4)


def detect_repetitive_opening(script: str, historical_scripts: list[str], *, opening_chars: int = 220, threshold: float = 0.82) -> tuple[bool, float]:
    opening = str(script or "")[:opening_chars]
    baseline = [str(item or "")[:opening_chars] for item in historical_scripts]
    return detect_duplicate_text(opening, baseline, threshold=threshold)


def detect_repeated_cta(cta_text: str, script: str, *, threshold_count: int = 2) -> tuple[bool, int]:
    cta = _normalize_text(cta_text)
    if not cta:
        return False, 0
    count = _normalize_text(script).count(cta)
    return count > threshold_count, count


def detect_unsupported_financial_claims(text: str) -> list[str]:
    checks = [
        r"\bkesin\s+(kazanc|getiri|kar)\b",
        r"\bgaranti\s+(kazanc|getiri|kar)\b",
        r"\b\d+\s*gunde\s*zengin\b",
        r"\byuzde\s*100\s*garanti\b",
    ]
    out: list[str] = []
    normalized = _normalize_text(text)
    for pattern in checks:
        if re.search(pattern, normalized):
            out.append(pattern)
    return out


def detect_unverifiable_insider_information(text: str) -> list[str]:
    checks = [
        r"\biceriden\s+bilgi\b",
        r"\bgizli\s+kaynak\b",
        r"\bkesin\s+duyurulacak\b",
        r"\bresmi\s+aciklanmadan\s+once\b",
    ]
    out: list[str] = []
    normalized = _normalize_text(text)
    for pattern in checks:
        if re.search(pattern, normalized):
            out.append(pattern)
    return out


def detect_guaranteed_return_wording(text: str) -> list[str]:
    checks = [
        r"\bgaranti\s+getiri\b",
        r"\brisksiz\s+kazanc\b",
        r"\bzarar\s+etmezsin\b",
        r"\bkesin\s+yukselir\b",
    ]
    out: list[str] = []
    normalized = _normalize_text(text)
    for pattern in checks:
        if re.search(pattern, normalized):
            out.append(pattern)
    return out


def evaluate_quality_checkpoints(payload: QualityValidationInput) -> ValidatorResult:
    """Run centralized read-only checkpoint scoring.

    The function is deterministic and does not mutate source content.
    """
    checks: list[QualityScore] = []

    title_script = semantic_similarity_score(payload.title, payload.script)
    checks.append(
        QualityScore(
            schema_version=QUALITY_SCORE_SCHEMA_VERSION,
            score_name="title_script_semantic_consistency",
            score_value=round(title_script, 4),
            status=_to_status(title_script),
        )
    )

    title_thumb = semantic_similarity_score(payload.title, payload.thumbnail_prompt)
    checks.append(
        QualityScore(
            schema_version=QUALITY_SCORE_SCHEMA_VERSION,
            score_name="title_thumbnail_consistency",
            score_value=round(title_thumb, 4),
            status=_to_status(title_thumb),
        )
    )

    script_desc = semantic_similarity_score(payload.script, payload.description)
    checks.append(
        QualityScore(
            schema_version=QUALITY_SCORE_SCHEMA_VERSION,
            score_name="script_description_consistency",
            score_value=round(script_desc, 4),
            status=_to_status(script_desc),
        )
    )

    script_short = semantic_similarity_score(payload.script, payload.short_script)
    checks.append(
        QualityScore(
            schema_version=QUALITY_SCORE_SCHEMA_VERSION,
            score_name="script_shorts_consistency",
            score_value=round(script_short, 4),
            status=_to_status(script_short),
        )
    )

    thumb_video = semantic_similarity_score(payload.thumbnail_prompt, payload.rendered_video_text)
    checks.append(
        QualityScore(
            schema_version=QUALITY_SCORE_SCHEMA_VERSION,
            score_name="thumbnail_video_consistency",
            score_value=round(thumb_video, 4),
            status=_to_status(thumb_video),
        )
    )

    hook_len = len(tokenize_text(payload.hook_text or payload.title))
    hook_score = min(1.0, hook_len / 12.0)
    checks.append(
        QualityScore(
            schema_version=QUALITY_SCORE_SCHEMA_VERSION,
            score_name="hook_quality",
            score_value=round(hook_score, 4),
            status=_to_status(hook_score, warn_below=0.6, fail_below=0.35),
            details={"hook_token_count": hook_len},
        )
    )

    dup_script, dup_script_score = detect_duplicate_text(payload.script, payload.historical_scripts, threshold=0.84)
    checks.append(
        QualityScore(
            schema_version=QUALITY_SCORE_SCHEMA_VERSION,
            score_name="duplicate_script_detection",
            score_value=1.0 - dup_script_score,
            status="fail" if dup_script else "pass",
            details={"max_similarity": dup_script_score},
        )
    )

    repetitive_opening, opening_score = detect_repetitive_opening(payload.script, payload.historical_scripts)
    checks.append(
        QualityScore(
            schema_version=QUALITY_SCORE_SCHEMA_VERSION,
            score_name="repetitive_opening_detection",
            score_value=1.0 - opening_score,
            status="fail" if repetitive_opening else "pass",
            details={"opening_similarity": opening_score},
        )
    )

    repeated_cta, cta_count = detect_repeated_cta(payload.cta_text, payload.script)
    checks.append(
        QualityScore(
            schema_version=QUALITY_SCORE_SCHEMA_VERSION,
            score_name="repeated_cta_detection",
            score_value=max(0.0, 1.0 - min(1.0, cta_count / 5.0)),
            status="fail" if repeated_cta else "pass",
            details={"cta_count": cta_count},
        )
    )

    dup_thumb, dup_thumb_score = detect_duplicate_text(payload.thumbnail_text, payload.historical_thumbnail_texts, threshold=0.84)
    checks.append(
        QualityScore(
            schema_version=QUALITY_SCORE_SCHEMA_VERSION,
            score_name="duplicate_thumbnail_text_detection",
            score_value=1.0 - dup_thumb_score,
            status="fail" if dup_thumb else "pass",
            details={"max_similarity": dup_thumb_score},
        )
    )

    dup_title, dup_title_score = detect_duplicate_text(payload.title, payload.historical_titles, threshold=0.84)
    checks.append(
        QualityScore(
            schema_version=QUALITY_SCORE_SCHEMA_VERSION,
            score_name="duplicate_title_detection",
            score_value=1.0 - dup_title_score,
            status="fail" if dup_title else "pass",
            details={"max_similarity": dup_title_score},
        )
    )

    claim_hits = detect_unsupported_financial_claims(payload.script)
    checks.append(
        QualityScore(
            schema_version=QUALITY_SCORE_SCHEMA_VERSION,
            score_name="unsupported_financial_claim_detection",
            score_value=0.0 if claim_hits else 1.0,
            status="fail" if claim_hits else "pass",
            details={"matched_patterns": claim_hits},
        )
    )

    insider_hits = detect_unverifiable_insider_information(payload.script)
    checks.append(
        QualityScore(
            schema_version=QUALITY_SCORE_SCHEMA_VERSION,
            score_name="unverifiable_insider_information_detection",
            score_value=0.0 if insider_hits else 1.0,
            status="fail" if insider_hits else "pass",
            details={"matched_patterns": insider_hits},
        )
    )

    guaranteed_hits = detect_guaranteed_return_wording(payload.script)
    checks.append(
        QualityScore(
            schema_version=QUALITY_SCORE_SCHEMA_VERSION,
            score_name="guaranteed_return_wording_detection",
            score_value=0.0 if guaranteed_hits else 1.0,
            status="fail" if guaranteed_hits else "pass",
            details={"matched_patterns": guaranteed_hits},
        )
    )

    return ValidatorResult(
        schema_version=VALIDATOR_RESULT_SCHEMA_VERSION,
        channel_id=payload.channel_id,
        content_id=payload.content_id,
        checks=checks,
    )
