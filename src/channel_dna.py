"""Channel DNA Registry v1: deterministic metadata helpers."""

from __future__ import annotations

import hashlib
import json


DEFAULT_CHANNEL_DNA_VERSION = "v1"


def _normalize_text(value: str | None) -> str:
    return (value or "").strip()


def _normalize_list(values: list[str] | tuple[str, ...] | None) -> list[str]:
    if not values:
        return []
    return [str(v).strip() for v in values if str(v).strip()]


def _canonical_dna_payload(payload: dict) -> str:
    # Stable key ordering and compact separators keep hashing deterministic.
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_channel_dna_metadata(
    *,
    tone: str = "samimi, gercekci, heyecanli ama bilimsel temelli",
    audience: str = "Turkiye'de 25-50 yas, aylik 15.000-80.000 TL gelirli, yatirim yapmak isteyen bireyler",
    voice_archetype: str = "finans mentoru",
    evidence_style: str = "veri destekli, somut rakam odakli",
    forbidden_patterns: list[str] | tuple[str, ...] | None = None,
    signature_structure: list[str] | tuple[str, ...] | None = None,
    channel_dna_version: str = DEFAULT_CHANNEL_DNA_VERSION,
) -> dict:
    base_payload = {
        "tone": _normalize_text(tone),
        "audience": _normalize_text(audience),
        "voice_archetype": _normalize_text(voice_archetype),
        "evidence_style": _normalize_text(evidence_style),
        "forbidden_patterns": _normalize_list(forbidden_patterns),
        "signature_structure": _normalize_list(signature_structure),
        "channel_dna_version": _normalize_text(channel_dna_version) or DEFAULT_CHANNEL_DNA_VERSION,
    }

    canonical = _canonical_dna_payload(base_payload)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    metadata = dict(base_payload)
    metadata["channel_dna_hash"] = digest
    metadata["channel_dna_id"] = f"cd_{digest[:16]}"
    return metadata