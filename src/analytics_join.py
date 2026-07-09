"""Derived analytics join metadata helpers.

This module builds a convenience join object from canonical metadata that
already exists in pipeline and content-layer outputs.
"""

from __future__ import annotations


JOIN_SCHEMA_VERSION = "v1"


def _clean(value):
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    return value


def build_analytics_join_metadata(
    *,
    content_id: str,
    run_id: str,
    channel_id: str | None = None,
    telemetry_metadata: dict | None = None,
    prompt_metadata: dict | None = None,
    channel_dna_metadata: dict | None = None,
    quality_score_metadata: dict | None = None,
) -> dict:
    telemetry_metadata = telemetry_metadata or {}
    prompt_metadata = prompt_metadata or {}
    channel_dna_metadata = channel_dna_metadata or {}
    quality_score_metadata = quality_score_metadata or {}

    return {
        "join_schema_version": JOIN_SCHEMA_VERSION,
        "content_id": content_id,
        "run_id": run_id,
        "channel_id": _clean(channel_id),
        "experiment_id": _clean(telemetry_metadata.get("experiment_id")),
        "experiment_group": _clean(telemetry_metadata.get("experiment_group")),
        "model_version": _clean(telemetry_metadata.get("model_version")),
        "thumbnail_strategy": _clean(telemetry_metadata.get("thumbnail_strategy")),
        "tts_strategy": _clean(telemetry_metadata.get("tts_strategy")),
        "prompt_id": _clean(prompt_metadata.get("prompt_id")),
        "prompt_version": _clean(prompt_metadata.get("prompt_version"))
        or _clean(telemetry_metadata.get("prompt_version")),
        "channel_dna_id": _clean(channel_dna_metadata.get("channel_dna_id")),
        "channel_dna_version": _clean(channel_dna_metadata.get("channel_dna_version"))
        or _clean(telemetry_metadata.get("channel_dna_version")),
        "thumbnail_attention_score": quality_score_metadata.get("thumbnail_attention_score"),
        "retention_signal_score": quality_score_metadata.get("retention_signal_score"),
        "overall_quality_score": quality_score_metadata.get("overall_quality_score"),
    }