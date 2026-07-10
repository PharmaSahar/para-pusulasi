#!/usr/bin/env python3
"""Generate a strict, read-only operational evidence report.

This reporter intentionally separates:
- Runtime evidence (stronger)
- Cache/snapshot evidence (secondary convenience)

It never modifies production behavior. It only reads artifacts and writes markdown.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "logs"

PROD_LOG = LOGS / "production_scheduler.out"
TRACE_PATH = LOGS / "trace_completeness_latest.json"
ACTIVATION_PATH = LOGS / "activation_controller_report_latest.json"
THUMB_FORENSICS_PATH = LOGS / "thumbnail_permission_forensics_2026-07-10.json"
THUMB_CACHE_PATH = LOGS / "thumbnail_permission_cache.json"
STEP2_PATH = LOGS / "step2_api_enablement_evidence_2026-07-09.md"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8", errors="ignore").splitlines()


def _today_upload_thumbnail_counts(lines: list[str], day: str) -> dict[str, int]:
    uploads = 0
    thumbs_ok = 0
    thumbs_403 = 0
    for line in lines:
        if day not in line:
            continue
        if "Video yuklendi: https://youtube.com/watch?v=" in line:
            uploads += 1
        if "Thumbnail" in line and "yuklendi" in line.lower():
            thumbs_ok += 1
        if "Thumbnail yukleme izni yok (403)" in line:
            thumbs_403 += 1
    return {
        "uploads": uploads,
        "thumbs_ok": thumbs_ok,
        "thumbs_403": thumbs_403,
    }


def _thumbnail_view() -> dict[str, Any]:
    forensics = _load_json(THUMB_FORENSICS_PATH)
    cache = _load_json(THUMB_CACHE_PATH)

    ready_from_forensics = int(forensics.get("ready", 0) or 0)
    blocked_from_forensics = int(forensics.get("blocked", 0) or 0)
    active_from_forensics = int(forensics.get("active_channels", 0) or 0)

    channels = dict(cache.get("channels") or {})
    ready_channels_cache: list[str] = []
    blocked_channels_cache: list[str] = []
    for channel_id, row in channels.items():
        if not isinstance(row, dict):
            continue
        if bool(row.get("can_upload_thumbnail")):
            ready_channels_cache.append(str(channel_id))
        elif str(row.get("last_reason") or ""):
            blocked_channels_cache.append(str(channel_id))

    return {
        "forensics": {
            "ready": ready_from_forensics,
            "blocked": blocked_from_forensics,
            "active": active_from_forensics,
        },
        "cache": {
            "ready_channels": sorted(ready_channels_cache),
            "blocked_channels": sorted(blocked_channels_cache),
            "total_channels": len(channels),
        },
    }


def _activation_view() -> dict[str, Any]:
    payload = _load_json(ACTIVATION_PATH)
    flags = dict(payload.get("flags") or {})
    gates = dict(payload.get("gates") or {})
    analytics_gate = dict(gates.get("analytics_api_probe") or {})
    thumb_gate = dict(gates.get("thumbnail_permission_probe") or {})

    return {
        "system_status": payload.get("system_status") or "unknown",
        "ready_for_learning_activation": bool(flags.get("ready_for_learning_activation")),
        "analytics_reason": analytics_gate.get("reason") or "unknown",
        "thumbnail_reason": thumb_gate.get("reason") or "unknown",
        "analytics_live_status": flags.get("analytics_live_status") or "unknown",
        "thumbnail_permission_status": flags.get("thumbnail_permission_status") or "unknown",
        "report_generated_at": payload.get("generated_at_utc") or "unknown",
    }


def _trace_view() -> dict[str, Any]:
    payload = _load_json(TRACE_PATH)
    trace = dict(payload.get("trace_completeness") or {})
    coverage = dict(payload.get("metrics_coverage") or {})

    ctr = float(dict(coverage.get("click_through_rate") or {}).get("percent", 0.0) or 0.0)
    wt = float(dict(coverage.get("watch_time_hours") or {}).get("percent", 0.0) or 0.0)
    imp = float(dict(coverage.get("impressions") or {}).get("percent", 0.0) or 0.0)
    avd = float(dict(coverage.get("average_view_duration_seconds") or {}).get("percent", 0.0) or 0.0)

    return {
        "eligible": int(trace.get("eligible_upload_runs", 0) or 0),
        "complete": int(trace.get("complete_runs", 0) or 0),
        "percent": float(trace.get("percent", 0.0) or 0.0),
        "target": float(trace.get("target_percent", 100.0) or 100.0),
        "alert_below": float(trace.get("alert_below_percent", 99.0) or 99.0),
        "coverage_ctr": ctr,
        "coverage_watch_time": wt,
        "coverage_impressions": imp,
        "coverage_avd": avd,
    }


def _pct(num: int, den: int) -> float:
    if den <= 0:
        return 0.0
    return round((num / den) * 100.0, 1)


def _report_text(*, day: str) -> str:
    lines = _load_lines(PROD_LOG)
    log_counts = _today_upload_thumbnail_counts(lines, day)
    thumb = _thumbnail_view()
    activation = _activation_view()
    trace = _trace_view()

    forensics = thumb["forensics"]
    cache = thumb["cache"]

    ready = int(forensics["ready"])
    blocked = int(forensics["blocked"])
    active = int(forensics["active"])

    learning_cov_pct = _pct(ready, active)
    sample_size = trace["eligible"]
    trace_status = "REPORTED_PASS" if trace["percent"] >= trace["alert_below"] else "REPORTED_ALERT"

    thumbnail_success_rate = "n/a"
    thumbnail_attempts = log_counts["thumbs_ok"] + log_counts["thumbs_403"]
    if thumbnail_attempts > 0:
        thumbnail_success_rate = f"{_pct(log_counts['thumbs_ok'], thumbnail_attempts)}%"

    now_utc = datetime.now(timezone.utc).isoformat()

    # Strict evidence wording: do not over-claim PROVEN/VALIDATED.
    body = f"""# Strict Evidence Report - {day}

