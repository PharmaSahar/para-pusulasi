#!/usr/bin/env python3
"""Daily metrics coverage and experiment trace completeness report."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PERF_FILE = ROOT / "logs" / "channel_performance.jsonl"
TELEMETRY_FILE = ROOT / "logs" / "production_scheduler.out"
REGISTRY_FILE = ROOT / "output" / "telemetry" / "experiments.jsonl"


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except Exception:
            continue
        if isinstance(item, dict):
            out.append(item)
    return out


def _load_telemetry_events(path: Path) -> tuple[list[dict], int]:
    if not path.exists():
        return [], -1
    events: list[dict] = []
    marker = "telemetry_event="
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    last_build_idx = -1
    for idx, line in enumerate(lines):
        if "BUILD_INFO scheduler" in line:
            last_build_idx = idx

    for idx, line in enumerate(lines):
        if idx <= last_build_idx:
            continue
        if marker not in line:
            continue
        payload = line.split(marker, 1)[1].strip()
        try:
            event = json.loads(payload)
        except Exception:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events, last_build_idx


def _metrics_coverage(rows: list[dict]) -> dict:
    keys = [
        "click_through_rate",
        "watch_time_hours",
        "impressions",
        "average_view_duration_seconds",
    ]
    total = len(rows)
    coverage = {}
    for key in keys:
        filled = sum(1 for r in rows if r.get(key) is not None)
        pct = (filled / total * 100.0) if total else 0.0
        coverage[key] = {"filled": filled, "total": total, "percent": round(pct, 2)}
    return coverage


def _trace_completeness(telemetry_events: list[dict], registry_events: list[dict]) -> dict:
    runs: dict[str, dict] = defaultdict(lambda: {
        "channel_id": None,
        "content_id": None,
        "experiment_id": None,
        "upload_video_id": None,
        "has_upload_completed": False,
        "has_registry_pipeline_run": False,
    })

    for ev in telemetry_events:
        run_id = ev.get("run_id")
        if not run_id:
            continue
        row = runs[run_id]
        row["channel_id"] = row["channel_id"] or ev.get("channel_id")
        row["content_id"] = row["content_id"] or ev.get("content_id")
        row["experiment_id"] = row["experiment_id"] or ev.get("experiment_id")
        if ev.get("stage") == "upload" and ev.get("event_type") == "stage_completed":
            row["has_upload_completed"] = True
            payload = ev.get("payload") or {}
            if isinstance(payload, dict):
                row["upload_video_id"] = payload.get("video_id")

    registry_run_ids = set()
    for ev in registry_events:
        if ev.get("event_type") != "pipeline_run":
            continue
        payload = ev.get("payload") or {}
        if isinstance(payload, dict) and payload.get("run_id"):
            registry_run_ids.add(str(payload.get("run_id")))

    eligible = 0
    complete = 0
    missing_reasons = Counter()
    by_channel = Counter()

    for run_id, row in runs.items():
        if not row["has_upload_completed"]:
            continue
        eligible += 1
        by_channel[str(row.get("channel_id") or "unknown")] += 1

        has_registry = run_id in registry_run_ids
        row["has_registry_pipeline_run"] = has_registry

        ok = True
        if not row.get("experiment_id"):
            ok = False
            missing_reasons["missing_experiment_id"] += 1
        if not row.get("upload_video_id"):
            ok = False
            missing_reasons["missing_upload_video_id"] += 1
        if not has_registry:
            ok = False
            missing_reasons["missing_registry_pipeline_run_event"] += 1

        if ok:
            complete += 1

    percent = (complete / eligible * 100.0) if eligible else 0.0
    return {
        "eligible_upload_runs": eligible,
        "complete_runs": complete,
        "percent": round(percent, 2),
        "target_percent": 100.0,
        "alert_below_percent": 99.0,
        "missing_reasons": dict(missing_reasons),
        "upload_runs_by_channel": dict(by_channel),
    }


def main() -> int:
    perf_rows = _load_jsonl(PERF_FILE)
    telemetry_events, cutover_marker_line = _load_telemetry_events(TELEMETRY_FILE)
    registry_events = _load_jsonl(REGISTRY_FILE)

    result = {
        "files": {
            "performance": str(PERF_FILE),
            "telemetry": str(TELEMETRY_FILE),
            "registry": str(REGISTRY_FILE),
        },
        "cutover": {
            "build_info_marker_line": cutover_marker_line,
            "telemetry_events_considered": len(telemetry_events),
            "mode": "post_build_info_window",
        },
        "metrics_coverage": _metrics_coverage(perf_rows),
        "trace_completeness": _trace_completeness(telemetry_events, registry_events),
    }

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
