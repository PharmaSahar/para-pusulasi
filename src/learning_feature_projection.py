from __future__ import annotations

from typing import Any


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def build_learning_index_record(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "learning_record_id": _safe_text(row.get("learning_record_id")),
        "decision_id": _safe_text(row.get("decision_id")),
        "channel_id": _safe_text(row.get("channel_id")),
        "content_id": _safe_text(row.get("content_id")),
        "topic": _safe_text(row.get("topic")) or None,
        "content_type": _safe_text(row.get("content_type")),
        "publish_slot": _safe_text(row.get("publish_slot")) or None,
        "impressions": row.get("impressions"),
        "views": row.get("views"),
        "ctr_ratio": row.get("ctr_ratio"),
        "watch_time_hours": row.get("watch_time_hours"),
        "average_view_duration_seconds": row.get("average_view_duration_seconds"),
        "subscribers_gained": row.get("subscribers_gained"),
        "maturity_state": _safe_text(row.get("maturity_state")),
        "metric_completeness": row.get("metric_completeness"),
        "evidence_completeness": row.get("evidence_completeness"),
    }


def build_learning_index_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    current_by_learning_record_id: dict[str, dict[str, Any]] = {}
    timeline_by_learning_record_id: dict[str, list[dict[str, Any]]] = {}

    sorted_rows = sorted(
        rows,
        key=lambda item: (
            _safe_text(item.get("measurement_timestamp")),
            _safe_text(item.get("created_at")),
            _safe_text(item.get("learning_event_id")),
        ),
    )

    for row in sorted_rows:
        record_id = _safe_text(row.get("learning_record_id"))
        if not record_id:
            continue
        current_by_learning_record_id[record_id] = row
        timeline_by_learning_record_id.setdefault(record_id, []).append(row)

    learning_index = [build_learning_index_record(row) for row in current_by_learning_record_id.values()]
    learning_index.sort(
        key=lambda item: (
            _safe_text(item.get("channel_id")),
            _safe_text(item.get("content_id")),
            _safe_text(item.get("learning_record_id")),
        )
    )

    return {
        "current_state_by_learning_record_id": current_by_learning_record_id,
        "learning_timeline": timeline_by_learning_record_id,
        "learning_index": learning_index,
    }
