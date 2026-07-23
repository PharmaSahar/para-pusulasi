"""
Content Quality Guard — channel-topic contract, metadata completeness,
script freshness, and cross-field consistency.

This module does NOT replace the image relevance guard (image_relevance_guard.py).
It operates at the content/metadata layer.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

# ── Channel-topic contract ────────────────────────────────────────────────────
# Maps niche → forbidden niches (cross-contamination blocks).
# Content from a forbidden source niche must not appear in this channel.

_NICHE_FORBIDDEN_CROSS: dict[str, frozenset[str]] = {
    "saglik": frozenset({
        "borsa", "kripto", "kisisel_finans", "gayrimenkul",
    }),
    "gayrimenkul": frozenset({
        "saglik", "kripto", "psikoloji",
    }),
    "egitim": frozenset({
        "borsa", "kripto", "gayrimenkul",
    }),
    "psikoloji": frozenset({
        "borsa", "kripto", "gayrimenkul",
    }),
    "kariyer": frozenset({
        "saglik", "kripto", "gayrimenkul",
    }),
    "teknoloji": frozenset({
        "saglik", "gayrimenkul",
    }),
    # Finance niches allow each other but not health/education/psychology
    "kisisel_finans": frozenset({
        "saglik", "psikoloji",
    }),
    "borsa": frozenset({
        "saglik", "psikoloji", "egitim",
    }),
    "kripto": frozenset({
        "saglik", "psikoloji", "egitim",
    }),
}

# Topic keyword signals per niche — used to detect cross-contamination
_NICHE_SIGNAL_KEYWORDS: dict[str, frozenset[str]] = {
    "saglik": frozenset({"saglik", "sağlık", "beslenme", "spor", "diyet", "vitamin",
                         "hastane", "doktor", "tedavi", "ilaç", "klinik", "terapi",
                         "psikoloji", "mental", "zihin", "stres", "uyku", "egzersiz"}),
    "borsa": frozenset({"borsa", "hisse", "bist", "temettü", "teknik analiz",
                        "portföy", "trading", "endeks", "pay", "tüfe", "vob"}),
    "kripto": frozenset({"bitcoin", "ethereum", "kripto", "blockchain", "defi",
                         "altcoin", "token", "nft", "web3", "coin", "cüzdan"}),
    "kisisel_finans": frozenset({"birikim", "emeklilik", "bes", "faiz", "enflasyon",
                                  "dolar", "kur", "altın", "yatırım", "portföy",
                                  "bütçe", "tasarruf", "kredi", "borç"}),
    "gayrimenkul": frozenset({"gayrimenkul", "konut", "kira", "emlak", "taşınmaz",
                               "daire", "arsa", "müteahhit", "ipotek", "tapu"}),
    "egitim": frozenset({"öğrenme", "eğitim", "ders", "okul", "üniversite",
                          "sınav", "not", "hafıza", "motivasyon", "kitap", "kurs"}),
    "kariyer": frozenset({"kariyer", "maaş", "iş", "linkedin", "cv", "müzakere",
                           "terfi", "işveren", "freelance", "remote", "staj"}),
    "teknoloji": frozenset({"yapay zeka", "ai", "yazılım", "kod", "python",
                             "chatgpt", "otomasyon", "dijital", "uygulama", "platform"}),
    "psikoloji": frozenset({"psikoloji", "terapi", "bilinç", "düşünce", "duygusal",
                             "motivasyon", "hedef", "alışkanlık", "meditasyon"}),
}

# Soft/polysemous terms are diagnostic-only unless strengthened by additional signals.
_GLOBAL_SOFT_TERMS: frozenset[str] = frozenset(
    {
        "ogrenme",
        "ogren",
        "egitim",
        "ders",
        "not",
        "psikoloji",
        "dusunce",
        "hedef",
        "stres",
        "saglik",
        "pay",
        "hisse",
        "kur",
        "altin",
        "motivasyon",
    }
)

_NICHE_CRITICAL_TERMS: dict[str, frozenset[str]] = {
    "saglik": frozenset({"doktor", "hastane", "tedavi", "ilac", "klinik", "ameliyat", "tani"}),
    "borsa": frozenset({"bist", "temettu", "vob", "teknik", "trading", "endeks"}),
    "kripto": frozenset({"bitcoin", "ethereum", "blockchain", "defi", "nft", "altcoin"}),
    "kisisel_finans": frozenset({"kredi", "borc", "enflasyon", "tasarruf", "portfoy", "emeklilik", "dolar", "doviz", "yatirim"}),
    "gayrimenkul": frozenset({"gayrimenkul", "emlak", "arsa", "ipotek", "tapu", "konut"}),
    "egitim": frozenset({"universite", "sinav", "mufredat", "kurs"}),
    "kariyer": frozenset({"linkedin", "terfi", "cv", "staj"}),
    "teknoloji": frozenset({"yapay", "zeka", "yazilim", "python", "chatgpt", "otomasyon"}),
    "psikoloji": frozenset({"terapi", "depresyon", "anksiyete", "travma", "meditasyon"}),
}

_NICHE_HARD_PHRASES: dict[str, tuple[str, ...]] = {
    "saglik": ("tibbi tani", "tedavi protokolu", "ilac dozu", "hastalik belirtisi"),
    "borsa": ("teknik analiz", "hisse senedi", "portfoy dagilimi", "bist 100"),
    "kripto": ("spot islemi", "on chain", "cold wallet", "akilli sozlesme"),
    "kisisel_finans": ("doviz kuru", "varlik dagilimi", "kredi faizi", "altin birikimi"),
    "gayrimenkul": ("kira carpan", "konut kredisi", "arsa yatirimi", "tapu devri"),
    "egitim": ("sinav takvimi", "mufredat plani", "ders notu"),
    "kariyer": ("mulakat hazirligi", "kariyer plani", "ucret pazarligi"),
    "teknoloji": ("yazilim mimarisi", "model egitimi", "veri boru hatti"),
    "psikoloji": ("bilissel davranis", "anksiyete yonetimi", "terapi sureci"),
}

# ── Required metadata fields ─────────────────────────────────────────────────
_REQUIRED_FIELDS = ("title", "description", "tags", "category_id", "script")
_REQUIRED_SHORT_FIELDS = ("title", "description", "script")
_MIN_DESCRIPTION_LENGTH = 80
_MIN_TAGS_COUNT = 3

# ── Script freshness ──────────────────────────────────────────────────────────
_RECENT_SCRIPTS_FILE = "output/queue/recent_scripts.json"
_RECENT_WINDOW = 10      # check last N scripts
_OVERLAP_THRESHOLD = 0.55  # token overlap ratio triggering near-duplicate


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class ContentQualityDecision:
    channel_id: str
    topic: str
    niche: str
    content_type: Literal["video", "short"]
    channel_fit: Literal["pass", "fail", "warn"]
    channel_fit_reasons: list[str] = field(default_factory=list)
    metadata_complete: bool = True
    metadata_missing_fields: list[str] = field(default_factory=list)
    script_fresh: bool = True
    script_similarity: float = 0.0
    matched_historical_ids: list[str] = field(default_factory=list)
    regeneration_count: int = 0
    publish_decision: Literal["allow", "block", "warn"] = "allow"
    block_reasons: list[str] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)


@dataclass
class MetadataBundle:
    """Lightweight wrapper for content metadata to be validated."""
    title: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    category_id: str = ""
    script: str = ""
    thumbnail_prompt: str = ""
    niche: str = ""
    channel_id: str = ""
    is_short: bool = False


# ── Core validation functions ─────────────────────────────────────────────────

def check_channel_topic_fit(
    topic: str,
    script: str,
    title: str,
    niche: str,
    description: str = "",
    thumbnail_prompt: str = "",
    channel_topics: list[str] | None = None,
) -> tuple[Literal["pass", "fail", "warn"], list[str]]:
    """
    Validate that the content belongs to the channel's niche.
    Returns (decision, reasons).

    Rules:
    - A finance channel must not produce health/medical content.
    - A health channel must not produce finance/stock market content.
    - Cross-contamination detected via signal-keyword presence.
    """
    niche_norm = _normalize_for_matching(niche)
    forbidden = _NICHE_FORBIDDEN_CROSS.get(niche_norm, frozenset())
    combined_text = _normalize_for_matching(
        " ".join([
            str(topic or ""),
            str(title or ""),
            str(script or ""),
            str(description or ""),
            str(thumbnail_prompt or ""),
        ])
    )

    tokens = _tokenize_match_tokens(combined_text)

    reasons: list[str] = []
    for foreign_niche in forbidden:
        evidence = _evaluate_cross_niche_evidence(
            detected_domain=niche_norm,
            conflicting_domain=foreign_niche,
            normalized_text=combined_text,
            tokens=tokens,
        )
        if evidence["final_classification"] == "HARD_CROSS_NICHE_SIGNAL":
            reasons.append(
                "cross_niche_contamination: "
                + json.dumps(evidence, ensure_ascii=False, sort_keys=True)
            )

    if reasons:
        return "fail", reasons
    return "pass", []


def _normalize_for_matching(text: str) -> str:
    value = str(text or "").strip().casefold()
    table = str.maketrans(
        {
            "ı": "i",
            "İ": "i",
            "ş": "s",
            "ğ": "g",
            "ç": "c",
            "ö": "o",
            "ü": "u",
        }
    )
    normalized = value.translate(table)
    return re.sub(r"\s+", " ", normalized)


def _tokenize_match_tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]{2,}", text))


def _evaluate_cross_niche_evidence(
    *,
    detected_domain: str,
    conflicting_domain: str,
    normalized_text: str,
    tokens: set[str],
) -> dict[str, object]:
    raw_signals = {_normalize_for_matching(v) for v in _NICHE_SIGNAL_KEYWORDS.get(conflicting_domain, frozenset())}
    critical_terms = {_normalize_for_matching(v) for v in _NICHE_CRITICAL_TERMS.get(conflicting_domain, frozenset())}
    hard_phrases = tuple(_normalize_for_matching(v) for v in _NICHE_HARD_PHRASES.get(conflicting_domain, ()))

    hard_terms = sorted(
        term for term in raw_signals if term and term in tokens and term not in _GLOBAL_SOFT_TERMS
    )
    soft_terms = sorted(
        term for term in raw_signals if term and term in tokens and term in _GLOBAL_SOFT_TERMS
    )
    phrase_hits = sorted(
        phrase for phrase in hard_phrases if phrase and re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", normalized_text)
    )
    critical_hits = sorted(term for term in critical_terms if term and term in tokens)

    score = len(hard_terms) * 2 + len(soft_terms) + len(phrase_hits) * 3 + len(critical_hits) * 4
    threshold = 4
    has_hard_signal = bool(critical_hits or phrase_hits or len(hard_terms) >= 2 or (len(hard_terms) >= 1 and len(soft_terms) >= 2))

    if has_hard_signal and score >= threshold:
        final_classification = "HARD_CROSS_NICHE_SIGNAL"
        decision_reason = "hard signals exceed deterministic threshold"
    elif hard_terms or soft_terms or phrase_hits:
        final_classification = "SOFT_CONTEXT_SIGNAL" if soft_terms else "AMBIGUOUS_SIGNAL"
        decision_reason = "diagnostic signal below hard-block threshold"
    else:
        final_classification = "AMBIGUOUS_SIGNAL"
        decision_reason = "no conflicting domain evidence"

    return {
        "detected_domain": detected_domain,
        "conflicting_domain": conflicting_domain,
        "hard_signals": sorted(set(hard_terms + critical_hits)),
        "soft_signals": soft_terms,
        "contextual_phrases": phrase_hits,
        "score": score,
        "threshold": threshold,
        "final_classification": final_classification,
        "decision_reason": decision_reason,
    }


def check_metadata_completeness(bundle: MetadataBundle) -> tuple[bool, list[str]]:
    """
    Validate that required metadata fields are present and non-trivial.
    Returns (complete, missing_or_weak_fields).
    """
    required = _REQUIRED_SHORT_FIELDS if bundle.is_short else _REQUIRED_FIELDS
    missing: list[str] = []

    for f in required:
        val = getattr(bundle, f, None)
        if not val:
            missing.append(f"{f}:empty")
        elif f == "description" and len(str(val)) < _MIN_DESCRIPTION_LENGTH:
            missing.append(f"description:too_short({len(str(val))}<{_MIN_DESCRIPTION_LENGTH})")
        elif f == "tags" and isinstance(val, list) and len(val) < _MIN_TAGS_COUNT:
            missing.append(f"tags:too_few({len(val)}<{_MIN_TAGS_COUNT})")

    return len(missing) == 0, missing


def _tokenize(text: str) -> set[str]:
    """Simple whitespace+punctuation tokenizer for overlap detection."""
    return set(re.findall(r"\b\w{4,}\b", text.lower()))


def _token_overlap(a: str, b: str) -> float:
    """Jaccard-like token overlap between two texts."""
    ta, tb = _tokenize(a), _tokenize(b)
    if not ta or not tb:
        return 0.0
    intersection = len(ta & tb)
    union = len(ta | tb)
    return intersection / union if union > 0 else 0.0


def check_script_freshness(
    channel_id: str,
    script: str,
    title: str,
    topic: str,
) -> tuple[bool, float, list[str]]:
    """
    Compare new script/topic against recent scripts from the same channel.
    Returns (is_fresh, max_similarity, matched_video_ids).

    A script is stale if token overlap with any recent script exceeds threshold.
    """
    recent = _load_recent_scripts(channel_id)
    max_sim = 0.0
    matched: list[str] = []
    check_text = f"{title} {topic} {script[:500]}"

    for entry in recent[-_RECENT_WINDOW:]:
        ref_text = f"{entry.get('title', '')} {entry.get('topic', '')} {entry.get('script_preview', '')}"
        sim = _token_overlap(check_text, ref_text)
        if sim > max_sim:
            max_sim = sim
        if sim >= _OVERLAP_THRESHOLD:
            matched.append(entry.get("video_id", "unknown"))

    is_fresh = max_sim < _OVERLAP_THRESHOLD
    return is_fresh, round(max_sim, 3), matched


def evaluate_content_quality(
    bundle: MetadataBundle,
    script: str,
    topic: str,
    content_type: Literal["video", "short"] = "video",
    regeneration_count: int = 0,
) -> ContentQualityDecision:
    """
    Run all quality checks and return a publish decision.
    """
    dec = ContentQualityDecision(
        channel_id=bundle.channel_id,
        topic=topic,
        niche=bundle.niche,
        content_type=content_type,
        channel_fit="pass",
        regeneration_count=regeneration_count,
    )

    # 1. Channel-topic fit
    fit, reasons = check_channel_topic_fit(
        topic,
        script,
        bundle.title,
        bundle.niche,
        description=bundle.description,
        thumbnail_prompt=bundle.thumbnail_prompt,
    )
    dec.channel_fit = fit
    dec.channel_fit_reasons = reasons

    # 2. Metadata completeness
    complete, missing = check_metadata_completeness(bundle)
    dec.metadata_complete = complete
    dec.metadata_missing_fields = missing

    # 3. Script freshness
    fresh, sim, matched_ids = check_script_freshness(
        bundle.channel_id, script, bundle.title, topic
    )
    dec.script_fresh = fresh
    dec.script_similarity = sim
    dec.matched_historical_ids = matched_ids

    # 4. Scores (0.0–1.0)
    dec.scores = {
        "channel_fit_score": 1.0 if fit == "pass" else (0.5 if fit == "warn" else 0.0),
        "metadata_completeness_score": 1.0 if complete else max(0.0, 1.0 - len(missing) * 0.2),
        "script_freshness_score": 1.0 - sim,
    }

    # 5. Publish decision
    block: list[str] = []
    if fit == "fail":
        block.extend(reasons)
    if not complete:
        block.extend([f"metadata:{f}" for f in missing])
    if not fresh:
        block.append(f"near_duplicate_script (similarity={sim:.2f}, matched={matched_ids})")

    dec.block_reasons = block
    dec.publish_decision = "block" if block else "allow"

    _record_quality_evidence(dec)
    return dec


# ── Script registry ───────────────────────────────────────────────────────────

def _load_recent_scripts(channel_id: str) -> list[dict]:
    p = Path(_RECENT_SCRIPTS_FILE)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data.get(channel_id, [])
    except Exception:
        return []


def register_published_script(
    channel_id: str,
    video_id: str,
    title: str,
    topic: str,
    script: str,
) -> None:
    """Save script fingerprint for future freshness checks."""
    p = Path(_RECENT_SCRIPTS_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        entries = data.get(channel_id, [])
        entries.append({
            "video_id": video_id,
            "title": title,
            "topic": topic,
            "script_preview": script[:400],
            "fingerprint": hashlib.sha256(script.encode()).hexdigest()[:16],
            "registered_at": datetime.now(timezone.utc).isoformat(),
        })
        # Keep last 20 per channel
        data[channel_id] = entries[-20:]
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        logger.warning("Failed to register script: %s", exc)


# ── Observability ─────────────────────────────────────────────────────────────

_EVIDENCE_PATH = Path("logs/content_quality_guard_latest.json")
_EVIDENCE_HISTORY: list[dict] = []


def _record_quality_evidence(dec: ContentQualityDecision) -> None:
    entry = {
        "channel": dec.channel_id,
        "topic": dec.topic,
        "niche": dec.niche,
        "content_type": dec.content_type,
        "channel_fit": dec.channel_fit,
        "mismatch_reasons": dec.channel_fit_reasons,
        "metadata_complete": dec.metadata_complete,
        "metadata_missing": dec.metadata_missing_fields,
        "script_similarity": dec.script_similarity,
        "matched_historical": dec.matched_historical_ids,
        "regeneration_count": dec.regeneration_count,
        "publish_decision": dec.publish_decision,
        "block_reasons": dec.block_reasons,
        "scores": dec.scores,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    _EVIDENCE_HISTORY.append(entry)

    try:
        _EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
        artifact = {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "total_evaluated": len(_EVIDENCE_HISTORY),
            "blocked": sum(1 for e in _EVIDENCE_HISTORY if e["publish_decision"] == "block"),
            "allowed": sum(1 for e in _EVIDENCE_HISTORY if e["publish_decision"] == "allow"),
            "channel_fit_failures": sum(1 for e in _EVIDENCE_HISTORY if e["channel_fit"] == "fail"),
            "metadata_failures": sum(1 for e in _EVIDENCE_HISTORY if not e["metadata_complete"]),
            "near_duplicates": sum(1 for e in _EVIDENCE_HISTORY if not e.get("matched_historical") is not None and e["script_similarity"] >= _OVERLAP_THRESHOLD),
            "recent_items": _EVIDENCE_HISTORY[-20:],
        }
        _EVIDENCE_PATH.write_text(json.dumps(artifact, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        logger.warning("Failed to write quality evidence: %s", exc)
