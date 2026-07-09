"""Audio metadata contract validation (A2)."""

from __future__ import annotations

from typing import Any

from .audio_metadata_contract import AUDIO_METADATA_SCHEMA_VERSION, VALID_AUDIO_WARNING_CODES

REQUIRED_FIELDS = (
    "schema_version",
    "audio_mix_metadata",
    "music_track_id",
    "ducking_applied",
    "loudness_target",
)


def validate_audio_metadata_contract(payload: dict[str, Any]) -> list[str]:
    """Return validation errors for audio metadata contract payload."""
    errors: list[str] = []

    for field in REQUIRED_FIELDS:
        if field not in payload:
            errors.append(f"missing_required_field:{field}")

    if "schema_version" in payload and payload.get("schema_version") != AUDIO_METADATA_SCHEMA_VERSION:
        errors.append("invalid_schema_version")

    if "audio_mix_metadata" in payload and not isinstance(payload.get("audio_mix_metadata"), dict):
        errors.append("invalid_audio_mix_metadata")

    if "music_track_id" in payload:
        track_id = payload.get("music_track_id")
        if not isinstance(track_id, str) or not track_id.strip():
            errors.append("invalid_music_track_id")

    if "ducking_applied" in payload and not isinstance(payload.get("ducking_applied"), bool):
        errors.append("invalid_ducking_applied")

    if "loudness_target" in payload:
        loudness_target = payload.get("loudness_target")
        if isinstance(loudness_target, bool) or not isinstance(loudness_target, (int, float)):
            errors.append("invalid_loudness_target")

    if "audio_warning" in payload:
        warning = payload.get("audio_warning")
        if not isinstance(warning, dict):
            errors.append("invalid_audio_warning")
        else:
            code = warning.get("code")
            if not isinstance(code, str) or not code.strip():
                errors.append("invalid_audio_warning_code")
            elif code not in VALID_AUDIO_WARNING_CODES:
                errors.append(f"unknown_audio_warning_code:{code}")

    return errors


def is_valid_audio_metadata_contract(payload: dict[str, Any]) -> bool:
    return len(validate_audio_metadata_contract(payload)) == 0
