from __future__ import annotations

import hashlib
import json
from typing import Any


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _sha(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def build_outcome_snapshot_record(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "outcome_record_id": _safe_text(row.get("outcome_record_id")),
        "decision_id": _safe_text(row.get("decision_id")),
        "learning_record_id": _safe_text(row.get("learning_record_id")),
        "correlation_id": _safe_text(row.get("correlation_id")),
        "channel_id": _safe_text(row.get("channel_id")),
        "content_id": _safe_text(row.get("content_id")),
        "observation_window_type": _safe_text(row.get("observation_window_type")),
        "observation_start": _safe_text(row.get("observation_start")),
        "observation_end": _safe_text(row.get("observation_end")),
        "observation_timestamp": _safe_text(row.get("observation_timestamp")),
        "impressions": row.get("impressions"),
        "ctr_ratio": row.get("ctr_ratio"),
        "watch_time_hours": row.get("watch_time_hours"),
        "average_view_duration_seconds": row.get("average_view_duration_seconds"),
        "average_percentage_viewed_ratio": row.get("average_percentage_viewed_ratio"),
        "subscribers_gained": row.get("subscribers_gained"),
        "likes": row.get("likes"),
        "comments": row.get("comments"),
        "maturity_state": _safe_text(row.get("maturity_state")),
        "metric_completeness": row.get("metric_completeness"),
        "evidence_completeness": row.get("evidence_completeness"),
        "sample_sufficiency": row.get("sample_sufficiency"),
        "kpi_categories": dict(row.get("kpi_categories") or {}),
        "snapshot_source_event_id": _safe_text(row.get("outcome_event_id")),
        "snapshot_source_hash": _safe_text(row.get("record_hash")),
    }


def build_outcome_snapshot_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    current_by_outcome_record_id: dict[str, dict[str, Any]] = {}
    timeline_by_outcome_record_id: dict[str, list[dict[str, Any]]] = {}

    sorted_rows = sorted(
        rows,
        key=lambda item: (
            _safe_text(item.get("observation_timestamp")),
            _safe_text(item.get("created_at")),
            _safe_text(item.get("outcome_event_id")),
        ),
    )

    for row in sorted_rows:
        record_id = _safe_text(row.get("outcome_record_id"))
        if not record_id:
            continue
        current_by_outcome_record_id[record_id] = row
        timeline_by_outcome_record_id.setdefault(record_id, []).append(row)

    outcome_snapshot = [build_outcome_snapshot_record(row) for row in current_by_outcome_record_id.values()]
    outcome_snapshot.sort(
        key=lambda item: (
            _safe_text(item.get("channel_id")),
            _safe_text(item.get("content_id")),
            _safe_text(item.get("outcome_record_id")),
        )
    )

    snapshot_payload = _stable_json(outcome_snapshot)
    snapshot_identity = "osm_" + _sha(snapshot_payload)[:24]
    snapshot_hash = "osh_" + _sha(snapshot_identity + "|" + snapshot_payload)[:24]

    return {
        "current_state_by_outcome_record_id": current_by_outcome_record_id,
        "outcome_timeline": timeline_by_outcome_record_id,
        "outcome_snapshot": outcome_snapshot,
        "snapshot_identity": snapshot_identity,
        "snapshot_hash": snapshot_hash,
    }
