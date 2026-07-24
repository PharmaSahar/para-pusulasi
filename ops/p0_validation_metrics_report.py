#!/usr/bin/env python3
"""Read-only P0 validation metric reporter.

This script computes currently observable P0 metrics from existing artifacts and
marks unavailable metrics as insufficient_evidence.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.runtime_storage import runtime_path

ROOT = Path(__file__).resolve().parents[1]
PERF_PATH = runtime_path("telemetry/channel_performance.jsonl")
THUMB_HISTORY_PATH = runtime_path("telemetry/thumbnail_history.jsonl")
ROUTING_GUARD_DECISIONS_PATH = runtime_path("telemetry/routing_guard_decisions.jsonl")
SHORTS_SAFETY_DECISIONS_PATH = runtime_path("telemetry/shorts_safety_decisions.jsonl")
CHAPTER_VALIDATION_TRAIL_PATH = runtime_path("telemetry/chapter_validation_trail.jsonl")
OUTPUT_LATEST = runtime_path("state/p0_validation_metrics_latest.json")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        raw = line.strip()
        if not raw:
            continue
        try:
            item = json.loads(raw)
        except Exception:
            continue
        if isinstance(item, dict):
            out.append(item)
    return out


def _safe_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _count_upload_rows(rows: list[dict[str, Any]]) -> int:
    return sum(1 for row in rows if row.get("video_id") or row.get("youtube_url"))


def _p0a_metrics(rows: list[dict[str, Any]], guard_rows: list[dict[str, Any]]) -> dict[str, Any]:
    uploads = [row for row in rows if row.get("video_id") or row.get("youtube_url")]
    sample_count = len(uploads)

    # Only this metric is currently observable from existing snapshots.
    dna_violation_count = sum(int(row.get("dna_violations") or 0) for row in uploads)
    wrong_channel_publish_rate = (dna_violation_count / sample_count * 100.0) if sample_count else None

    routing_guard_rows = [
        row
        for row in guard_rows
        if str(row.get("guard_name") or "").strip().lower() == "niche_alignment_guard"
    ]
    blocked_rows = [
        row
        for row in routing_guard_rows
        if str(row.get("decision") or "").strip().lower() == "block"
    ]
    reviewed_block_rows = [row for row in blocked_rows if row.get("review_outcome")]

    true_blocks = sum(
        1
        for row in reviewed_block_rows
        if str(row.get("review_outcome") or "").strip().lower() in {"true_block", "true_positive", "correct"}
    )
    false_blocks = sum(
        1
        for row in reviewed_block_rows
        if str(row.get("review_outcome") or "").strip().lower() in {"false_block", "false_positive", "incorrect"}
    )

    block_precision = (true_blocks / len(reviewed_block_rows) * 100.0) if reviewed_block_rows else None
    false_block_rate = (false_blocks / len(reviewed_block_rows) * 100.0) if reviewed_block_rows else None

    fail_closed_count = sum(
        1
        for row in routing_guard_rows
        if bool(row.get("fail_closed", False)) or str(row.get("decision") or "").strip().lower() == "fail_closed"
    )
    guard_fail_closed_rate = (fail_closed_count / len(routing_guard_rows) * 100.0) if routing_guard_rows else None

    return {
        "workstream": "P0-A",
        "name": "routing_and_dna_leak_prevention",
        "sample_count": sample_count,
        "guard_decision_rows": len(routing_guard_rows),
        "guard_block_rows": len(blocked_rows),
        "guard_reviewed_block_rows": len(reviewed_block_rows),
        "metrics": {
            "wrong_channel_publish_rate": {
                "value": round(wrong_channel_publish_rate, 3) if wrong_channel_publish_rate is not None else None,
                "unit": "percent",
                "evidence_status": "observed" if sample_count else "no_evidence",
            },
            "dna_violation_block_precision": {
                "value": round(block_precision, 3) if block_precision is not None else None,
                "unit": "percent",
                "evidence_status": "observed" if block_precision is not None else "insufficient_evidence",
                "reason": None if block_precision is not None else "missing_review_outcome_labels_in_guard_decisions",
            },
            "false_block_rate": {
                "value": round(false_block_rate, 3) if false_block_rate is not None else None,
                "unit": "percent",
                "evidence_status": "observed" if false_block_rate is not None else "insufficient_evidence",
                "reason": None if false_block_rate is not None else "missing_review_outcome_labels_in_guard_decisions",
            },
            "guard_fail_closed_rate": {
                "value": round(guard_fail_closed_rate, 3) if guard_fail_closed_rate is not None else None,
                "unit": "percent",
                "evidence_status": "observed" if guard_fail_closed_rate is not None else "no_evidence",
            },
        },
    }


def _p0b_metrics(
    rows: list[dict[str, Any]],
    thumb_history_rows: list[dict[str, Any]],
    shorts_safety_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    shorts_rows = [row for row in rows if row.get("short_url")]
    sample_count = len(shorts_rows)

    short_decisions = [
        row
        for row in shorts_safety_rows
        if str(row.get("content_type") or "").strip().lower() == "short"
    ]
    short_decisions_non_error = [row for row in short_decisions if not bool(row.get("validator_error", False))]

    safe_area_pass_count = sum(1 for row in short_decisions_non_error if row.get("safe_area_pass") is True)
    safe_area_compliance = (
        safe_area_pass_count / len(short_decisions_non_error) * 100.0 if short_decisions_non_error else None
    )

    unsafe_escape_count = sum(1 for row in short_decisions_non_error if row.get("overall_pass") is False)
    unsafe_escape_rate = (
        unsafe_escape_count / len(short_decisions_non_error) * 100.0 if short_decisions_non_error else None
    )

    # Approximation from currently available fields.
    reject_values = [float(row.get("thumbnail_reject_rate")) for row in shorts_rows if isinstance(row.get("thumbnail_reject_rate"), (int, float))]
    avg_reject = (sum(reject_values) / len(reject_values)) if reject_values else None

    return {
        "workstream": "P0-B",
        "name": "shorts_visual_safety",
        "sample_count": sample_count,
        "history_rows": len(thumb_history_rows),
        "shorts_safety_decision_rows": len(short_decisions),
        "shorts_safety_non_error_rows": len(short_decisions_non_error),
        "metrics": {
            "unsafe_visual_escape_rate": {
                "value": round(unsafe_escape_rate, 3) if unsafe_escape_rate is not None else None,
                "unit": "percent",
                "evidence_status": "observed" if unsafe_escape_rate is not None else "insufficient_evidence",
                "reason": None if unsafe_escape_rate is not None else "missing_structured_shorts_safety_decisions",
            },
            "thumbnail_reject_rate_proxy": {
                "value": round(avg_reject * 100.0, 3) if avg_reject is not None else None,
                "unit": "percent",
                "evidence_status": "observed" if avg_reject is not None else "no_evidence",
            },
            "safe_area_compliance": {
                "value": round(safe_area_compliance, 3) if safe_area_compliance is not None else None,
                "unit": "percent",
                "evidence_status": "observed" if safe_area_compliance is not None else "insufficient_evidence",
                "reason": None if safe_area_compliance is not None else "missing_structured_shorts_safety_decisions",
            },
        },
    }


def _p0c_metrics(rows: list[dict[str, Any]], chapter_rows: list[dict[str, Any]]) -> dict[str, Any]:
    sample_count = _count_upload_rows(rows)

    revalidate_rows = [row.get("revalidate") for row in chapter_rows if isinstance(row.get("revalidate"), dict)]
    compliant_count = sum(1 for row in revalidate_rows if bool(row.get("chapter_contract_pass", False)))
    chapter_contract_compliance = (compliant_count / len(revalidate_rows) * 100.0) if revalidate_rows else None

    upload_failure_rows = [row for row in chapter_rows if row.get("upload_stage_failed") is not None]
    upload_failure_count = sum(1 for row in upload_failure_rows if bool(row.get("upload_stage_failed", False)))
    upload_failure_rate = (upload_failure_count / len(upload_failure_rows) * 100.0) if upload_failure_rows else None

    post_upload_edit_rows = [row for row in chapter_rows if row.get("post_upload_edit") is not None]
    post_upload_edit_count = sum(1 for row in post_upload_edit_rows if bool(row.get("post_upload_edit", False)))
    post_upload_edit_rate = (post_upload_edit_count / len(post_upload_edit_rows) * 100.0) if post_upload_edit_rows else None

    return {
        "workstream": "P0-C",
        "name": "chapter_validator_hardening",
        "sample_count": sample_count,
        "chapter_validation_rows": len(chapter_rows),
        "chapter_revalidate_rows": len(revalidate_rows),
        "metrics": {
            "chapter_contract_compliance": {
                "value": round(chapter_contract_compliance, 3) if chapter_contract_compliance is not None else None,
                "unit": "percent",
                "evidence_status": "observed" if chapter_contract_compliance is not None else "insufficient_evidence",
                "reason": None if chapter_contract_compliance is not None else "missing_structured_chapter_validate_revalidate_artifacts",
            },
            "upload_time_chapter_failure_rate": {
                "value": round(upload_failure_rate, 3) if upload_failure_rate is not None else None,
                "unit": "percent",
                "evidence_status": "observed" if upload_failure_rate is not None else "insufficient_evidence",
                "reason": None if upload_failure_rate is not None else "missing_chapter_failure_tagging",
            },
            "post_upload_chapter_edit_rate": {
                "value": round(post_upload_edit_rate, 3) if post_upload_edit_rate is not None else None,
                "unit": "percent",
                "evidence_status": "observed" if post_upload_edit_rate is not None else "insufficient_evidence",
                "reason": None if post_upload_edit_rate is not None else "missing_post_upload_chapter_edit_audit",
            },
        },
    }


def build_report(*, lookback_rows: int) -> dict[str, Any]:
    perf_rows = _load_jsonl(PERF_PATH)
    thumb_history_rows = _load_jsonl(THUMB_HISTORY_PATH)
    guard_decision_rows = _load_jsonl(ROUTING_GUARD_DECISIONS_PATH)
    shorts_safety_rows = _load_jsonl(SHORTS_SAFETY_DECISIONS_PATH)
    chapter_validation_rows = _load_jsonl(CHAPTER_VALIDATION_TRAIL_PATH)

    scoped_rows = perf_rows[-max(1, int(lookback_rows)) :]

    report = {
        "generated_at_utc": _utc_now_iso(),
        "scope": {
            "lookback_rows": max(1, int(lookback_rows)),
            "performance_rows_total": len(perf_rows),
            "performance_rows_scoped": len(scoped_rows),
            "thumbnail_history_rows_total": len(thumb_history_rows),
            "routing_guard_decision_rows_total": len(guard_decision_rows),
            "shorts_safety_decision_rows_total": len(shorts_safety_rows),
            "chapter_validation_rows_total": len(chapter_validation_rows),
        },
        "workstreams": [
            _p0a_metrics(scoped_rows, guard_decision_rows),
            _p0b_metrics(scoped_rows, thumb_history_rows, shorts_safety_rows),
            _p0c_metrics(scoped_rows, chapter_validation_rows),
        ],
        "safety": {
            "read_only": True,
            "changes_runtime_behavior": False,
            "writes_flags": False,
        },
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate read-only P0 validation metrics report")
    parser.add_argument("--lookback-rows", type=int, default=500)
    parser.add_argument("--output", default=str(OUTPUT_LATEST))
    args = parser.parse_args(argv)

    report = build_report(lookback_rows=max(1, int(args.lookback_rows)))
    out_path = Path(args.output)
    _safe_write_json(out_path, report)

    print(
        json.dumps(
            {
                "ok": True,
                "report": str(out_path),
                "workstreams": [ws.get("workstream") for ws in report.get("workstreams", [])],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
