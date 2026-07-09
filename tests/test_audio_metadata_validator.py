from __future__ import annotations

from src.audio_metadata_contract import AUDIO_METADATA_SCHEMA_VERSION, VALID_AUDIO_WARNING_CODES
from src.audio_metadata_validator import (
    is_valid_audio_metadata_contract,
    validate_audio_metadata_contract,
)


def _valid_payload() -> dict:
    return {
        "schema_version": AUDIO_METADATA_SCHEMA_VERSION,
        "audio_mix_metadata": {
            "mix_applied": True,
            "loudness_measured_lufs": -16.1,
            "true_peak_dbtp": -1.2,
        },
        "music_track_id": "track_001",
        "ducking_applied": True,
        "loudness_target": -16.0,
    }


def test_valid_audio_metadata_contract_passes():
    payload = _valid_payload()

    assert validate_audio_metadata_contract(payload) == []
    assert is_valid_audio_metadata_contract(payload) is True


def test_missing_required_fields_rejected():
    payload = _valid_payload()
    payload.pop("audio_mix_metadata")
    payload.pop("music_track_id")

    errors = validate_audio_metadata_contract(payload)

    assert "missing_required_field:audio_mix_metadata" in errors
    assert "missing_required_field:music_track_id" in errors


def test_loudness_target_must_be_numeric():
    payload = _valid_payload()
    payload["loudness_target"] = "-16"

    errors = validate_audio_metadata_contract(payload)

    assert "invalid_loudness_target" in errors


def test_ducking_applied_must_be_boolean():
    payload = _valid_payload()
    payload["ducking_applied"] = "yes"

    errors = validate_audio_metadata_contract(payload)

    assert "invalid_ducking_applied" in errors


def test_audio_warning_code_must_be_standard():
    payload = _valid_payload()
    payload["audio_warning"] = {"code": sorted(VALID_AUDIO_WARNING_CODES)[0]}

    assert validate_audio_metadata_contract(payload) == []

    payload["audio_warning"] = {"code": "non_standard_reason"}
    errors = validate_audio_metadata_contract(payload)
    assert "unknown_audio_warning_code:non_standard_reason" in errors


def test_schema_version_must_match_constant():
    payload = _valid_payload()
    payload["schema_version"] = "2.0"

    errors = validate_audio_metadata_contract(payload)

    assert "invalid_schema_version" in errors
