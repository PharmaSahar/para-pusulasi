from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REJECTION_LOG_PATH = Path("logs/analytics_quality_rejections.jsonl")


@dataclass(frozen=True, slots=True)
class AnalyticsGuardResult:
    accepted: bool
    status: str
    reason_code: str
    message: str
    evidence: dict[str, Any]
    duplicate: bool = False


def _parse_iso(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _record_event(payload: dict[str, Any]) -> None:
    try:
        from .production_quality_platform import record_production_event

        record_production_event(payload)
    except Exception:
        return


def _reject(*, reason_code: str, message: str, snapshot: dict[str, Any], evidence: dict[str, Any], emit_event: bool = True) -> AnalyticsGuardResult:
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "reason_code": reason_code,
        "message": message,
        "snapshot": snapshot,
        "evidence": evidence,
    }
    _append_jsonl(REJECTION_LOG_PATH, payload)
    if emit_event:
        _record_event(
            {
                "event_type": "analytics_validation_rejected",
                "timestamp": payload["timestamp"],
                "severity": "ERROR",
                "status": "blocked",
                "reason": reason_code,
                "operation": "analytics_append",
                "release_sha": str(snapshot.get("commit_sha") or snapshot.get("build_sha") or ""),
                "channel": str(snapshot.get("channel_id") or ""),
                "channel_id": str(snapshot.get("channel_id") or ""),
                "job_id": str(snapshot.get("run_id") or ""),
                "video_id": str(snapshot.get("video_id") or ""),
                "source_component": "analytics_quality_guard",
                "evidence": evidence,
            }
        )
    return AnalyticsGuardResult(False, "blocked", reason_code, message, evidence)


def validate_performance_snapshot(snapshot: dict[str, Any], *, existing_rows: list[dict[str, Any]] | None = None) -> AnalyticsGuardResult:
    if not isinstance(snapshot, dict):
        return _reject(
            reason_code="analytics_snapshot_not_dict",
            message="Analytics snapshot payload is not a mapping.",
            snapshot={"raw_type": type(snapshot).__name__},
            evidence={"raw_type": type(snapshot).__name__},
        )

    required_fields = (
        "channel_id",
        "content_id",
        "run_id",
        "created_at",
        "performance_schema_version",
        "title",
    )
    missing = [field for field in required_fields if not str(snapshot.get(field) or "").strip()]
    if missing:
        return _reject(
            reason_code="analytics_snapshot_missing_required_fields",
            message="Analytics snapshot is missing required fields.",
            snapshot=snapshot,
            evidence={"missing_fields": missing},
        )

    created_at = _parse_iso(str(snapshot.get("created_at") or ""))
    if created_at is None:
        return _reject(
            reason_code="analytics_snapshot_invalid_timestamp",
            message="Analytics snapshot timestamp is invalid.",
            snapshot=snapshot,
            evidence={"field": "created_at"},
        )

    now = datetime.now(timezone.utc) + timedelta(minutes=5)
    if created_at > now or created_at.year < 2020:
        return _reject(
            reason_code="analytics_snapshot_impossible_timestamp",
            message="Analytics snapshot timestamp is impossible.",
            snapshot=snapshot,
            evidence={"created_at": created_at.isoformat()},
        )

    numeric_non_negative = (
        "impressions",
        "watch_time_hours",
        "average_view_duration_seconds",
        "average_view_percentage",
        "click_through_rate",
    )
    negatives = []
    for field in numeric_non_negative:
        value = snapshot.get(field)
        if value is None:
            continue
        try:
            parsed = float(value)
        except Exception:
            return _reject(
                reason_code="analytics_snapshot_invalid_numeric_value",
                message="Analytics snapshot contains an invalid numeric value.",
                snapshot=snapshot,
                evidence={"field": field, "value": value},
            )
        if parsed < 0:
            negatives.append(field)
    if negatives:
        return _reject(
            reason_code="analytics_snapshot_negative_metric",
            message="Analytics snapshot contains negative metrics.",
            snapshot=snapshot,
            evidence={"fields": negatives},
        )

    ctr = snapshot.get("click_through_rate")
    if ctr is not None:
        ctr_value = float(ctr)
        if ctr_value > 100 or ctr_value < 0:
            return _reject(
                reason_code="analytics_snapshot_invalid_ctr",
                message="Analytics snapshot CTR is out of range.",
                snapshot=snapshot,
                evidence={"click_through_rate": ctr_value},
            )

    avg_pct = snapshot.get("average_view_percentage")
    if avg_pct is not None:
        avg_pct_value = float(avg_pct)
        if avg_pct_value > 100 or avg_pct_value < 0:
            return _reject(
                reason_code="analytics_snapshot_invalid_average_percentage",
                message="Analytics snapshot average percentage viewed is out of range.",
                snapshot=snapshot,
                evidence={"average_view_percentage": avg_pct_value},
            )

    channel_id = str(snapshot.get("channel_id") or "")
    video_id = str(snapshot.get("video_id") or "")
    if video_id and len(video_id) < 6:
        return _reject(
            reason_code="analytics_snapshot_malformed_video_id",
            message="Analytics snapshot video id is malformed.",
            snapshot=snapshot,
            evidence={"video_id": video_id},
        )
    if len(channel_id) < 3:
        return _reject(
            reason_code="analytics_snapshot_malformed_channel_id",
            message="Analytics snapshot channel id is malformed.",
            snapshot=snapshot,
            evidence={"channel_id": channel_id},
        )

    duplicate_key = (
        channel_id,
        str(snapshot.get("content_id") or ""),
        str(snapshot.get("run_id") or ""),
        str(snapshot.get("video_id") or ""),
        str(snapshot.get("day") or ""),
    )
    for row in existing_rows or []:
        row_key = (
            str(row.get("channel_id") or ""),
            str(row.get("content_id") or ""),
            str(row.get("run_id") or ""),
            str(row.get("video_id") or ""),
            str(row.get("day") or ""),
        )
        if row_key == duplicate_key:
            _record_event(
                {
                    "event_type": "analytics_validation_rejected",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "severity": "WARNING",
                    "status": "duplicate",
                    "reason": "analytics_snapshot_duplicate",
                    "operation": "analytics_append",
                    "release_sha": str(snapshot.get("commit_sha") or snapshot.get("build_sha") or ""),
                    "channel": channel_id,
                    "channel_id": channel_id,
                    "job_id": str(snapshot.get("run_id") or ""),
                    "video_id": video_id,
                    "source_component": "analytics_quality_guard",
                    "evidence": {"duplicate_key": duplicate_key},
                }
            )
            return AnalyticsGuardResult(True, "duplicate", "analytics_snapshot_duplicate", "Duplicate analytics snapshot suppressed.", {"duplicate_key": duplicate_key}, duplicate=True)

    return AnalyticsGuardResult(True, "accepted", "analytics_snapshot_valid", "Analytics snapshot accepted.", {"duplicate_key": duplicate_key})