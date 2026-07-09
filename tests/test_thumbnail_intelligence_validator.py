from __future__ import annotations

import json
from pathlib import Path

from src.thumbnail_intelligence_validator import (
    THUMBNAIL_INTELLIGENCE_SCHEMA_VERSION,
    REJECTION_REASON_CODES,
    is_valid_thumbnail_metadata_contract,
    normalize_rejection_reasons,
    validate_thumbnail_metadata_contract,
)


def _load_thumbnail_fixture(filename: str) -> dict:
    fixture_path = Path(__file__).parent / "fixtures" / filename
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def _valid_payload() -> dict:
    payload = _load_thumbnail_fixture("thumbnail_metadata_valid.json")
    payload["schema_version"] = THUMBNAIL_INTELLIGENCE_SCHEMA_VERSION
    return payload


def _invalid_payload() -> dict:
    return _load_thumbnail_fixture("thumbnail_metadata_invalid.json")


def test_valid_thumbnail_metadata_contract_passes():
    payload = _valid_payload()
    assert validate_thumbnail_metadata_contract(payload) == []
    assert is_valid_thumbnail_metadata_contract(payload) is True


def test_validate_invalid_fixture_fails():
    payload = _invalid_payload()

    errors = validate_thumbnail_metadata_contract(payload)

    assert "invalid_schema_version" in errors
    assert "invalid_channel_id" in errors
    assert "invalid_rejection_reasons" in errors


def test_validate_missing_schema_version_field_fails():
    payload = _valid_payload()
    payload.pop("schema_version")

    errors = validate_thumbnail_metadata_contract(payload)

    assert "missing_required_field:schema_version" in errors


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
