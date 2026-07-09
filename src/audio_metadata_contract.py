"""Shared audio metadata contract constants."""

from __future__ import annotations


AUDIO_METADATA_SCHEMA_VERSION = "1.0"

VALID_AUDIO_WARNING_CODES = {
    "audio_track_not_found",
    "audio_selection_failed",
    "audio_ducking_failed",
    "audio_loudness_out_of_range",
    "audio_mix_failed",
    "audio_metadata_validation_failed",
}
