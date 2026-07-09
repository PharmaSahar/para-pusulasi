"""Thumbnail candidate generation layer (T2.2).

Scope:
- Generate deterministic A/B/... candidate sets for a single experiment/content.
- Validate each candidate through ThumbnailVariant model contract.
"""

from __future__ import annotations

from typing import Any

from .thumbnail_experiment import (
    ALLOWED_VARIANT_LABELS,
    ThumbnailVariant,
    create_thumbnail_variant,
    validate_unique_variant_ids,
)


def _required_text(field_name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing_required_field:{field_name}")
    return value.strip()


def _validate_count(count: int) -> int:
    if not isinstance(count, int) or count <= 0:
        raise ValueError("invalid_count")
    if count > len(ALLOWED_VARIANT_LABELS):
        raise ValueError("count_exceeds_supported_labels")
    return count


def _validate_thumbnail_path(path: str) -> str:
    value = _required_text("thumbnail_path", path)
    lowered = value.lower()
    if not lowered.endswith((".jpg", ".jpeg", ".png", ".webp")):
        raise ValueError("invalid_thumbnail_path")
    return value


def _variant_id(index: int) -> str:
    return f"var_{index:04d}"


def generate_thumbnail_candidates(
    *,
    experiment_id: str,
    channel_id: str,
    content_id: str,
    strategy: str,
    candidates: list[dict[str, Any]],
    count: int = 2,
) -> list[ThumbnailVariant]:
    """Generate deterministic thumbnail variants for the same experiment/content.

    Notes:
    - Deterministic variant IDs: var_0001, var_0002, ...
    - Deterministic labels: A, B, C, ...
    - Each candidate must include at least: thumbnail_path, prompt
    """
    _required_text("experiment_id", experiment_id)
    _required_text("channel_id", channel_id)
    _required_text("content_id", content_id)
    _required_text("strategy", strategy)
    _validate_count(count)

    if not isinstance(candidates, list):
        raise ValueError("invalid_candidates")
    if len(candidates) < count:
        raise ValueError("insufficient_candidates")

    variants: list[ThumbnailVariant] = []
    for idx in range(count):
        payload = candidates[idx]
        if not isinstance(payload, dict):
            raise ValueError("invalid_candidate_payload")

        thumbnail_path = _validate_thumbnail_path(str(payload.get("thumbnail_path", "")))
        prompt = _required_text("prompt", str(payload.get("prompt", "")))

        variant = create_thumbnail_variant(
            experiment_id=experiment_id,
            variant_id=_variant_id(idx + 1),
            variant_label=ALLOWED_VARIANT_LABELS[idx],
            channel_id=channel_id,
            content_id=content_id,
            thumbnail_path=thumbnail_path,
            prompt=prompt,
            strategy=strategy,
        )
        variants.append(variant)

    validate_unique_variant_ids(variants)
    return variants
