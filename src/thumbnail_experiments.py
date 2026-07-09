"""Deterministic thumbnail A/B concept generation."""

from __future__ import annotations

from typing import Any

from .quality_scoring import build_quality_scores
from .visual_diversity import enforce_thumbnail_diversity


def _experiment_seed_prompts(base_prompt: str, title: str) -> dict[str, str]:
    base = (base_prompt or title or "thumbnail concept").strip()
    variant_b = (
        f"{base} — single focal subject, strong contrast, mobile-safe negative space, "
        f"curiosity gap, editorial lighting, one clear emotional cue"
    )
    return {"A": base, "B": variant_b}


def _score_variant(title: str, prompt: str) -> int:
    scores = build_quality_scores(
        title=title,
        description="",
        script="",
        tags=[],
        thumbnail_prompt=prompt,
    )
    return int(scores.get("thumbnail_attention_score") or 0)


def build_thumbnail_experiment_bundle(
    *,
    channel_id: str,
    content_type: str,
    slot: str,
    topic: str,
    title: str,
    thumbnail_prompt: str,
    profile: dict[str, Any],
    recent_history: list[dict[str, Any]],
    publish_at: str | None = None,
) -> dict:
    prompts = _experiment_seed_prompts(thumbnail_prompt, title)
    variants: list[dict[str, Any]] = []

    for variant_id in ("A", "B"):
        seed_prompt = prompts[variant_id]
        guard = enforce_thumbnail_diversity(
            channel_id=channel_id,
            content_type=content_type,
            slot=slot,
            topic=topic,
            thumbnail_prompt=seed_prompt,
            profile=profile,
            recent_history=recent_history,
            publish_at=publish_at,
        )
        record = dict(guard.get("record") or {})
        selected_prompt = record.get("thumbnail_prompt") or seed_prompt
        variants.append(
            {
                "variant_id": variant_id,
                "seed_prompt": seed_prompt,
                "thumbnail_prompt": selected_prompt,
                "accepted": bool(guard.get("accepted")),
                "regenerated": bool(guard.get("regenerated")),
                "attempts": int(guard.get("attempts") or 0),
                "rejected_attempts": guard.get("rejected_attempts") or [],
                "thumbnail_attention_score": _score_variant(title, selected_prompt),
                "record": record,
            }
        )

    variants.sort(
        key=lambda item: (
            item["thumbnail_attention_score"],
            1 if item["accepted"] else 0,
            1 if item["regenerated"] else 0,
        ),
        reverse=True,
    )
    selected = variants[0]

    return {
        "accepted": any(item["accepted"] for item in variants),
        "regenerated": any(item["regenerated"] for item in variants),
        "selected_variant_id": selected["variant_id"],
        "selected_prompt": selected["thumbnail_prompt"],
        "record": selected["record"],
        "variants": variants,
    }
