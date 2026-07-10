"""
Image Relevance Guard — Topic-aware Pexels asset classification.

Design principles:
- Hard-block sexualized content unconditionally.
- Context-sensitive filtering for people/lifestyle imagery.
- Topic/niche-specific acceptance and rejection policies.
- Relevance scoring (positive + negative keywords).
- Structured observability via JSON artifact.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

# ── Hard-block terms ──────────────────────────────────────────────────────────
# Always rejected regardless of topic or context.
_HARD_BLOCK_TERMS: frozenset[str] = frozenset(
    {
        "bikini",
        "swimsuit",
        "swimwear",
        "lingerie",
        "underwear",
        "topless",
        "nude",
        "nudity",
        "naked",
        "explicit",
        "erotic",
        "adult content",
        "pornographic",
    }
)
_HARD_BLOCK_RE = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in sorted(_HARD_BLOCK_TERMS)) + r")\b",
    re.IGNORECASE,
)

# ── Topic-specific positive keywords (boost relevance score) ──────────────────
_TOPIC_POSITIVE: dict[str, frozenset[str]] = {
    "kisisel_finans": frozenset(
        {
            "finance",
            "money",
            "savings",
            "budget",
            "planning",
            "calculator",
            "chart",
            "graph",
            "desk",
            "office",
            "documents",
            "spreadsheet",
            "investment",
            "retirement",
            "pension",
            "bank",
            "financial",
        }
    ),
    "borsa": frozenset(
        {
            "stock",
            "market",
            "chart",
            "trading",
            "analysis",
            "graph",
            "office",
            "screen",
            "monitor",
            "desk",
            "finance",
            "investment",
        }
    ),
    "kripto": frozenset(
        {
            "cryptocurrency",
            "bitcoin",
            "blockchain",
            "coin",
            "chart",
            "screen",
            "technology",
            "digital",
            "trading",
        }
    ),
    "kariyer": frozenset(
        {
            "career",
            "office",
            "professional",
            "laptop",
            "desk",
            "planning",
            "resume",
            "interview",
            "work",
            "team",
        }
    ),
    "girisim": frozenset(
        {
            "startup",
            "office",
            "team",
            "workspace",
            "laptop",
            "planning",
            "innovation",
        }
    ),
    "teknoloji": frozenset(
        {
            "technology",
            "computer",
            "screen",
            "code",
            "software",
            "digital",
            "device",
        }
    ),
    "egitim": frozenset(
        {
            "education",
            "learning",
            "study",
            "student",
            "books",
            "library",
            "classroom",
            "desk",
            "school",
            "university",
            "notebook",
        }
    ),
    "gayrimenkul": frozenset(
        {
            "house",
            "building",
            "property",
            "real estate",
            "architecture",
            "interior",
            "apartment",
        }
    ),
    "saglik": frozenset(
        {
            "health",
            "medical",
            "doctor",
            "clinic",
            "hospital",
            "nutrition",
            "fitness",
            "wellness",
            "medicine",
            "equipment",
        }
    ),
    "psikoloji": frozenset(
        {
            "psychology",
            "therapy",
            "mental",
            "journal",
            "wellness",
            "meditation",
            "books",
            "desk",
            "reflection",
        }
    ),
}

# ── Topic-specific CONTEXTUAL block terms (only for these niches) ─────────────
# These are not globally rejected; they are blocked only for specific topics.
_TOPIC_CONTEXTUAL_BLOCKS: dict[str, frozenset[str]] = {
    "kisisel_finans": frozenset(
        {
            "nightclub",
            "nightlife",
            "party girl",
            "glamour model",
            "beach fashion",
            "resort",
            "swimwear",
            "vacation fashion",
            "luxury yacht",
        }
    ),
    "borsa": frozenset(
        {"nightclub", "nightlife", "party", "resort", "fashion model"}
    ),
    "kripto": frozenset({"nightclub", "nightlife", "resort", "fashion model"}),
    "egitim": frozenset({"nightclub", "nightlife", "party", "resort"}),
}

# ── Contextual terms NOT globally blocked ─────────────────────────────────────
# These only contribute to negative score in finance/retirement niches.
_CONTEXT_PENALTY_FINANCE: frozenset[str] = frozenset(
    {
        "beach",
        "vacation",
        "holiday",
        "pool",
        "tropical",
        "summer",
        "glamour",
        "fashion",
        "model",
        "nightlife",
        "party",
    }
)


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class AssetClassification:
    asset_id: str
    asset_url: str
    asset_type: Literal["photo", "video"]
    alt_text: str
    topic: str
    niche: str
    query_used: str
    hard_blocked: bool
    positive_score: int
    negative_score: int
    contextual_penalty: int
    final_decision: Literal["accept", "reject"]
    rejection_reason: str | None = None

    @property
    def relevance_score(self) -> int:
        return self.positive_score - self.negative_score - self.contextual_penalty


@dataclass
class SearchObservability:
    channel_id: str
    topic: str
    niche: str
    original_query: str
    effective_query: str
    media_type: str
    total_candidates: int = 0
    accepted: int = 0
    rejected: int = 0
    hard_blocked: int = 0
    low_relevance: int = 0
    fallback_used: bool = False
    fallback_reason: str | None = None
    selected_asset_urls: list[str] = field(default_factory=list)
    classifications: list[AssetClassification] = field(default_factory=list)


# ── Core functions ─────────────────────────────────────────────────────────────


def build_safe_search_queries(
    topic: str,
    niche: str | None,
    channel_id: str | None = None,
) -> list[str]:
    """
    Return ordered list of search queries to try (primary + fallbacks).
    All queries are object-focused, avoiding people/lifestyle terms.
    """
    niche_norm = (niche or "").strip().lower()

    _SAFE_QUERIES: dict[str, list[str]] = {
        "kisisel_finans": [
            "personal finance budget spreadsheet desk calculator",
            "retirement savings pension documents office",
            "financial planning chart graph money",
        ],
        "borsa": [
            "stock market chart analysis screen office",
            "financial trading graph monitor desk",
            "investment analysis chart data",
        ],
        "kripto": [
            "cryptocurrency coin chart screen technology",
            "bitcoin blockchain digital network",
            "trading chart crypto screen",
        ],
        "kariyer": [
            "career office laptop desk planning documents",
            "professional workspace resume notebook",
            "office meeting room whiteboard",
        ],
        "girisim": [
            "startup office workspace desk laptop planning",
            "innovation office team whiteboard brainstorm",
        ],
        "teknoloji": [
            "technology computer screen code software",
            "digital workspace coding monitor circuit",
        ],
        "egitim": [
            "education books library desk classroom notebook",
            "study learning school university textbook",
        ],
        "gayrimenkul": [
            "real estate house building property architecture",
            "home interior apartment exterior",
        ],
        "saglik": [
            "health medical clinic equipment nutrition",
            "wellness fitness food medicine hospital",
        ],
        "psikoloji": [
            "psychology books desk therapy journal wellness",
            "mental health meditation notebook reflection",
        ],
    }

    queries = list(_SAFE_QUERIES.get(niche_norm, []))
    if not queries:
        queries = [
            "business office desk planning documents finance",
            "finance chart graph desk professional",
        ]
    return queries


def _extract_check_text(asset: dict, asset_type: str) -> str:
    """Extract all text fields available for relevance checking."""
    parts: list[str] = []
    if asset_type == "photo":
        parts.append(str(asset.get("alt", "") or ""))
        parts.append(str(asset.get("url", "") or ""))
        parts.append(str(asset.get("photographer", "") or ""))
    else:
        parts.append(str(asset.get("url", "") or ""))
        parts.append(" ".join(str(t) for t in (asset.get("tags") or [])))
        user = asset.get("user") or {}
        parts.append(str(user.get("name", "") or ""))
    return " ".join(parts)


def classify_asset_relevance(
    asset: dict,
    asset_type: Literal["photo", "video"],
    topic: str,
    niche: str | None,
    query_used: str = "",
) -> AssetClassification:
    """
    Score and classify a single Pexels photo or video.
    Returns an AssetClassification with the final accept/reject decision.
    """
    niche_norm = (niche or "").strip().lower()

    if asset_type == "photo":
        asset_id = str(asset.get("id", ""))
        asset_url = str(asset.get("url", "") or "")
        alt_text = str(asset.get("alt", "") or "")
    else:
        asset_id = str(asset.get("id", ""))
        asset_url = str(asset.get("url", "") or "")
        alt_text = " ".join(str(t) for t in (asset.get("tags") or []))

    check_text = _extract_check_text(asset, asset_type)
    check_lower = check_text.lower()

    # ── 1. Hard-block check ────────────────────────────────────────────────────
    hard_blocked = bool(_HARD_BLOCK_RE.search(check_lower))
    if hard_blocked:
        return AssetClassification(
            asset_id=asset_id,
            asset_url=asset_url,
            asset_type=asset_type,
            alt_text=alt_text,
            topic=topic,
            niche=niche_norm,
            query_used=query_used,
            hard_blocked=True,
            positive_score=0,
            negative_score=10,
            contextual_penalty=0,
            final_decision="reject",
            rejection_reason="hard_block",
        )

    # ── 2. Positive keyword score ──────────────────────────────────────────────
    positive_kw = _TOPIC_POSITIVE.get(niche_norm, frozenset())
    words = set(re.findall(r"\b\w+\b", check_lower))
    positive_score = len(words & positive_kw)

    # ── 3. Topic-specific contextual block ────────────────────────────────────
    contextual_blocks = _TOPIC_CONTEXTUAL_BLOCKS.get(niche_norm, frozenset())
    contextual_penalty = 0
    for block_term in contextual_blocks:
        if block_term in check_lower:
            contextual_penalty += 3

    # ── 4. Context penalty for finance niches (lifestyle in finance) ───────────
    negative_score = 0
    _FINANCE_NICHES = {"kisisel_finans", "borsa", "kripto", "gayrimenkul"}
    if niche_norm in _FINANCE_NICHES:
        penalty_words = words & _CONTEXT_PENALTY_FINANCE
        negative_score = len(penalty_words)

    # ── 5. Final decision ─────────────────────────────────────────────────────
    relevance = positive_score - negative_score - contextual_penalty
    if contextual_penalty >= 3:
        decision: Literal["accept", "reject"] = "reject"
        reason: str | None = f"contextual_block (score={relevance})"
    elif relevance < 0 and positive_score == 0 and niche_norm in _FINANCE_NICHES:
        decision = "reject"
        reason = f"low_relevance_finance (score={relevance})"
    else:
        decision = "accept"
        reason = None

    return AssetClassification(
        asset_id=asset_id,
        asset_url=asset_url,
        asset_type=asset_type,
        alt_text=alt_text,
        topic=topic,
        niche=niche_norm,
        query_used=query_used,
        hard_blocked=False,
        positive_score=positive_score,
        negative_score=negative_score,
        contextual_penalty=contextual_penalty,
        final_decision=decision,
        rejection_reason=reason,
    )


def should_reject_asset(classification: AssetClassification) -> bool:
    return classification.final_decision == "reject"


def select_safe_assets(
    candidates: list[dict],
    asset_type: Literal["photo", "video"],
    topic: str,
    niche: str | None,
    query_used: str = "",
    max_count: int = 6,
) -> tuple[list[dict], list[AssetClassification]]:
    """
    Filter and select safe assets from Pexels candidates.
    Returns (accepted_assets, all_classifications).
    Deduplicates by asset ID.
    """
    classifications: list[AssetClassification] = []
    seen_ids: set[str] = set()
    accepted: list[dict] = []

    for asset in candidates:
        asset_id = str(asset.get("id", ""))
        if asset_id in seen_ids:
            continue
        seen_ids.add(asset_id)

        clf = classify_asset_relevance(asset, asset_type, topic, niche, query_used)
        classifications.append(clf)

        if not should_reject_asset(clf):
            accepted.append(asset)
            if len(accepted) >= max_count:
                break

    return accepted, classifications


# ── Observability ──────────────────────────────────────────────────────────────

_ARTIFACT_PATH = Path("logs/image_relevance_guard_latest.json")
_ARTIFACT_HISTORY: list[dict] = []


def _build_artifact_entry(obs: SearchObservability) -> dict:
    return {
        "channel_id": obs.channel_id,
        "topic": obs.topic,
        "niche": obs.niche,
        "original_query": obs.original_query,
        "effective_query": obs.effective_query,
        "media_type": obs.media_type,
        "total_candidates": obs.total_candidates,
        "accepted": obs.accepted,
        "rejected": obs.rejected,
        "hard_blocked": obs.hard_blocked,
        "low_relevance": obs.low_relevance,
        "fallback_used": obs.fallback_used,
        "fallback_reason": obs.fallback_reason,
        "selected_assets": obs.selected_asset_urls,
        "rejection_reasons": [
            {"url": c.asset_url, "reason": c.rejection_reason}
            for c in obs.classifications
            if c.rejection_reason
        ],
    }


def record_search_observability(obs: SearchObservability) -> None:
    """Append search observability data to the JSON artifact."""
    try:
        entry = _build_artifact_entry(obs)
        _ARTIFACT_HISTORY.append(entry)
        _ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)

        # Aggregate stats
        total_c = sum(e["total_candidates"] for e in _ARTIFACT_HISTORY)
        total_a = sum(e["accepted"] for e in _ARTIFACT_HISTORY)
        total_r = sum(e["rejected"] for e in _ARTIFACT_HISTORY)
        total_hb = sum(e["hard_blocked"] for e in _ARTIFACT_HISTORY)
        total_lr = sum(e["low_relevance"] for e in _ARTIFACT_HISTORY)
        total_fb = sum(1 for e in _ARTIFACT_HISTORY if e["fallback_used"])

        artifact = {
            "aggregate": {
                "total_candidates": total_c,
                "accepted": total_a,
                "rejected": total_r,
                "hard_blocked": total_hb,
                "low_relevance": total_lr,
                "fallback_count": total_fb,
            },
            "searches": _ARTIFACT_HISTORY[-50:],  # keep last 50
        }
        _ARTIFACT_PATH.write_text(json.dumps(artifact, indent=2, ensure_ascii=False))
        logger.debug("Image relevance artifact updated: %s", _ARTIFACT_PATH)
    except Exception as exc:
        logger.warning("Failed to write image relevance artifact: %s", exc)