## Scope
- Read-only operational report generation
- No source mutation
- No runtime flag mutation
- No commit/merge automation

## Evidence Maturity
- Lifecycle: PLANNED -> REPORTED -> PROVEN -> VALIDATED -> ROLLED_OUT
- This report package max maturity: REPORTED

## Runtime Source Priority
- Primary runtime sources:
  - logs/production_scheduler.out
  - logs/activation_controller_report_latest.json
  - logs/trace_completeness_latest.json
- Secondary convenience source:
  - logs/thumbnail_permission_cache.json
- Note:
  - Cache evidence can be stale/overwritten/incomplete.

## P0 Thumbnail 403 Root-Cause Classification
- Classification status: REPORTED
- Reported blocked channels (cache-derived): {", ".join(cache['blocked_channels']) if cache['blocked_channels'] else "none"}
- Reported ready channels (cache-derived): {", ".join(cache['ready_channels']) if cache['ready_channels'] else "none"}
- Evidence statement:
  - 403 class labels are observed and reported.
  - Full PROVEN requires per-channel fix, successful re-probe streak, and non-recurrence window.

## P0 3-Success Streak State
- Threshold: 3 consecutive thumbnails.set successes
- Ready (forensics snapshot): {ready}
- Blocked (forensics snapshot): {blocked}
- Active channels in snapshot: {active}
- Maturity: REPORTED

## Trace Completeness
- eligible_upload_runs: {trace['eligible']}
- complete_runs: {trace['complete']}
- trace_percent: {trace['percent']}
- target_percent: {trace['target']}
- alert_below_percent: {trace['alert_below']}
- sample_size: {sample_size}
- status: {trace_status}
- Caveat:
  - Small sample size can inflate confidence. Interpret with caution.

## Activation Controller Go/No-Go
- system_status: {activation['system_status']}
- ready_for_learning_activation: {str(activation['ready_for_learning_activation']).lower()}
- analytics_live_status: {activation['analytics_live_status']}
- analytics_gate_reason: {activation['analytics_reason']}
- thumbnail_gate_reason: {activation['thumbnail_reason']}
- blocked_reason_summary:
  - Analytics coverage insufficient ({trace['coverage_ctr']}% CTR / {trace['coverage_watch_time']}% watch_time / {trace['coverage_impressions']}% impressions / {trace['coverage_avd']}% AVD coverage)
  - Backfill chain incomplete
  - KPI confidence below validation threshold

## P1 Analytics Backfill SLO
- Current status: VALIDATION_QUEUE
- Rule:
  - Do not mark PROVEN/VALIDATED before API + eligible input + rows_appended + downstream consumption evidence are jointly observed.
- Evidence pointer:
  - logs/step2_api_enablement_evidence_2026-07-09.md exists: {str(STEP2_PATH.exists()).lower()}

## Operational Confidence
- P0-A: Medium
- P0-B: Low
- P0-C: High
- Overall confidence: Medium

## Business Snapshot
- report_generated_at_utc: {now_utc}
- uploads_today: {log_counts['uploads']}
- channels_healthy_snapshot: {ready}/{active}
- channels_blocked_snapshot: {blocked}/{active}
- thumbnail_success_rate_today: {thumbnail_success_rate}
- estimated_learning_coverage: {learning_cov_pct}%
- top_operational_blocker: thumbnail ownership/brand permission 403 on blocked channels
- top_growth_blocker: analytics coverage/backfill evidence not validated for activation

## Final Decision
- P0 root-cause class: REPORTED
- P0 streak readiness: REPORTED
- Trace completeness: {trace_status} (sample_size={sample_size})
- Activation learning state: NO-GO (safe mode remains)
- P1 backfill SLO: queued for validation
"""
    return body


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate strict read-only evidence report")
    parser.add_argument("--date", default=date.today().isoformat(), help="Report date in YYYY-MM-DD")
    parser.add_argument(
        "--out",
        default=str(LOGS / "strict_evidence_report_latest.md"),
        help="Output markdown path",
    )
    parser.add_argument(
        "--write-dated-copy",
        action="store_true",
        help="Also write logs/strict_evidence_report_<date>.md",
    )
    parser.add_argument(
        "--latest-only",
        action="store_true",
        help="Write only --out and skip dated copy (cron-safe explicit mode)",
    )
    args = parser.parse_args()

    if args.latest_only and args.write_dated_copy:
        parser.error("--latest-only and --write-dated-copy cannot be used together")

    report = _report_text(day=args.date)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")

    write_dated = bool(args.write_dated_copy) and not bool(args.latest_only)

    if write_dated:
        dated = LOGS / f"strict_evidence_report_{args.date}.md"
        dated.write_text(report, encoding="utf-8")

    print(
        json.dumps(
            {
                "ok": True,
                "out": str(out_path),
                "dated_copy_written": write_dated,
                "mode": "latest_only" if args.latest_only else ("latest_plus_dated" if write_dated else "latest_only_default"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
