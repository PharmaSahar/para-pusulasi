from __future__ import annotations

from src.thumbnail_intelligence_validator import (
    THUMBNAIL_INTELLIGENCE_SCHEMA_VERSION,
    REJECTION_REASON_CODES,
    is_valid_thumbnail_metadata_contract,
    normalize_rejection_reasons,
    validate_thumbnail_metadata_contract,
)


def _valid_payload() -> dict:
    return {
        "schema_version": THUMBNAIL_INTELLIGENCE_SCHEMA_VERSION,
        "channel_id": "egitim_rehberi",
        "content_id": "content_123",
        "thumbnail_path": "channels/egitim_rehberi/output/videos/t1.jpg",
        "variant_id": "v1",
        "evaluated_at_utc": "2026-07-09T12:00:00+00:00",
        "quality": {
            "safe_area_pass": True,
            "text_density_ratio": 0.14,
            "text_density_pass": True,
            "subject_clarity_pass": True,
            "brand_consistency_pass": True,
            "diversity_pass": True,
            "contrast_pass": True,
            "overall_pass": True,
        },
        "rejection_reasons": [],
        "diversity": {
            "window_size": 30,
            "similarity_score": 0.41,
            "similarity_threshold": 0.78,
        },
        "brand_profile_version": "v1",
    }


def test_valid_thumbnail_metadata_contract_passes():
    payload = _valid_payload()
    assert validate_thumbnail_metadata_contract(payload) == []
    assert is_valid_thumbnail_metadata_contract(payload) is True


def test_validate_missing_required_fields():
    payload = _valid_payload()
    payload.pop("schema_version")
    payload.pop("quality")

    errors = validate_thumbnail_metadata_contract(payload)

    assert "missing_required_field:schema_version" in errors
    assert "missing_required_field:quality" in errors


def test_normalize_rejection_reasons_maps_runtime_aliases():
    normalized = normalize_rejection_reasons(
        [
            "text_hits_right_overlay",
            "line_count_exceeded",
            "near_duplicate_prompt",
            "low_contrast",
            "line_count_exceeded",
        ]
    )

    assert normalized == [
        "SAFE_AREA_VIOLATION",
        "TEXT_DENSITY_EXCEEDED",
        "DUPLICATE_OR_LOW_DIVERSITY",
        "LOW_CONTRAST",
    ]


def test_validate_rejection_reason_unknown_code_fails():
    payload = _valid_payload()
    payload["quality"]["overall_pass"] = False
    payload["rejection_reasons"] = ["NOT_A_REAL_REASON"]

    errors = validate_thumbnail_metadata_contract(payload)

    assert any(item.startswith("unknown_rejection_reason:") for item in errors)


def test_validate_consistency_overall_pass_with_rejections_fails():
    payload = _valid_payload()
    payload["quality"]["overall_pass"] = True
    payload["rejection_reasons"] = ["LOW_CONTRAST"]

    errors = validate_thumbnail_metadata_contract(payload)

    assert "invalid_consistency:overall_pass_with_rejections" in errors


def test_validate_consistency_overall_fail_without_rejections_fails():
    payload = _valid_payload()
    payload["quality"]["overall_pass"] = False
    payload["rejection_reasons"] = []

    errors = validate_thumbnail_metadata_contract(payload)

    assert "invalid_consistency:overall_fail_without_rejections" in errors


def test_contract_reason_codes_cover_documented_set():
    expected = {
        "SAFE_AREA_VIOLATION",
        "TEXT_DENSITY_EXCEEDED",
        "SUBJECT_CLARITY_LOW",
        "BRAND_INCONSISTENT",
        "DUPLICATE_OR_LOW_DIVERSITY",
        "LOW_CONTRAST",
        "VISUAL_CLUTTER",
    }
    assert REJECTION_REASON_CODES == expected
