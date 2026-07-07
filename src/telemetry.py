"""Passive telemetry helpers for pipeline identity and stage envelopes."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import uuid


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
    asset_id: str | None = None,
) -> dict:
    return {
        "event_id": f"evt_{uuid.uuid4().hex}",
        "content_id": content_id,
        "run_id": run_id,
        "experiment_id": experiment_id,
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
        if sink is not None:
            sink(event)
            return
        if logger is not None:
            logger.info("telemetry_event=%s", json.dumps(event, ensure_ascii=False, sort_keys=True))
    except Exception:
        # Strict fail-open behavior for passive telemetry.
        return
