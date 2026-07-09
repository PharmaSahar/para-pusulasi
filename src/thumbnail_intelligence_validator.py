"""Thumbnail Intelligence metadata contract and rejection reason validation."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .thumbnail_metadata_contract import THUMBNAIL_METADATA_SCHEMA_VERSION

# Backward-compatible alias retained for existing imports.
THUMBNAIL_INTELLIGENCE_SCHEMA_VERSION = THUMBNAIL_METADATA_SCHEMA_VERSION

REJECTION_REASON_CODES = {
    "SAFE_AREA_VIOLATION",
    "TEXT_DENSITY_EXCEEDED",
    "SUBJECT_CLARITY_LOW",
    "BRAND_INCONSISTENT",
    "DUPLICATE_OR_LOW_DIVERSITY",
    "LOW_CONTRAST",
    "VISUAL_CLUTTER",
}

# Internal/runtime reason aliases mapped to contract-level rejection codes.
REJECTION_REASON_ALIASES = {
    "text_outside_safe_area": "SAFE_AREA_VIOLATION",
    "text_hits_right_overlay": "SAFE_AREA_VIOLATION",
    "text_hits_bottom_overlay": "SAFE_AREA_VIOLATION",
    "text_outside_frame": "SAFE_AREA_VIOLATION",
    "line_count_exceeded": "TEXT_DENSITY_EXCEEDED",
    "readability_low": "LOW_CONTRAST",
    "near_duplicate_prompt": "DUPLICATE_OR_LOW_DIVERSITY",
    "same_channel_prompt_similarity>=0.82": "DUPLICATE_OR_LOW_DIVERSITY",
    "same_channel_slot_style_collision": "DUPLICATE_OR_LOW_DIVERSITY",
    "slot_style_overused_across_channels": "DUPLICATE_OR_LOW_DIVERSITY",
    "cross_channel_topic_too_similar": "DUPLICATE_OR_LOW_DIVERSITY",
    "subject_pose_background_repeat": "DUPLICATE_OR_LOW_DIVERSITY",
}

REQUIRED_FIELDS = (
    "schema_version",
    "channel_id",
    "content_id",
    "thumbnail_path",
    "variant_id",
    "evaluated_at_utc",
    "quality",
    "rejection_reasons",
    "diversity",
    "brand_profile_version",
)

REQUIRED_QUALITY_FIELDS = (
    "safe_area_pass",
    "text_density_ratio",
    "text_density_pass",
    "subject_clarity_pass",
    "brand_consistency_pass",
    "diversity_pass",
    "contrast_pass",
    "overall_pass",
)

REQUIRED_DIVERSITY_FIELDS = (
    "window_size",
    "similarity_score",
    "similarity_threshold",
)


def _is_iso_utc_like(value: str) -> bool:
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


def normalize_rejection_reasons(reasons: list[str] | tuple[str, ...] | None) -> list[str]:
    """Normalize runtime rejection reasons into contract-level reason codes."""
    if not reasons:
        return []

    normalized: list[str] = []
    seen: set[str] = set()

    for raw in reasons:
        value = str(raw or "").strip()
        if not value:
            continue

        code = REJECTION_REASON_ALIASES.get(value, value.upper())
        if code not in seen:
            normalized.append(code)
            seen.add(code)

    return normalized


def validate_thumbnail_metadata_contract(metadata: dict[str, Any]) -> list[str]:
    """Return contract validation errors for thumbnail intelligence metadata."""
    errors: list[str] = []

    for field in REQUIRED_FIELDS:
        if field not in metadata:
            errors.append(f"missing_required_field:{field}")

    if errors:
        return errors

    if metadata.get("schema_version") != THUMBNAIL_METADATA_SCHEMA_VERSION:
        errors.append("invalid_schema_version")

    for text_field in ("channel_id", "content_id", "thumbnail_path", "variant_id", "brand_profile_version"):
        value = metadata.get(text_field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"invalid_{text_field}")

    evaluated_at_utc = metadata.get("evaluated_at_utc")
    if not isinstance(evaluated_at_utc, str) or not _is_iso_utc_like(evaluated_at_utc):
        errors.append("invalid_evaluated_at_utc")

    quality = metadata.get("quality")
    if not isinstance(quality, dict):
        errors.append("invalid_quality")
    else:
        for field in REQUIRED_QUALITY_FIELDS:
            if field not in quality:
                errors.append(f"missing_quality_field:{field}")

        for bool_field in (
            "safe_area_pass",
            "text_density_pass",
            "subject_clarity_pass",
            "brand_consistency_pass",
            "diversity_pass",
            "contrast_pass",
            "overall_pass",
        ):
            if bool_field in quality and not isinstance(quality.get(bool_field), bool):
                errors.append(f"invalid_quality_{bool_field}")

        text_density_ratio = quality.get("text_density_ratio")
        if "text_density_ratio" in quality and not isinstance(text_density_ratio, (int, float)):
            errors.append("invalid_quality_text_density_ratio")
        elif isinstance(text_density_ratio, (int, float)) and not (0.0 <= float(text_density_ratio) <= 1.0):
            errors.append("invalid_quality_text_density_ratio_range")

    diversity = metadata.get("diversity")
    if not isinstance(diversity, dict):
        errors.append("invalid_diversity")
    else:
        for field in REQUIRED_DIVERSITY_FIELDS:
            if field not in diversity:
                errors.append(f"missing_diversity_field:{field}")

        if "window_size" in diversity and (
            not isinstance(diversity.get("window_size"), int) or int(diversity.get("window_size")) <= 0
        ):
            errors.append("invalid_diversity_window_size")

        for float_field in ("similarity_score", "similarity_threshold"):
            value = diversity.get(float_field)
            if float_field in diversity and not isinstance(value, (int, float)):
                errors.append(f"invalid_diversity_{float_field}")

    reasons_raw = metadata.get("rejection_reasons")
    if not isinstance(reasons_raw, list):
        errors.append("invalid_rejection_reasons")
        reasons_normalized: list[str] = []
    else:
        reasons_normalized = normalize_rejection_reasons(reasons_raw)
        unknown = [reason for reason in reasons_normalized if reason not in REJECTION_REASON_CODES]
        for reason in unknown:
            errors.append(f"unknown_rejection_reason:{reason}")

    if isinstance(quality, dict) and isinstance(reasons_raw, list):
        overall_pass = quality.get("overall_pass")
        if overall_pass is True and reasons_normalized:
            errors.append("invalid_consistency:overall_pass_with_rejections")
        if overall_pass is False and not reasons_normalized:
            errors.append("invalid_consistency:overall_fail_without_rejections")

    return errors


def is_valid_thumbnail_metadata_contract(metadata: dict[str, Any]) -> bool:
    return len(validate_thumbnail_metadata_contract(metadata)) == 0
