"""Thumbnail experiment variant model and schema validation (T2.1)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Iterable

THUMBNAIL_EXPERIMENT_SCHEMA_VERSION = "1.0"
ALLOWED_VARIANT_LABELS = tuple(chr(code) for code in range(ord("A"), ord("Z") + 1))
VARIANT_ID_PATTERN = re.compile(r"^var_[0-9]{4}$")


@dataclass(frozen=True)
class ThumbnailVariant:
    experiment_id: str
    variant_id: str
    variant_label: str
    channel_id: str
    thumbnail_path: str
    prompt: str
    strategy: str
    created_at: str
    schema_version: str
    content_id: str | None = None
    video_id: str | None = None


def _is_iso_like(value: str) -> bool:
    candidate = (value or "").strip()
    if not candidate:
        return False
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        datetime.fromisoformat(candidate)
        return True
    except ValueError:
        return False


def _required_non_empty(field_name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing_required_field:{field_name}")
    return value.strip()


def _validate_variant_label(value: str) -> str:
    label = _required_non_empty("variant_label", value).upper()
    if label not in ALLOWED_VARIANT_LABELS:
        raise ValueError("invalid_variant_label")
    return label


def _validate_variant_id(value: str) -> str:
    variant_id = _required_non_empty("variant_id", value)
    if not VARIANT_ID_PATTERN.fullmatch(variant_id):
        raise ValueError("invalid_variant_id_format")
    return variant_id


def validate_thumbnail_variant(variant: ThumbnailVariant) -> None:
    _required_non_empty("experiment_id", variant.experiment_id)
    _validate_variant_id(variant.variant_id)
    _validate_variant_label(variant.variant_label)
    _required_non_empty("channel_id", variant.channel_id)
    _required_non_empty("thumbnail_path", variant.thumbnail_path)
    schema_version = _required_non_empty("schema_version", variant.schema_version)
    if schema_version != THUMBNAIL_EXPERIMENT_SCHEMA_VERSION:
        raise ValueError("invalid_schema_version")

    if not _is_iso_like(variant.created_at):
        raise ValueError("invalid_created_at")


def create_thumbnail_variant(
    *,
    experiment_id: str,
    variant_id: str,
    variant_label: str,
    channel_id: str,
    thumbnail_path: str,
    prompt: str,
    strategy: str,
    content_id: str | None = None,
    video_id: str | None = None,
    created_at: str | None = None,
    schema_version: str = THUMBNAIL_EXPERIMENT_SCHEMA_VERSION,
) -> ThumbnailVariant:
    value = ThumbnailVariant(
        experiment_id=_required_non_empty("experiment_id", experiment_id),
        variant_id=_validate_variant_id(variant_id),
        variant_label=_validate_variant_label(variant_label),
        channel_id=_required_non_empty("channel_id", channel_id),
        thumbnail_path=_required_non_empty("thumbnail_path", thumbnail_path),
        prompt=str(prompt or "").strip(),
        strategy=str(strategy or "").strip(),
        created_at=(created_at or datetime.now(timezone.utc).isoformat()),
        schema_version=_required_non_empty("schema_version", schema_version),
        content_id=(str(content_id).strip() if isinstance(content_id, str) and content_id.strip() else None),
        video_id=(str(video_id).strip() if isinstance(video_id, str) and video_id.strip() else None),
    )
    validate_thumbnail_variant(value)
    return value


def validate_unique_variant_ids(variants: Iterable[ThumbnailVariant]) -> None:
    seen_by_experiment: dict[str, set[str]] = {}
    for item in variants:
        validate_thumbnail_variant(item)
        ids = seen_by_experiment.setdefault(item.experiment_id, set())
        if item.variant_id in ids:
            raise ValueError(
                f"duplicate_variant_id_in_experiment:{item.experiment_id}:{item.variant_id}"
            )
        ids.add(item.variant_id)


def build_ab_variant_set(
    *,
    experiment_id: str,
    channel_id: str,
    content_id: str,
    variants: dict[str, dict[str, str]],
    strategy: str,
    schema_version: str = THUMBNAIL_EXPERIMENT_SCHEMA_VERSION,
) -> list[ThumbnailVariant]:
    """Build A/B style variant set from label-keyed input payload.

    Expected input example:
    {
            "A": {"variant_id": "var_0001", "thumbnail_path": "...", "prompt": "..."},
            "B": {"variant_id": "var_0002", "thumbnail_path": "...", "prompt": "..."},
    }
    """
    result: list[ThumbnailVariant] = []
    for label, payload in variants.items():
        if not isinstance(payload, dict):
            raise ValueError(f"invalid_variant_payload:{label}")
        result.append(
            create_thumbnail_variant(
                experiment_id=experiment_id,
                variant_id=str(payload.get("variant_id", "")),
                variant_label=str(label),
                channel_id=channel_id,
                content_id=content_id,
                thumbnail_path=str(payload.get("thumbnail_path", "")),
                prompt=str(payload.get("prompt", "")),
                strategy=str(strategy),
                schema_version=schema_version,
            )
        )

    validate_unique_variant_ids(result)
    return result
