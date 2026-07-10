#!/usr/bin/env python3
"""Consolidate latest P0/P1 operational evidence artifacts into one bundle."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

ARTIFACTS: dict[str, Path] = {
    "p0_validation_metrics": ROOT / "logs" / "p0_validation_metrics_latest.json",
    "trace_completeness": ROOT / "logs" / "trace_completeness_latest.json",
    "thumbnail_403_root_cause": ROOT / "logs" / "thumbnail_403_root_cause_latest.json",
    "thumbnail_streak_path": ROOT / "logs" / "thumbnail_streak_path_latest.json",
    "activation_go_no_go": ROOT / "logs" / "activation_controller_report_latest.json",
    "runtime_flag_ab_evidence": ROOT / "logs" / "runtime_flag_ab_evidence_latest.json",
    "routing_guard_review_queue": ROOT / "logs" / "routing_guard_review_queue_latest.json",
}

DEFAULT_OUTPUT = ROOT / "logs" / "p0_p1_artifacts_bundle_latest.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if isinstance(payload, dict):
        return payload
    return None


def _build_summary(bundle: dict[str, Any]) -> dict[str, Any]:
    p0 = bundle.get("artifacts", {}).get("p0_validation_metrics", {}).get("payload") or {}
    ws = {item.get("workstream"): item for item in (p0.get("workstreams") or []) if isinstance(item, dict)}

    trace = bundle.get("artifacts", {}).get("trace_completeness", {}).get("payload") or {}
    trace_pct = ((trace.get("trace_completeness") or {}).get("percent"))

    streak = bundle.get("artifacts", {}).get("thumbnail_streak_path", {}).get("payload") or {}
    streak_summary = streak.get("summary") or {}

    activation = bundle.get("artifacts", {}).get("activation_go_no_go", {}).get("payload") or {}
    runtime = bundle.get("artifacts", {}).get("runtime_flag_ab_evidence", {}).get("payload") or {}
    queue = bundle.get("artifacts", {}).get("routing_guard_review_queue", {}).get("payload") or {}

    p0a = ws.get("P0-A") or {}
    p0b = ws.get("P0-B") or {}
    p0c = ws.get("P0-C") or {}

    return {
        "trace_completeness_percent": trace_pct,
        "p0a_wrong_channel_publish_rate": ((((p0a.get("metrics") or {}).get("wrong_channel_publish_rate") or {}).get("value"))),
        "p0a_guard_review_pending": int((queue.get("summary") or {}).get("pending_review_rows", 0) or 0),
        "p0b_shorts_safety_rows": int(p0b.get("shorts_safety_decision_rows", 0) or 0),
        "p0c_chapter_contract_compliance": ((((p0c.get("metrics") or {}).get("chapter_contract_compliance") or {}).get("value"))),
        "streak_resolved_channels": int(streak_summary.get("resolved", 0) or 0),
        "streak_blocked_channels": int(streak_summary.get("blocked", 0) or 0),
        "activation_system_status": activation.get("system_status"),
        "runtime_flag_ab_ok": bool((runtime.get("result") or {}).get("ok", False)),
    }


def build_bundle() -> dict[str, Any]:
    artifacts: dict[str, Any] = {}
    for name, path in ARTIFACTS.items():
        payload = _read_json(path)
        artifacts[name] = {
            "path": str(path),
            "exists": path.exists(),
            "valid_json_object": payload is not None,
            "payload": payload,
        }

    bundle: dict[str, Any] = {
        "generated_at_utc": _utc_now_iso(),
        "scope": "p0_p1_operational_evidence_bundle",
        "artifacts": artifacts,
    }
    bundle["summary"] = _build_summary(bundle)
    return bundle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create consolidated P0/P1 artifacts bundle")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args(argv)

    bundle = build_bundle()
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "ok": True,
                "output": str(out_path),
                "summary": bundle.get("summary"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
