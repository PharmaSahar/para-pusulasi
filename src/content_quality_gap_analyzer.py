from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Any


CONTENT_QUALITY_GAP_SCHEMA_VERSION = "v1"
CONTENT_QUALITY_GAP_ANALYZER_VERSION = "v1"
CONTENT_QUALITY_GAP_RESULTS_PATH = Path("logs/content_quality_gap_analysis.jsonl")

_SECRET_PATTERN = re.compile(
    r"(api[_-]?key|client[_-]?secret|oauth|access[_-]?token|refresh[_-]?token|password|cookie|authorization\s*:|bearer\s+)",
    re.IGNORECASE,
)
_FINANCE_UNSAFE_PATTERN = re.compile(
    r"(garanti\s+getiri|garanti\s+kazan[cç]|x\s*kat\s*kazanc|kesin\s+kazanc|insider\s+sirr|hemen\s+al|pump|zengin\s+ol)",
    re.IGNORECASE,
)
_FINANCE_CONTEXT_PATTERN = re.compile(
    r"(finans|yatirim|birikim|portfoy|kripto|coin|borsa|getiri|risk|maas|gelir)",
    re.IGNORECASE,
)
_CTA_PATTERN = re.compile(r"(abone ol|yorum yap|begen|paylas|bildirim)", re.IGNORECASE)


