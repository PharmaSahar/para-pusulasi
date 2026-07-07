"""Passive telemetry helpers for pipeline identity and stage envelopes."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import uuid

_DEFAULT_SINK = None
_SINK_INIT_ATTEMPTED = False


def _get_default_sink():
    global _DEFAULT_SINK
    global _SINK_INIT_ATTEMPTED
    if _SINK_INIT_ATTEMPTED:
        return _DEFAULT_SINK
    _SINK_INIT_ATTEMPTED = True
    try:
        from .telemetry_sink import build_jsonl_sink, get_sink_config

        cfg = get_sink_config()
        if cfg.get("enabled", True):
            _DEFAULT_SINK = build_jsonl_sink()
    except Exception:
        _DEFAULT_SINK = None
    return _DEFAULT_SINK


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_content_id() -> str:
    return f"content_{uuid.uuid4().hex}"


def generate_run_id() -> str:
    return f"run_{uuid.uuid4().hex}"


def build_event_envelope(
    *,
    content_id: str,
    run_id: str,
    stage: str,
    event_type: str,
    channel_id: str | None = None,
    payload: dict | None = None,
    experiment_id: str | None = None,
    experiment_group: str | None = None,
    prompt_version: str | None = None,
    channel_dna_version: str | None = None,
    thumbnail_strategy: str | None = None,
    tts_strategy: str | None = None,
    model_version: str | None = None,
    asset_id: str | None = None,
) -> dict:
    return {
        "event_id": f"evt_{uuid.uuid4().hex}",
        "content_id": content_id,
        "run_id": run_id,
        "experiment_id": experiment_id,
        "experiment_group": experiment_group,
        "prompt_version": prompt_version,
        "channel_dna_version": channel_dna_version,
        "thumbnail_strategy": thumbnail_strategy,
        "tts_strategy": tts_strategy,
        "model_version": model_version,
        "asset_id": asset_id,
        "stage": stage,
        "event_type": event_type,
        "occurred_at_utc": _utc_now_iso(),
        "channel_id": channel_id,
        "payload": payload or {},
    }


def emit_event(event: dict, *, logger=None, sink=None) -> None:
    """Emit telemetry in fail-open mode.

    This must never break production execution.
    """
    try:
        active_sink = sink if sink is not None else _get_default_sink()
        if active_sink is not None:
            active_sink(event)
        if logger is not None:
            logger.info("telemetry_event=%s", json.dumps(event, ensure_ascii=False, sort_keys=True))
    except Exception:
        # Strict fail-open behavior for passive telemetry.
        return
