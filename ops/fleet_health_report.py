#!/usr/bin/env python3
"""Fleet-level health snapshot for all channels.

This script is read-only and intended for operations visibility.
It does not modify runtime behavior.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "channels" / "channel_registry.json"
THUMB_CACHE_PATH = ROOT / "logs" / "thumbnail_permission_cache.json"
FLAGS_PATH = ROOT / "output" / "state" / "learning_activation_flags.json"
PERFORMANCE_PATH = ROOT / "logs" / "channel_performance.jsonl"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _active_channels() -> list[str]:
    registry = _read_json(REGISTRY_PATH)
    channels = dict(registry.get("channels") or {})
    out: list[str] = []
    for cid, cfg in channels.items():
        if not isinstance(cfg, dict):
            continue
        if str(cfg.get("status") or "").strip().lower() == "active":
            out.append(str(cid))
    return sorted(out)


def _performance_rows_by_channel(lookback_hours: int = 24) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    if not PERFORMANCE_PATH.exists():
        return out

    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, int(lookback_hours)))
    for line in PERFORMANCE_PATH.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except Exception:
            continue
        channel_id = str(row.get("channel_id") or "").strip()
        if not channel_id:
            continue
        created_at_raw = str(row.get("created_at") or "")
        try:
            created_at = datetime.fromisoformat(created_at_raw.replace("Z", "+00:00"))
        except Exception:
            continue
        if created_at < cutoff:
            continue
        out.setdefault(channel_id, []).append(row)
    return out


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return float(mean(values))


def classify_channel_health(
    *,
    can_upload_thumbnail: bool,
    success_streak: int,
    has_last_24h_data: bool,
    uploaded_last_24h: bool,
    had_upload_error: bool,
    avg_ctr: float | None,
    avg_retention: float | None,
    analytics_data_status: str = "OBSERVED",
) -> tuple[str, int, list[str]]:
    reasons: list[str] = []
    risk_score = 0

    if not can_upload_thumbnail:
        risk_score += 45
        reasons.append("thumbnail_permission_blocked")
    elif success_streak < 3:
        risk_score += 12
        reasons.append("thumbnail_streak_below_3")

    normalized_data_status = str(analytics_data_status or "OBSERVED").strip().upper() or "OBSERVED"
    if normalized_data_status in {"NO_EVIDENCE", "DATA_PENDING"}:
        reasons.append(normalized_data_status.lower())
    elif not has_last_24h_data:
        reasons.append("no_recent_data")
    elif not uploaded_last_24h:
        risk_score += 20
        reasons.append("no_recent_upload")

    if had_upload_error:
        risk_score += 25
        reasons.append("recent_upload_error")

    if normalized_data_status == "OBSERVED" and avg_ctr is not None and avg_ctr < 0.035:
        risk_score += 10
        reasons.append("ctr_low")

    if normalized_data_status == "OBSERVED" and avg_retention is not None and avg_retention < 50.0:
        risk_score += 8
        reasons.append("retention_low")

    risk_score = min(100, risk_score)
    if risk_score >= 65:
        status = "RED"
    elif risk_score >= 30:
        status = "YELLOW"
    else:
        status = "GREEN"

    return status, risk_score, reasons


def build_fleet_health() -> dict[str, Any]:
    active_channels = _active_channels()
    thumb_cache = _read_json(THUMB_CACHE_PATH)
    flags = _read_json(FLAGS_PATH)
    rows_by_channel = _performance_rows_by_channel()

    thumb_channels = dict(thumb_cache.get("channels") or {})
    oauth_ready = 0
    analytics_ready = 0
    thumbnail_learning_on = 0
    safe_mode_count = 0
    channels_with_errors = 0
    uploaded_last_24h = 0
    no_data_channels = 0
    green_count = 0
    yellow_count = 0
    red_count = 0

    details: list[dict[str, Any]] = []
    for channel_id in active_channels:
        thumb_entry = dict(thumb_channels.get(channel_id) or {})
        success_streak = int(thumb_entry.get("success_streak", 0) or 0)
        can_upload_thumb = bool(thumb_entry.get("can_upload_thumbnail", False))
        rows = rows_by_channel.get(channel_id, [])

        has_any_data = bool(rows)
        upload_success = any(bool(row.get("upload_success") or row.get("youtube_url")) for row in rows)
        has_error = any(bool(row.get("upload_success") is False) for row in rows)
        ctr_values = [float(row["click_through_rate"]) for row in rows if isinstance(row.get("click_through_rate"), (int, float))]
        retention_values = [float(row["average_view_percentage"]) for row in rows if isinstance(row.get("average_view_percentage"), (int, float))]
        avg_ctr = _avg(ctr_values)
        avg_retention = _avg(retention_values)

        analytics_data_status = "OBSERVED"
        if not rows:
            analytics_data_status = "NO_EVIDENCE"
        elif avg_ctr is None and avg_retention is None:
            analytics_data_status = "DATA_PENDING"

        risk_status, risk_score, reasons = classify_channel_health(
            can_upload_thumbnail=can_upload_thumb,
            success_streak=success_streak,
            has_last_24h_data=has_any_data,
            uploaded_last_24h=upload_success,
            had_upload_error=has_error,
            avg_ctr=avg_ctr,
            avg_retention=avg_retention,
            analytics_data_status=analytics_data_status,
        )

        if can_upload_thumb:
            oauth_ready += 1
        if bool(flags.get("analytics_collector_enabled", False)):
            analytics_ready += 1
        if bool(flags.get("thumbnail_learning_enabled", False)) and can_upload_thumb:
            thumbnail_learning_on += 1
        if not can_upload_thumb:
            safe_mode_count += 1
        if has_error:
            channels_with_errors += 1
        if upload_success:
            uploaded_last_24h += 1
        if not has_any_data:
            no_data_channels += 1
        if risk_status == "GREEN":
            green_count += 1
        elif risk_status == "YELLOW":
            yellow_count += 1
        else:
            red_count += 1

        details.append(
            {
                "channel_id": channel_id,
                "can_upload_thumbnail": can_upload_thumb,
                "thumbnail_success_streak": success_streak,
                "last_thumbnail_reason": thumb_entry.get("last_reason"),
                "has_last_24h_data": has_any_data,
                "uploaded_last_24h": upload_success,
                "had_recent_upload_error": has_error,
                "avg_ctr_last_24h": avg_ctr,
                "avg_retention_last_24h": avg_retention,
                "analytics_data_status": analytics_data_status,
                "safe_mode": not can_upload_thumb,
                "risk_status": risk_status,
                "risk_score": risk_score,
                "risk_reasons": reasons,
            }
        )

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "fleet": {
            "active_channels": len(active_channels),
            "oauth_ready_channels": oauth_ready,
            "analytics_ready_channels": analytics_ready,
            "thumbnail_learning_enabled_channels": thumbnail_learning_on,
            "safe_mode_channels": safe_mode_count,
            "channels_with_errors": channels_with_errors,
            "channels_uploaded_last_24h": uploaded_last_24h,
            "channels_without_data_last_24h": no_data_channels,
            "green_channels": green_count,
            "yellow_channels": yellow_count,
            "red_channels": red_count,
        },
        "risk_model": {
            "status_thresholds": {
                "green_max": 29,
                "yellow_max": 64,
                "red_min": 65,
            },
            "scoring_factors": [
                "thumbnail_permission_blocked",
                "thumbnail_streak_below_3",
                "no_recent_data",
                "no_recent_upload",
                "recent_upload_error",
                "ctr_low",
                "retention_low",
            ],
        },
        "channels": details,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate fleet health report")
    parser.add_argument("--output", default=str(ROOT / "logs" / "fleet_health_report.json"))
    args = parser.parse_args(argv)

    report = build_fleet_health()
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(out_path), "fleet": report["fleet"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