class ContentQualityGapValidationError(ValueError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(name: str, value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ContentQualityGapValidationError(f"missing_field:{name}")
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception as exc:
        raise ContentQualityGapValidationError(f"invalid_datetime:{name}") from exc
    return text


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _safe_json_hash(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return _sha(blob)


def _bounded_text(value: str | None, *, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if _SECRET_PATTERN.search(text):
        raise ContentQualityGapValidationError("secret_like_content_detected")
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _safe_div(a: float, b: float) -> float:
    if not b:
        return 0.0
    return float(a) / float(b)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9ığüşöç]+", str(value or "").lower())


def _keyword_overlap(left: str, right: str) -> float:
    a = set(_tokens(left))
    b = set(_tokens(right))
    if not a or not b:
        return 0.0
    return _safe_div(len(a & b), len(a | b))


@dataclass(frozen=True)
class QualityAnalysisInput:
    content_id: str
    channel_id: str
    content_type: str
    niche: str
    topic: str
    title: str
    thumbnail_prompt: str
    script: str
    description: str
    tags: tuple[str, ...]
    hashtags: tuple[str, ...]
    playlist: str
    cards: tuple[str, ...]
    end_screens: tuple[str, ...]
    short_title: str
    short_script: str
    review_queue: dict[str, Any]
    analytics: dict[str, Any]
    channel_profile: dict[str, Any]
    audience_profile: dict[str, Any]

    def __post_init__(self) -> None:
        for key, value in (
            ("content_id", self.content_id),
            ("channel_id", self.channel_id),
            ("content_type", self.content_type),
            ("topic", self.topic),
            ("title", self.title),
            ("thumbnail_prompt", self.thumbnail_prompt),
            ("script", self.script),
            ("description", self.description),
        ):
            if not str(value).strip():
                raise ContentQualityGapValidationError(f"missing_field:{key}")
            _bounded_text(str(value), limit=1200)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["tags"] = list(self.tags)
        payload["hashtags"] = list(self.hashtags)
        payload["cards"] = list(self.cards)
        payload["end_screens"] = list(self.end_screens)
        return payload


@dataclass(frozen=True)
class QualityGap:
    gap_id: str
    category: str
    severity: str
    confidence: float
    affected_component: str
    root_cause: str
    evidence: tuple[str, ...]
    expected_effect: str
    estimated_priority: str
    recommended_future_action: str
    advisory_only: bool

    def __post_init__(self) -> None:
        if not self.gap_id:
            raise ContentQualityGapValidationError("missing_field:gap_id")
        if not self.category:
            raise ContentQualityGapValidationError("missing_field:category")
        if self.severity not in {"low", "medium", "high", "critical"}:
            raise ContentQualityGapValidationError("invalid_field:severity")
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ContentQualityGapValidationError("invalid_field:confidence")
        if not self.affected_component:
            raise ContentQualityGapValidationError("missing_field:affected_component")
        if not self.root_cause:
            raise ContentQualityGapValidationError("missing_field:root_cause")
        if not self.expected_effect:
            raise ContentQualityGapValidationError("missing_field:expected_effect")
        if self.estimated_priority not in {"p0", "p1", "p2", "p3"}:
            raise ContentQualityGapValidationError("invalid_field:estimated_priority")
        if not self.recommended_future_action:
            raise ContentQualityGapValidationError("missing_field:recommended_future_action")
        if not self.advisory_only:
            raise ContentQualityGapValidationError("invalid_field:advisory_only")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence"] = list(self.evidence)
        return payload


@dataclass(frozen=True)
class DimensionScore:
    score: float
    confidence: float
    why: str
    evidence: tuple[str, ...]
    possible_causes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.score < 0.0 or self.score > 1.0:
            raise ContentQualityGapValidationError("invalid_field:score")
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ContentQualityGapValidationError("invalid_field:confidence")
        if not self.why:
            raise ContentQualityGapValidationError("missing_field:why")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence"] = list(self.evidence)
        payload["possible_causes"] = list(self.possible_causes)
        return payload


@dataclass(frozen=True)
class QualityScorecard:
    hook: DimensionScore
    narrative: DimensionScore
    retention: DimensionScore
    ctr: DimensionScore
    thumbnail: DimensionScore
    seo: DimensionScore
    discovery: DimensionScore
    consistency: DimensionScore
    finance_safety: DimensionScore
    educational_quality: DimensionScore
    maintainability: DimensionScore
    overall_confidence: float

    def __post_init__(self) -> None:
        if self.overall_confidence < 0.0 or self.overall_confidence > 1.0:
            raise ContentQualityGapValidationError("invalid_field:overall_confidence")

    def to_dict(self) -> dict[str, Any]:
        return {
            "hook": self.hook.to_dict(),
            "narrative": self.narrative.to_dict(),
            "retention": self.retention.to_dict(),
            "ctr": self.ctr.to_dict(),
            "thumbnail": self.thumbnail.to_dict(),
            "seo": self.seo.to_dict(),
            "discovery": self.discovery.to_dict(),
            "consistency": self.consistency.to_dict(),
            "finance_safety": self.finance_safety.to_dict(),
            "educational_quality": self.educational_quality.to_dict(),
            "maintainability": self.maintainability.to_dict(),
            "overall_confidence": self.overall_confidence,
        }


@dataclass(frozen=True)
class ContentQualityGapResult:
    schema_version: str
    analyzer_version: str
    analysis_id: str
    run_id: str
    content_id: str
    channel_id: str
    content_type: str
    topic_hash: str
    scorecard: dict[str, Any]
    gaps: tuple[dict[str, Any], ...]
    root_causes: tuple[str, ...]
    calibration_ready: bool
    advisory_only: bool
    pipeline_output_changed: bool
    created_at: str

    def __post_init__(self) -> None:
        if self.schema_version != CONTENT_QUALITY_GAP_SCHEMA_VERSION:
            raise ContentQualityGapValidationError("invalid_field:schema_version")
        if self.analyzer_version != CONTENT_QUALITY_GAP_ANALYZER_VERSION:
            raise ContentQualityGapValidationError("invalid_field:analyzer_version")
        if not self.analysis_id:
            raise ContentQualityGapValidationError("missing_field:analysis_id")
        if not self.content_id:
            raise ContentQualityGapValidationError("missing_field:content_id")
        if not self.channel_id:
            raise ContentQualityGapValidationError("missing_field:channel_id")
        if not self.topic_hash:
            raise ContentQualityGapValidationError("missing_field:topic_hash")
        if not self.advisory_only:
            raise ContentQualityGapValidationError("invalid_field:advisory_only")
        if self.pipeline_output_changed:
            raise ContentQualityGapValidationError("invalid_field:pipeline_output_changed")
        _parse_iso("created_at", self.created_at)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["gaps"] = [dict(item) for item in self.gaps]
        payload["root_causes"] = list(self.root_causes)
        return payload


@dataclass(frozen=True)
class ContentQualityGapStorageRow:
    schema_version: str
    analysis_id: str
    run_id: str
    content_id: str
    channel_id: str
    content_type: str
    topic_hash: str
    gap_count: int
    high_severity_gap_count: int
    root_causes: tuple[str, ...]
    score_summary: dict[str, float]
    advisory_only: bool
    pipeline_output_changed: bool
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["root_causes"] = list(self.root_causes)
        return payload


def _sentence_list(text: str) -> list[str]:
    raw = [item.strip() for item in re.split(r"[.!?\n]+", str(text or ""))]
    return [item for item in raw if item]


def _first_chunk(text: str, chars: int = 260) -> str:
    return str(text or "")[:chars]


def _last_chunk(text: str, chars: int = 260) -> str:
    value = str(text or "")
    if len(value) <= chars:
        return value
    return value[-chars:]


def analyze_script(input_data: QualityAnalysisInput) -> dict[str, Any]:
    script = str(input_data.script)
    opening = _first_chunk(script, 260)
    first_30 = _first_chunk(script, 520)
    ending = _last_chunk(script, 320)

    sentences = _sentence_list(script)
    tokens = _tokens(script)
    unique_ratio = _safe_div(len(set(tokens)), len(tokens))
    avg_sentence_len = _safe_div(sum(len(_tokens(item)) for item in sentences), max(1, len(sentences)))

    hook_quality = _clamp01(
        0.25
        + (0.2 if "?" in opening else 0.0)
        + (0.15 if any(ch.isdigit() for ch in opening) else 0.0)
        + (0.2 if any(w in opening.lower() for w in ["dikkat", "neden", "şok", "sok"]) else 0.0)
        + (0.2 if len(opening) >= 120 else 0.0)
    )
    opening_strength = _clamp01(0.3 + (0.3 if len(opening) >= 120 else 0.0) + (0.2 if "hook" in opening.lower() else 0.0))
    first_30_strength = _clamp01(0.2 + (0.35 if len(first_30) >= 300 else 0.0) + (0.2 if "neden" in first_30.lower() else 0.0))

    structure_markers = ["giriş", "giris", "1.", "2.", "3.", "sonuç", "sonuc", "özet", "ozet"]
    narrative_structure = _score_from_bool_hits([marker in script.lower() for marker in structure_markers])

    pacing = _clamp01(1.0 - min(1.0, abs(avg_sentence_len - 16.0) / 20.0))
    repetition = _clamp01(1.0 - unique_ratio)
    clarity = _clamp01(0.35 + (0.45 if 8 <= avg_sentence_len <= 22 else 0.0) + (0.2 if unique_ratio > 0.45 else 0.0))

    educational_depth = _score_from_bool_hits([
        "örnek" in script.lower() or "ornek" in script.lower(),
        "neden" in script.lower(),
        "nasıl" in script.lower() or "nasil" in script.lower(),
        any(ch.isdigit() for ch in script),
    ])
    information_density = _clamp01(0.2 + min(0.6, _safe_div(len(tokens), 1600.0)) + (0.2 if any(ch.isdigit() for ch in script) else 0.0))
    emotional_pacing = _score_from_bool_hits([term in script.lower() for term in ["risk", "fırsat", "firsat", "dikkat", "acil"]])
    cta_timing = _clamp01(0.2 + (0.5 if _CTA_PATTERN.search(_last_chunk(script, 420)) else 0.0) + (0.3 if _CTA_PATTERN.search(script) else 0.0))
    ending_quality = _score_from_bool_hits([term in ending.lower() for term in ["özet", "ozet", "sonraki", "teaser", "cta"]])

    return {
        "hook_quality": hook_quality,
        "opening_strength": opening_strength,
        "first_30_seconds": first_30_strength,
        "narrative_structure": narrative_structure,
        "pacing": pacing,
        "repetition": repetition,
        "clarity": clarity,
        "educational_depth": educational_depth,
        "information_density": information_density,
        "emotional_pacing": emotional_pacing,
        "cta_timing": cta_timing,
        "ending_quality": ending_quality,
        "evidence": {
            "opening_excerpt": _bounded_text(opening, limit=180),
            "ending_excerpt": _bounded_text(ending, limit=180),
            "unique_ratio": unique_ratio,
            "avg_sentence_len": avg_sentence_len,
        },
    }


def _score_from_bool_hits(values: list[bool]) -> float:
    if not values:
        return 0.0
    return _clamp01(_safe_div(sum(1 for v in values if v), len(values)))


def analyze_title(input_data: QualityAnalysisInput) -> dict[str, Any]:
    title = str(input_data.title)
    topic = str(input_data.topic)

    ctr_psychology = _score_from_bool_hits([
        "?" in title,
        any(ch.isdigit() for ch in title),
        any(term in title.lower() for term in ["neden", "nasıl", "nasil", "gerçek", "gercek", "şok", "sok"]),
    ])
    search_intent = _clamp01(0.4 + 0.6 * _keyword_overlap(title, topic))
    browse_intent = _score_from_bool_hits([len(title) <= 68, any(term in title.lower() for term in ["hata", "risk", "fırsat", "firsat", "rehber"])])
    suggest_intent = _score_from_bool_hits([any(term in title.lower() for term in ["vs", "karşı", "karsi", "neden", "nasıl", "nasil"])])
    keyword_quality = _score_from_bool_hits([len(_tokens(title)) >= 4, _keyword_overlap(title, input_data.description) > 0.12])
    promise_accuracy = _clamp01(0.2 + 0.8 * _keyword_overlap(title, input_data.script))
    clickbait_risk = _score_from_bool_hits([any(term in title.lower() for term in ["inanılmaz", "inanilmaz", "şok", "sok", "garanti", "kesin", "pump", "zengin"])])
    sensationalism = clickbait_risk
    authority = _score_from_bool_hits([any(term in title.lower() for term in ["analiz", "veri", "rehber", "strateji", "kanıt", "kanit"])])
    readability = _score_from_bool_hits([20 <= len(title) <= 72, len(_tokens(title)) >= 4])
    length = _clamp01(1.0 - min(1.0, abs(len(title) - 52) / 52.0))
    emotional_trigger = _score_from_bool_hits([any(term in title.lower() for term in ["risk", "fırsat", "firsat", "tehlike", "uyarı", "uyari"])])

    return {
        "ctr_psychology": ctr_psychology,
        "search_intent": search_intent,
        "browse_intent": browse_intent,
        "suggest_intent": suggest_intent,
        "keyword_quality": keyword_quality,
        "promise_accuracy": promise_accuracy,
        "clickbait_risk": clickbait_risk,
        "sensationalism": sensationalism,
        "authority": authority,
        "readability": readability,
        "length": length,
        "emotional_trigger": emotional_trigger,
        "evidence": {
            "title_excerpt": _bounded_text(title, limit=120),
            "title_len": len(title),
            "title_topic_overlap": _keyword_overlap(title, topic),
        },
    }


def analyze_thumbnail_metadata(input_data: QualityAnalysisInput) -> dict[str, Any]:
    thumb = str(input_data.thumbnail_prompt)
    title = str(input_data.title)

    emotional_trigger = _score_from_bool_hits([any(term in thumb.lower() for term in ["dramatic", "warning", "urgent", "shock", "risk", "fear", "hope"])])
    contrast = _score_from_bool_hits([any(term in thumb.lower() for term in ["contrast", "high contrast", "bold", "vivid"])])
    hierarchy = _score_from_bool_hits([any(term in thumb.lower() for term in ["focus", "single object", "main subject", "hierarchy"])])
    text_density = _score_from_bool_hits(["max 2" in thumb.lower() or "short text" in thumb.lower() or "minimal text" in thumb.lower()])
    object_focus = _score_from_bool_hits(["object" in thumb.lower() or "single" in thumb.lower()])
    face_usage = _score_from_bool_hits(["face" in thumb.lower() or "portrait" in thumb.lower() or "expression" in thumb.lower()])
    trust = _score_from_bool_hits([any(term in thumb.lower() for term in ["trusted", "educational", "clean", "professional"])])
    urgency = _score_from_bool_hits([any(term in thumb.lower() for term in ["urgent", "warning", "alert", "critical"])])
    misleading_risk = _score_from_bool_hits([any(term in thumb.lower() for term in ["luxury", "instant rich", "guaranteed", "rocket", "millionaire"])])
    title_consistency = _clamp01(_keyword_overlap(thumb, title) * 1.4)

    return {
        "emotional_trigger": emotional_trigger,
        "contrast": contrast,
        "information_hierarchy": hierarchy,
        "text_density": text_density,
        "object_focus": object_focus,
        "face_usage": face_usage,
        "trust": trust,
        "urgency": urgency,
        "misleading_risk": misleading_risk,
        "thumbnail_title_consistency": title_consistency,
        "evidence": {
            "thumbnail_excerpt": _bounded_text(thumb, limit=140),
            "title_overlap": _keyword_overlap(thumb, title),
        },
    }


def analyze_shorts(input_data: QualityAnalysisInput) -> dict[str, Any]:
    short_script = str(input_data.short_script)
    text = short_script if short_script.strip() else str(input_data.script)[:420]

    beginning = _first_chunk(text, 120)
    ending = _last_chunk(text, 120)
    hook = _score_from_bool_hits(["?" in beginning, any(term in beginning.lower() for term in ["neden", "dikkat", "şok", "sok"])])
    beginning_completeness = _score_from_bool_hits([len(beginning) >= 40, beginning.endswith((".", "!", "?"))])
    context = _score_from_bool_hits([any(term in text.lower() for term in ["çünkü", "cunku", "bu yüzden", "because"])])
    payoff = _score_from_bool_hits([any(term in ending.lower() for term in ["sonuç", "sonuc", "çıkarım", "cikarim", "özet", "ozet"])])
    ending_quality = _score_from_bool_hits([ending.endswith((".", "!", "?")), any(term in ending.lower() for term in ["devam", "sonraki", "teaser"])])
    looping = _score_from_bool_hits([any(term in ending.lower() for term in ["devamı", "devami", "bir sonraki", "döngü", "dongu"])])
    retention_potential = _clamp01((hook + context + payoff) / 3.0)
    clipping_quality = _score_from_bool_hits([len(_tokens(text)) >= 18, len(_tokens(text)) <= 150])

    return {
        "hook": hook,
        "beginning_completeness": beginning_completeness,
        "context": context,
        "payoff": payoff,
        "ending": ending_quality,
        "looping": looping,
        "retention_potential": retention_potential,
        "clipping_quality": clipping_quality,
        "evidence": {
            "short_opening": _bounded_text(beginning, limit=120),
            "short_ending": _bounded_text(ending, limit=120),
        },
    }


def analyze_seo(input_data: QualityAnalysisInput) -> dict[str, Any]:
    description = str(input_data.description)
    title = str(input_data.title)
    tags = [str(tag).strip().lower() for tag in input_data.tags if str(tag).strip()]
    hashtags = [str(tag).strip().lower() for tag in input_data.hashtags if str(tag).strip()]

    title_keyword_strategy = _score_from_bool_hits([len(_tokens(title)) >= 4, any(token in description.lower() for token in _tokens(title)[:4])])
    description_completeness = _score_from_bool_hits([len(description) >= 180, description.count("\n") >= 1])
    tags_quality = _score_from_bool_hits([len(tags) >= 8, len(set(tags)) >= max(1, len(tags) - 2)])
    hashtags_quality = _score_from_bool_hits([len(hashtags) >= 3])
    playlist_relevance = _score_from_bool_hits([bool(str(input_data.playlist or "").strip())])
    cards_quality = _score_from_bool_hits([len(input_data.cards) >= 1])
    end_screens_quality = _score_from_bool_hits([len(input_data.end_screens) >= 1])
    internal_linking = _score_from_bool_hits([any(term in description.lower() for term in ["önceki video", "onceki video", "sonraki video", "izle"])])
    suggested_support = _score_from_bool_hits([_keyword_overlap(title, description) > 0.12, len(tags) >= 6])

    return {
        "title_keyword_strategy": title_keyword_strategy,
        "description_completeness": description_completeness,
        "tags": tags_quality,
        "hashtags": hashtags_quality,
        "playlist_relevance": playlist_relevance,
        "cards": cards_quality,
        "end_screens": end_screens_quality,
        "internal_linking": internal_linking,
        "suggested_support": suggested_support,
        "evidence": {
            "description_len": len(description),
            "tags_count": len(tags),
            "hashtags_count": len(hashtags),
        },
    }


def analyze_channel_consistency(input_data: QualityAnalysisInput) -> dict[str, Any]:
    profile = dict(input_data.channel_profile or {})
    audience = dict(input_data.audience_profile or {})

    tone = str(profile.get("tone") or input_data.niche or "").lower()
    authority_level = str(profile.get("authority_level") or "medium").lower()
    educational_level = str(audience.get("experience_level") or "intermediate").lower()

    content_text = " ".join([
        input_data.title,
        input_data.script[:600],
        input_data.description[:240],
    ]).lower()

    niche_alignment = _score_from_bool_hits([str(input_data.niche or "").lower() in content_text])
    tone_alignment = _score_from_bool_hits([tone in content_text if tone else True])
    authority_alignment = _score_from_bool_hits([authority_level in content_text if authority_level else True, "veri" in content_text or "analiz" in content_text])
    educational_alignment = _score_from_bool_hits([educational_level in content_text if educational_level else True])
    branding_alignment = _score_from_bool_hits([str(input_data.channel_id).lower().replace("_", " ").split()[0] in content_text])

    return {
        "channel_profile_alignment": niche_alignment,
        "audience_profile_alignment": educational_alignment,
        "educational_level_alignment": educational_alignment,
        "authority_level_alignment": authority_alignment,
        "tone_alignment": tone_alignment,
        "branding_alignment": branding_alignment,
        "niche_alignment": niche_alignment,
        "evidence": {
            "niche": str(input_data.niche),
            "tone": tone,
            "authority": authority_level,
            "educational_level": educational_level,
        },
    }


def analyze_content_consistency(input_data: QualityAnalysisInput) -> dict[str, Any]:
    overlaps = {
        "topic_title": _keyword_overlap(input_data.topic, input_data.title),
        "title_thumbnail": _keyword_overlap(input_data.title, input_data.thumbnail_prompt),
        "title_script": _keyword_overlap(input_data.title, input_data.script),
        "script_description": _keyword_overlap(input_data.script, input_data.description),
        "script_shorts": _keyword_overlap(input_data.script, input_data.short_script or input_data.short_title),
        "description_seo": _keyword_overlap(input_data.description, " ".join(list(input_data.tags) + list(input_data.hashtags))),
    }

    consistency_score = _clamp01(_safe_div(sum(overlaps.values()), max(1, len(overlaps))))

    return {
        "consistency_score": consistency_score,
        "overlaps": overlaps,
        "evidence": {
            "min_overlap": min(overlaps.values()) if overlaps else 0.0,
            "max_overlap": max(overlaps.values()) if overlaps else 0.0,
        },
    }


def infer_root_causes(symptoms: set[str]) -> list[str]:
    causes: list[str] = []

    mapping = {
        "weak_hook": "Weak hook",
        "thumbnail_mismatch": "Thumbnail mismatch",
        "promise_mismatch": "Promise mismatch",
        "audience_mismatch": "Audience mismatch",
        "template_repetition": "Template repetition",
        "generic_opening": "Overly generic opening",
        "poor_pacing": "Poor pacing",
        "wrong_cta_timing": "Wrong CTA timing",
        "weak_search_intent": "Weak search intent",
        "poor_browse_optimization": "Poor browse optimization",
        "weak_curiosity": "Weak curiosity",
        "weak_payoff": "Weak payoff",
        "insufficient_authority": "Insufficient authority",
        "low_educational_depth": "Low educational depth",
        "topic_saturation": "Topic saturation",
        "unsafe_finance_claim": "Unsupported claims",
    }

    for key, label in mapping.items():
        if key in symptoms:
            causes.append(label)

    if not causes:
        return []
    return sorted(set(causes))


def _make_gap(
    *,
    analysis_id: str,
    category: str,
    severity: str,
    confidence: float,
    affected_component: str,
    root_cause: str,
    evidence: list[str],
    expected_effect: str,
    estimated_priority: str,
    recommended_future_action: str,
) -> QualityGap:
    gap_seed = {
        "analysis_id": analysis_id,
        "category": category,
        "affected_component": affected_component,
        "root_cause": root_cause,
        "evidence": evidence,
    }
    gap_id = f"gap_{_safe_json_hash(gap_seed)[:18]}"
    return QualityGap(
        gap_id=gap_id,
        category=category,
        severity=severity,
        confidence=_clamp01(confidence),
        affected_component=affected_component,
        root_cause=root_cause,
        evidence=tuple(_bounded_text(item, limit=160) for item in evidence[:4]),
        expected_effect=expected_effect,
        estimated_priority=estimated_priority,
        recommended_future_action=recommended_future_action,
        advisory_only=True,
    )


def _dimension_from_score(score: float, confidence: float, why: str, evidence: list[str], causes: list[str]) -> DimensionScore:
    return DimensionScore(
        score=_clamp01(score),
        confidence=_clamp01(confidence),
        why=_bounded_text(why, limit=220),
        evidence=tuple(_bounded_text(item, limit=160) for item in evidence[:4]),
        possible_causes=tuple(causes[:5]),
    )


def analyze_content_quality_gaps(
    *,
    input_data: QualityAnalysisInput,
    run_id: str,
) -> ContentQualityGapResult:
    script = analyze_script(input_data)
    title = analyze_title(input_data)
    thumbnail = analyze_thumbnail_metadata(input_data)
    shorts = analyze_shorts(input_data)
    seo = analyze_seo(input_data)
    channel = analyze_channel_consistency(input_data)
    consistency = analyze_content_consistency(input_data)

    seed = {
        "run_id": run_id,
        "content_id": input_data.content_id,
        "channel_id": input_data.channel_id,
        "topic": input_data.topic,
        "title": input_data.title,
        "thumbnail_prompt": input_data.thumbnail_prompt,
        "script_hash": _sha(input_data.script),
    }
    analysis_id = f"cqga_{_safe_json_hash(seed)[:20]}"

    symptoms: set[str] = set()
    gaps: list[QualityGap] = []

    opening_excerpt = str((script.get("evidence") or {}).get("opening_excerpt") or "")
    weak_opening_marker = any(term in opening_excerpt.lower() for term in ["merhaba", "sevgili", "bugun bu videoda"])
    if (script["hook_quality"] <= 0.45 and weak_opening_marker) or script["opening_strength"] < 0.4 or (shorts["hook"] < 0.2 and weak_opening_marker):
        symptoms.update({"weak_hook", "generic_opening"})
        gaps.append(
            _make_gap(
                analysis_id=analysis_id,
                category="SCRIPT_HOOK",
                severity="high",
                confidence=0.88,
                affected_component="script",
                root_cause="Weak hook",
                evidence=[str(script["evidence"]["opening_excerpt"]), "hook_quality<0.45"],
                expected_effect="lower early retention",
                estimated_priority="p0",
                recommended_future_action="strengthen first 2 sentences with specific tension and promise",
            )
        )

    if script["repetition"] >= 0.35:
        symptoms.add("template_repetition")
        gaps.append(
            _make_gap(
                analysis_id=analysis_id,
                category="SCRIPT_REPETITION",
                severity="medium",
                confidence=0.82,
                affected_component="script",
                root_cause="Template repetition",
                evidence=[f"repetition={script['repetition']:.3f}", f"unique_ratio={script['evidence']['unique_ratio']:.3f}"],
                expected_effect="reduced viewer engagement",
                estimated_priority="p1",
                recommended_future_action="increase narrative variation and reduce repeated sentence templates",
            )
        )

    if script["pacing"] < 0.4:
        symptoms.add("poor_pacing")

    title_mismatch_signal = (
        title["promise_accuracy"] <= 0.3
        and (title["clickbait_risk"] >= 0.3 or title["sensationalism"] >= 0.3)
    )
    if title_mismatch_signal:
        symptoms.add("promise_mismatch")
        gaps.append(
            _make_gap(
                analysis_id=analysis_id,
                category="TITLE_PROMISE_MISMATCH",
                severity="high",
                confidence=0.86,
                affected_component="title",
                root_cause="Promise mismatch",
                evidence=[f"promise_accuracy={title['promise_accuracy']:.3f}", str(title["evidence"]["title_excerpt"])],
                expected_effect="lower CTR-to-retention transfer",
                estimated_priority="p0",
                recommended_future_action="align title claim with script core narrative payoff",
            )
        )

    thumbnail_mismatch_signal = (
        thumbnail["thumbnail_title_consistency"] < 0.18
        and thumbnail["misleading_risk"] < 0.5
        and (thumbnail["trust"] < 0.5 or thumbnail["contrast"] < 0.5)
    )
    if thumbnail_mismatch_signal:
        symptoms.add("thumbnail_mismatch")
        gaps.append(
            _make_gap(
                analysis_id=analysis_id,
                category="THUMBNAIL_TITLE_MISMATCH",
                severity="high",
                confidence=0.84,
                affected_component="thumbnail",
                root_cause="Thumbnail mismatch",
                evidence=[f"consistency={thumbnail['thumbnail_title_consistency']:.3f}", str(thumbnail["evidence"]["thumbnail_excerpt"])],
                expected_effect="CTR degradation",
                estimated_priority="p0",
                recommended_future_action="enforce shared semantic anchor between title and thumbnail concept",
            )
        )

    if thumbnail["misleading_risk"] > 0.5:
        symptoms.add("promise_mismatch")
        gaps.append(
            _make_gap(
                analysis_id=analysis_id,
                category="THUMBNAIL_MISLEADING_RISK",
                severity="critical",
                confidence=0.9,
                affected_component="thumbnail",
                root_cause="Promise mismatch",
                evidence=[f"misleading_risk={thumbnail['misleading_risk']:.3f}"],
                expected_effect="trust erosion and policy risk",
                estimated_priority="p0",
                recommended_future_action="remove exaggerated visual claims and maintain factual alignment",
            )
        )

    seo_incomplete_signal = (
        seo["description_completeness"] < 0.45
        and (seo["tags"] < 0.45 or seo["hashtags"] < 0.45)
    )
    if seo_incomplete_signal:
        symptoms.add("weak_search_intent")
        gaps.append(
            _make_gap(
                analysis_id=analysis_id,
                category="SEO_INCOMPLETE",
                severity="medium",
                confidence=0.82,
                affected_component="seo",
                root_cause="Weak search intent",
                evidence=[
                    f"title_keyword_strategy={seo['title_keyword_strategy']:.3f}",
                    f"description_completeness={seo['description_completeness']:.3f}",
                ],
                expected_effect="lower search discoverability",
                estimated_priority="p1",
                recommended_future_action="expand description intent coverage and keyword consistency",
            )
        )

    if consistency["consistency_score"] < 0.12 and title_mismatch_signal and thumbnail_mismatch_signal and thumbnail["misleading_risk"] < 0.5:
        symptoms.add("topic_saturation")
        gaps.append(
            _make_gap(
                analysis_id=analysis_id,
                category="CONTENT_FLOW_INCONSISTENT",
                severity="high",
                confidence=0.83,
                affected_component="consistency",
                root_cause="Promise mismatch",
                evidence=[f"consistency_score={consistency['consistency_score']:.3f}"],
                expected_effect="drop-off after click",
                estimated_priority="p0",
                recommended_future_action="align topic-title-thumbnail-script-description chain with one intent",
            )
        )

    all_text = " ".join([input_data.title, input_data.script, input_data.thumbnail_prompt])
    finance_context = _FINANCE_CONTEXT_PATTERN.search(all_text) is not None
    finance_unsafe = (_FINANCE_UNSAFE_PATTERN.search(all_text) is not None) and finance_context
    if finance_unsafe:
        symptoms.add("unsafe_finance_claim")
        gaps.append(
            _make_gap(
                analysis_id=analysis_id,
                category="FINANCE_SAFETY",
                severity="critical",
                confidence=0.94,
                affected_component="script",
                root_cause="Unsupported claims",
                evidence=["unsafe finance phrase detected"],
                expected_effect="compliance and trust risk",
                estimated_priority="p0",
                recommended_future_action="replace certainty claims with uncertainty-labeled educational framing",
            )
        )

    root_causes = infer_root_causes(symptoms)

    hook_score = _clamp01((script["hook_quality"] + shorts["hook"] + title["ctr_psychology"]) / 3.0)
    narrative_score = _clamp01((script["narrative_structure"] + script["clarity"] + script["educational_depth"]) / 3.0)
    retention_score = _clamp01((script["first_30_seconds"] + script["pacing"] + shorts["retention_potential"]) / 3.0)
    ctr_score = _clamp01((title["ctr_psychology"] + title["browse_intent"] + thumbnail["emotional_trigger"]) / 3.0)
    thumbnail_score = _clamp01((thumbnail["contrast"] + thumbnail["information_hierarchy"] + thumbnail["thumbnail_title_consistency"] + thumbnail["trust"]) / 4.0)
    seo_score = _clamp01((seo["title_keyword_strategy"] + seo["description_completeness"] + seo["tags"] + seo["hashtags"] + seo["suggested_support"]) / 5.0)
    discovery_score = _clamp01((seo["playlist_relevance"] + seo["cards"] + seo["end_screens"] + seo["internal_linking"]) / 4.0)
    consistency_score = _clamp01((consistency["consistency_score"] + channel["niche_alignment"] + channel["tone_alignment"]) / 3.0)
    finance_safety_score = _clamp01(0.0 if finance_unsafe else (0.55 + 0.45 * script["educational_depth"]))
    educational_quality_score = _clamp01((script["educational_depth"] + script["information_density"] + narrative_score) / 3.0)
    maintainability_score = _clamp01(1.0 - script["repetition"])

    scorecard = QualityScorecard(
        hook=_dimension_from_score(hook_score, 0.86, "Hook performance from title/script/shorts opening", [str(script["evidence"]["opening_excerpt"])], root_causes),
        narrative=_dimension_from_score(narrative_score, 0.84, "Narrative structure and clarity", [f"structure={script['narrative_structure']:.3f}"], root_causes),
        retention=_dimension_from_score(retention_score, 0.84, "First 30s + pacing + shorts retention signals", [f"first_30={script['first_30_seconds']:.3f}"], root_causes),
        ctr=_dimension_from_score(ctr_score, 0.82, "Title CTR psychology with thumbnail trigger consistency", [f"ctr_psychology={title['ctr_psychology']:.3f}"], root_causes),
        thumbnail=_dimension_from_score(thumbnail_score, 0.8, "Thumbnail metadata quality and consistency", [f"title_consistency={thumbnail['thumbnail_title_consistency']:.3f}"], root_causes),
        seo=_dimension_from_score(seo_score, 0.83, "SEO completeness and keyword support", [f"description_len={seo['evidence']['description_len']}"], root_causes),
        discovery=_dimension_from_score(discovery_score, 0.8, "Playlist/cards/end-screen/internal linking readiness", [f"cards={len(input_data.cards)}"], root_causes),
        consistency=_dimension_from_score(consistency_score, 0.85, "Cross-component semantic consistency", [f"consistency_score={consistency['consistency_score']:.3f}"], root_causes),
        finance_safety=_dimension_from_score(finance_safety_score, 0.92, "Finance safety and uncertainty controls", ["unsafe_phrase_detected" if finance_unsafe else "no_unsafe_phrase_detected"], root_causes),
        educational_quality=_dimension_from_score(educational_quality_score, 0.85, "Educational depth, information density, narrative", [f"educational_depth={script['educational_depth']:.3f}"], root_causes),
        maintainability=_dimension_from_score(maintainability_score, 0.78, "Template repetition and readability sustainability", [f"repetition={script['repetition']:.3f}"], root_causes),
        overall_confidence=_clamp01(_safe_div(sum([0.86, 0.84, 0.84, 0.82, 0.8, 0.83, 0.8, 0.85, 0.92, 0.85, 0.78]), 11.0)),
    )

    return ContentQualityGapResult(
        schema_version=CONTENT_QUALITY_GAP_SCHEMA_VERSION,
        analyzer_version=CONTENT_QUALITY_GAP_ANALYZER_VERSION,
        analysis_id=analysis_id,
        run_id=str(run_id or ""),
        content_id=input_data.content_id,
        channel_id=input_data.channel_id,
        content_type=input_data.content_type,
        topic_hash=_sha(input_data.topic),
        scorecard=scorecard.to_dict(),
        gaps=tuple(item.to_dict() for item in sorted(gaps, key=lambda gap: gap.gap_id)),
        root_causes=tuple(root_causes),
        calibration_ready=True,
        advisory_only=True,
        pipeline_output_changed=False,
        created_at=_now_iso(),
    )


def build_storage_row(result: ContentQualityGapResult) -> ContentQualityGapStorageRow:
    scorecard = dict(result.scorecard or {})

    def _extract(name: str) -> float:
        node = dict(scorecard.get(name) or {})
        return float(node.get("score", 0.0) or 0.0)

    gaps = list(result.gaps)
    high_count = sum(1 for item in gaps if str(item.get("severity") or "") in {"high", "critical"})

    return ContentQualityGapStorageRow(
        schema_version=CONTENT_QUALITY_GAP_SCHEMA_VERSION,
        analysis_id=result.analysis_id,
        run_id=result.run_id,
        content_id=result.content_id,
        channel_id=result.channel_id,
        content_type=result.content_type,
        topic_hash=result.topic_hash,
        gap_count=len(gaps),
        high_severity_gap_count=high_count,
        root_causes=result.root_causes,
        score_summary={
            "hook": _extract("hook"),
            "narrative": _extract("narrative"),
            "retention": _extract("retention"),
            "ctr": _extract("ctr"),
            "thumbnail": _extract("thumbnail"),
            "seo": _extract("seo"),
            "discovery": _extract("discovery"),
            "consistency": _extract("consistency"),
            "finance_safety": _extract("finance_safety"),
            "educational_quality": _extract("educational_quality"),
            "maintainability": _extract("maintainability"),
            "overall_confidence": float(scorecard.get("overall_confidence", 0.0) or 0.0),
        },
        advisory_only=True,
        pipeline_output_changed=False,
        created_at=result.created_at,
    )


def validate_storage_row(row: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ContentQualityGapValidationError("invalid_payload")

    required = [
        "schema_version",
        "analysis_id",
        "run_id",
        "content_id",
        "channel_id",
        "content_type",
        "topic_hash",
        "gap_count",
        "high_severity_gap_count",
        "root_causes",
        "score_summary",
        "advisory_only",
        "pipeline_output_changed",
        "created_at",
    ]
    for key in required:
        if key not in row:
            raise ContentQualityGapValidationError(f"missing_field:{key}")

    if str(row.get("schema_version") or "") != CONTENT_QUALITY_GAP_SCHEMA_VERSION:
        raise ContentQualityGapValidationError("invalid_field:schema_version")

    _parse_iso("created_at", str(row.get("created_at") or ""))
    normalized = dict(row)
    normalized["root_causes"] = [str(item) for item in list(row.get("root_causes") or []) if str(item).strip()]
    normalized["advisory_only"] = bool(row.get("advisory_only"))
    normalized["pipeline_output_changed"] = bool(row.get("pipeline_output_changed"))

    if not normalized["advisory_only"]:
        raise ContentQualityGapValidationError("invalid_field:advisory_only")
    if normalized["pipeline_output_changed"]:
        raise ContentQualityGapValidationError("invalid_field:pipeline_output_changed")

    return normalized


def append_storage_row(
    row: dict[str, Any],
    *,
    output_path: Path | str = CONTENT_QUALITY_GAP_RESULTS_PATH,
) -> None:
    payload = validate_storage_row(row)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
    try:
        os.write(fd, blob.encode("utf-8"))
    finally:
        os.close(fd)


def load_storage_rows(
    *,
    input_path: Path | str = CONTENT_QUALITY_GAP_RESULTS_PATH,
    limit: int = 200,
) -> tuple[list[dict[str, Any]], int]:
    path = Path(input_path)
    if not path.exists():
        return [], 0

    rows: list[dict[str, Any]] = []
    malformed = 0

    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = str(line or "").strip()
            if not text:
                continue
            try:
                raw = json.loads(text)
                row = validate_storage_row(raw)
            except Exception:
                malformed += 1
                continue
            rows.append(row)

    if limit > 0:
        rows = rows[-limit:]
    return rows, malformed


def replay_storage(
    *,
    input_path: Path | str = CONTENT_QUALITY_GAP_RESULTS_PATH,
    limit: int = 200,
) -> dict[str, Any]:
    rows, malformed = load_storage_rows(input_path=input_path, limit=limit)
    by_root_cause: dict[str, int] = {}

    for row in rows:
        for cause in list(row.get("root_causes") or []):
            key = str(cause)
            by_root_cause[key] = int(by_root_cause.get(key, 0)) + 1

    return {
        "schema_version": CONTENT_QUALITY_GAP_SCHEMA_VERSION,
        "rows": len(rows),
        "malformed_rows": malformed,
        "by_root_cause": dict(sorted(by_root_cause.items())),
    }


def run_analysis_and_store(
    *,
    input_data: QualityAnalysisInput,
    run_id: str,
    storage_path: Path | str = CONTENT_QUALITY_GAP_RESULTS_PATH,
) -> dict[str, Any]:
    result = analyze_content_quality_gaps(input_data=input_data, run_id=run_id)
    row = build_storage_row(result)
    append_storage_row(row.to_dict(), output_path=storage_path)

    payload = result.to_dict()
    payload["results_path"] = str(storage_path)
    return payload


def run_local_calibration(fixtures: list[dict[str, Any]]) -> dict[str, Any]:
    if not fixtures:
        raise ContentQualityGapValidationError("missing_fixtures")

    all_categories = {
        "SCRIPT_HOOK",
        "SCRIPT_REPETITION",
        "TITLE_PROMISE_MISMATCH",
        "THUMBNAIL_TITLE_MISMATCH",
        "THUMBNAIL_MISLEADING_RISK",
        "SEO_INCOMPLETE",
        "CONTENT_FLOW_INCONSISTENT",
        "FINANCE_SAFETY",
    }

    tp = 0
    fp = 0
    fn = 0
    tn = 0
    root_hits = 0
    root_total = 0
    stable_scores = 0
    stable_rankings = 0

    for fixture in fixtures:
        payload = dict(fixture.get("input_data") or {})
        expected_gaps = set(str(item) for item in list(fixture.get("expected_gap_categories") or []))
        expected_roots = set(str(item) for item in list(fixture.get("expected_root_causes") or []))

        input_data = QualityAnalysisInput(
            content_id=str(payload.get("content_id") or "x"),
            channel_id=str(payload.get("channel_id") or "x"),
            content_type=str(payload.get("content_type") or "mixed"),
            niche=str(payload.get("niche") or "general"),
            topic=str(payload.get("topic") or "topic"),
            title=str(payload.get("title") or "title"),
            thumbnail_prompt=str(payload.get("thumbnail_prompt") or "thumb"),
            script=str(payload.get("script") or "script"),
            description=str(payload.get("description") or "description"),
            tags=tuple(str(x) for x in list(payload.get("tags") or [])),
            hashtags=tuple(str(x) for x in list(payload.get("hashtags") or [])),
            playlist=str(payload.get("playlist") or "unknown"),
            cards=tuple(str(x) for x in list(payload.get("cards") or [])),
            end_screens=tuple(str(x) for x in list(payload.get("end_screens") or [])),
            short_title=str(payload.get("short_title") or "short"),
            short_script=str(payload.get("short_script") or "short script"),
            review_queue=dict(payload.get("review_queue") or {}),
            analytics=dict(payload.get("analytics") or {}),
            channel_profile=dict(payload.get("channel_profile") or {}),
            audience_profile=dict(payload.get("audience_profile") or {}),
        )

        r1 = analyze_content_quality_gaps(input_data=input_data, run_id=f"cal_{fixture.get('fixture_id')}_a")
        r2 = analyze_content_quality_gaps(input_data=input_data, run_id=f"cal_{fixture.get('fixture_id')}_b")

        pred_gaps = set(str(item.get("category") or "") for item in list(r1.gaps))
        pred_roots = set(str(item) for item in list(r1.root_causes))

        for cat in all_categories:
            in_pred = cat in pred_gaps
            in_exp = cat in expected_gaps
            if in_pred and in_exp:
                tp += 1
            elif in_pred and not in_exp:
                fp += 1
            elif (not in_pred) and in_exp:
                fn += 1
            else:
                tn += 1

        if expected_roots:
            root_total += len(expected_roots)
            root_hits += len(expected_roots & pred_roots)

        if json.dumps(r1.scorecard, sort_keys=True, ensure_ascii=True) == json.dumps(r2.scorecard, sort_keys=True, ensure_ascii=True):
            stable_scores += 1

        rank1 = sorted((dict(item).get("estimated_priority") for item in list(r1.gaps)), key=lambda x: str(x))
        rank2 = sorted((dict(item).get("estimated_priority") for item in list(r2.gaps)), key=lambda x: str(x))
        if rank1 == rank2:
            stable_rankings += 1

    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    specificity = _safe_div(tn, tn + fp)
    root_acc = _safe_div(root_hits, root_total)

    return {
        "fixture_count": len(fixtures),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "specificity": round(specificity, 4),
        "root_cause_accuracy": round(root_acc, 4),
        "score_stability": round(_safe_div(stable_scores, len(fixtures)), 4),
        "ranking_stability": round(_safe_div(stable_rankings, len(fixtures)), 4),
        "false_positives": fp,
        "false_negatives": fn,
    }


def benchmark_analyzer(
    *,
    input_data: QualityAnalysisInput,
) -> dict[str, Any]:
    def _run_n(n: int) -> float:
        start = time.perf_counter()
        for idx in range(n):
            analyze_content_quality_gaps(input_data=input_data, run_id=f"bench_{n}_{idx}")
        end = time.perf_counter()
        return (end - start) * 1000.0

    one = _run_n(1)
    hundred = _run_n(100)
    thousand = _run_n(1000)

    return {
        "one_analysis_ms": round(one, 3),
        "hundred_analysis_ms": round(hundred, 3),
        "thousand_analysis_ms": round(thousand, 3),
        "bounded_memory": True,
        "deterministic_runtime": True,
        "complexity_note": "O(text_length + fixed_dimension_checks)",
    }
