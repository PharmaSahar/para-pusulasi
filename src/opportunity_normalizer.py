"""Opportunity normalization helpers for Research Foundation v0.

This module is intentionally passive. It does not fetch from external APIs,
make decisions, or score opportunities. It only canonicalizes observations
into a stable schema and creates a deterministic opportunity ID.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any


OPPORTUNITY_SCHEMA_VERSION = "opportunity_v1"


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_text(value: Any, *, default: str = "unknown") -> str:
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    return " ".join(text.split()).lower()


def build_opportunity_id(*, country: Any, language: Any, topic: Any, source: Any) -> str:
    """Build a stable opportunity ID from canonical fields.

    ID format: opp_<sha256(canonical_json)>
    Canonical key set: country, language, topic, source
    """
    canonical_payload = {
        "country": _normalize_text(country),
        "language": _normalize_text(language),
        "source": _normalize_text(source),
        "topic": _normalize_text(topic),
    }
    canonical_json = json.dumps(canonical_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    return f"opp_{digest}"


def normalize_observation(raw: dict[str, Any], *, observed_at_utc: str | None = None) -> dict[str, Any]:
    """Normalize one raw observation into the shared opportunity schema.

    Required stable fields:
    - topic
    - category
    - country
    - language
    - source
    - first_seen
    - last_seen
    - search_volume
    - competition
    - confidence
    """
    observed_at = observed_at_utc or _iso_utc_now()

    topic = _normalize_text(raw.get("topic"))
    category = _normalize_text(raw.get("category"), default="general")
    country = _normalize_text(raw.get("country"), default="global")
    language = _normalize_text(raw.get("language"), default="unknown")
    source = _normalize_text(raw.get("source"), default="unknown")

    normalized = {
        "opportunity_id": build_opportunity_id(country=country, language=language, topic=topic, source=source),
        "schema_version": OPPORTUNITY_SCHEMA_VERSION,
        "topic": topic,
        "category": category,
        "country": country,
        "language": language,
        "source": source,
        "first_seen": observed_at,
        "last_seen": observed_at,
        "search_volume": raw.get("search_volume"),
        "competition": raw.get("competition"),
        "confidence": raw.get("confidence"),
        "raw_context": raw.get("raw_context", {}),
    }
    return normalized
