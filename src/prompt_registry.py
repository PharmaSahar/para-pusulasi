"""Prompt Registry v1: deterministic prompt metadata helpers."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import re


PROMPT_REGISTRY_SCHEMA_VERSION = "v2"
_SECRET_PATTERN = re.compile(
    r"(api[_-]?key|client[_-]?secret|oauth|access[_-]?token|refresh[_-]?token|password|cookie|authorization\s*:|bearer\s+)",
    re.IGNORECASE,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_prompt(prompt_text: str) -> str:
    return (prompt_text or "").strip()


def _bounded_excerpt(prompt_text: str, *, limit: int = 240) -> str:
    text = re.sub(r"\s+", " ", str(prompt_text or "").strip())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _extract_categories(prompt_text: str) -> list[str]:
    text = str(prompt_text or "").lower()
    categories: list[str] = []
    checks = (
        ("channel", ["kanal", "niche", "persona", "tone", "ton"]),
        ("audience", ["hedef kitle", "audience", "beginner", "advanced", "yas"]),
        ("topic", ["konu", "topic", "intent", "urgency"]),
        ("narrative", ["anlatim", "narrative", "structure", "hikaye"]),
        ("hook", ["hook", "acilis", "ilk 30", "first sentence"]),
        ("retention", ["retention", "pace", "pacing", "cta timing", "curiosity"]),
        ("thumbnail", ["thumbnail", "visual", "contrast", "text density"]),
        ("seo", ["seo", "keyword", "search intent", "tag", "hashtag"]),
        ("shorts", ["short", "#shorts", "looping", "clip"]),
        ("discovery", ["playlist", "cards", "end screen", "suggested"]),
        ("safety", ["safe mode", "dogrulanabilir", "risk", "uncertainty", "guaranteed", "insider"]),
        ("output_format", ["json", "output", "yalnizca json", "sadece json"]),
    )
    for code, patterns in checks:
        if any(p in text for p in patterns):
            categories.append(code)
    return sorted(set(categories))


def _extract_output_requirements(prompt_text: str) -> list[str]:
    text = str(prompt_text or "").lower()
    req: list[str] = []
    if "json" in text:
        req.append("json_output")
    if '"title"' in text or "title" in text:
        req.append("title_required")
    if '"description"' in text or "description" in text:
        req.append("description_required")
    if '"script"' in text or "script" in text:
        req.append("script_required")
    if '"thumbnail_prompt"' in text or "thumbnail" in text:
        req.append("thumbnail_prompt_required")
    if '"tags"' in text or "hashtag" in text:
        req.append("tags_required")
    return sorted(set(req))


def _build_safe_prompt_representation(
    prompt_text: str,
    *,
    prompt_type: str,
    template_id: str,
    provider_model_family: str,
    input_field_presence: dict | None,
    blueprint_goal_references: list[str] | None,
) -> dict:
    normalized = _normalize_prompt(prompt_text)
    if _SECRET_PATTERN.search(normalized):
        raise ValueError("secret_like_prompt_detected")

    categories = _extract_categories(normalized)
    requirements = _extract_output_requirements(normalized)
    excerpt = _bounded_excerpt(normalized, limit=240)
    return {
        "schema_version": "v1",
        "prompt_type": str(prompt_type or "unknown"),
        "prompt_version": "v1",
        "template_id": str(template_id or "unknown_template"),
        "normalized_instruction_categories": categories,
        "bounded_excerpt": excerpt,
        "prompt_hash": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        "input_field_presence": dict(input_field_presence or {}),
        "output_format_requirements": requirements,
        "safety_instruction_presence": "safety" in categories,
        "channel_context_presence": any(item in categories for item in ("channel", "topic")),
        "audience_context_presence": "audience" in categories,
        "blueprint_goal_references": sorted(set(str(x) for x in (blueprint_goal_references or []) if str(x).strip())),
        "provider_model_family": str(provider_model_family or "unknown"),
        "char_size_estimate": len(normalized),
        "token_size_estimate": max(1, int(round(len(normalized) / 4))) if normalized else 0,
    }


def build_prompt_metadata(
    prompt_text: str,
    *,
    prompt_type: str = "content_generation",
    template_id: str = "content_generator_v2_json",
    provider_model_family: str = "anthropic_claude",
    input_field_presence: dict | None = None,
    blueprint_goal_references: list[str] | None = None,
) -> dict:
    normalized = _normalize_prompt(prompt_text)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    prompt_hash = digest
    prompt_id = f"pr_{digest[:16]}"
    prompt_version = f"v1-{digest[:8]}"
    safe_prompt = _build_safe_prompt_representation(
        normalized,
        prompt_type=prompt_type,
        template_id=template_id,
        provider_model_family=provider_model_family,
        input_field_presence=input_field_presence,
        blueprint_goal_references=blueprint_goal_references,
    )
    return {
        "registry_schema_version": PROMPT_REGISTRY_SCHEMA_VERSION,
        "prompt_hash": prompt_hash,
        "prompt_id": prompt_id,
        "prompt_version": prompt_version,
        "created_at": _utc_now_iso(),
        "safe_prompt": safe_prompt,
    }
