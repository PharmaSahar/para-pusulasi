#!/usr/bin/env python3
"""Generate an optimization backlog from health KPIs.

Read-only analysis that proposes prioritized work items.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PERFORMANCE_PATH = ROOT / "logs" / "channel_performance.jsonl"
THUMB_CACHE_PATH = ROOT / "logs" / "thumbnail_permission_cache.json"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _load_recent_rows(limit: int = 200) -> list[dict[str, Any]]:
    if not PERFORMANCE_PATH.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in PERFORMANCE_PATH.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except Exception:
            continue
        rows.append(row)
    return rows[-max(1, int(limit)) :]


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return float(sum(values) / len(values))


def build_backlog() -> dict[str, Any]:
    rows = _load_recent_rows()
    thumb_cache = _read_json(THUMB_CACHE_PATH)
    channels = dict(thumb_cache.get("channels") or {})

    ctr_values = [float(r["click_through_rate"]) for r in rows if isinstance(r.get("click_through_rate"), (int, float))]
    retention_values = [float(r["average_view_percentage"]) for r in rows if isinstance(r.get("average_view_percentage"), (int, float))]
    reject_values = [float(r["thumbnail_reject_rate"]) for r in rows if isinstance(r.get("thumbnail_reject_rate"), (int, float))]

    avg_ctr = _avg(ctr_values)
    avg_retention = _avg(retention_values)
    avg_reject = _avg(reject_values)

    permission_blocked = 0
    for _, entry in channels.items():
        if not isinstance(entry, dict):
            continue
        if not bool(entry.get("can_upload_thumbnail", False)):
            permission_blocked += 1

    items: list[dict[str, Any]] = []

    def _item(
        *,
        priority: int,
        signal: str,
        reason: str,
        value: Any,
        expected_impact: str,
        estimated_risk: str,
        affected_modules: list[str],
        recommended_work: str,
        layer: str,
        evidence_source: str,
        evidence_status: str,
        sample_count: int,
        confidence: float,
    ) -> dict[str, Any]:
        return {
            "priority": int(priority),
            "signal": signal,
            "reason": reason,
            "value": value,
            "expected_impact": expected_impact,
            "estimated_risk": estimated_risk,
            "affected_modules": affected_modules,
            "recommended_work": recommended_work,
            "layer": layer,
            "evidence_source": evidence_source,
            "evidence_status": evidence_status,
            "sample_count": int(sample_count),
            "confidence": round(max(0.0, min(1.0, float(confidence))), 3),
        }

    if permission_blocked > 0:
        items.append(
            _item(
                priority=1,
                signal="thumbnail_permission_blocked",
                reason="Channels still fail thumbnails.set authorization checks",
                value=permission_blocked,
                expected_impact="high",
                estimated_risk="low",
                affected_modules=[
                    "ops/thumbnail_only_probe.py",
                    "ops/thumbnail_probe_wave.py",
                    "src/thumbnail_selection_policy.py",
                ],
                recommended_work="Resolve channel ownership/brand permission and quota blockers for thumbnails",
                layer="thumbnail_intelligence_v2",
                evidence_source=str(THUMB_CACHE_PATH),
                evidence_status="observed",
                sample_count=max(1, len(channels)),
                confidence=0.95,
            )
        )

    if avg_reject is not None and avg_reject > 0.2:
        items.append(
            _item(
                priority=1,
                signal="thumbnail_reject_rate_high",
                reason="Recent reject ratio above 20% threshold",
                value=round(avg_reject, 4),
                expected_impact="high",
                estimated_risk="medium",
                affected_modules=[
                    "src/thumbnail_selection_policy.py",
                    "src/pipeline.py",
                    "ops/activation_controller.py",
                ],
                recommended_work="Increase thumbnail variation and add stricter contrast validator",
                layer="thumbnail_intelligence_v2",
                evidence_source=str(PERFORMANCE_PATH),
                evidence_status="observed",
                sample_count=len(reject_values),
                confidence=0.8 if len(reject_values) >= 10 else 0.65,
            )
        )

    if len(ctr_values) >= 10 and avg_ctr is not None and avg_ctr < 0.04:
        items.append(
            _item(
                priority=2,
                signal="ctr_low",
                reason="Average CTR below 4% across recent window",
                value=round(avg_ctr, 4),
                expected_impact="high",
                estimated_risk="medium",
                affected_modules=[
                    "src/pipeline.py",
                    "src/channel_performance.py",
                    "ops/optimization_memory_engine.py",
                ],
                recommended_work="Increase thumbnail concept diversity and headline-thumbnail consistency",
                layer="analytics_learning",
                evidence_source=str(PERFORMANCE_PATH),
                evidence_status="observed",
                sample_count=len(ctr_values),
                confidence=0.8,
            )
        )

    if len(retention_values) >= 10 and avg_retention is not None and avg_retention < 55.0:
        items.append(
            _item(
                priority=3,
                signal="retention_low",
                reason="Average retention below 55% in recent samples",
                value=round(avg_retention, 3),
                expected_impact="medium",
                estimated_risk="low",
                affected_modules=[
                    "src/channel_performance.py",
                    "src/pipeline.py",
                ],
                recommended_work="Update hook generation and tighten section pacing policy",
                layer="video_quality_score",
                evidence_source=str(PERFORMANCE_PATH),
                evidence_status="observed",
                sample_count=len(retention_values),
                confidence=0.75,
            )
        )

    if not items:
        items.append(
            _item(
                priority=99,
                signal="no_critical_gap_detected",
                reason="No critical KPI threshold breach in current window",
                value=None,
                expected_impact="low",
                estimated_risk="low",
                affected_modules=[
                    "ops/optimization_backlog_engine.py",
                ],
                recommended_work="Continue monitoring and keep current optimization rollout",
                layer="controller_observe_mode",
                evidence_source=str(PERFORMANCE_PATH),
                evidence_status="no_evidence" if not rows else "observed",
                sample_count=len(rows),
                confidence=0.5,
            )
        )

    items.sort(key=lambda x: (int(x.get("priority", 999)), str(x.get("signal", ""))))

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "row_count": len(rows),
            "avg_ctr": avg_ctr,
            "avg_retention": avg_retention,
            "avg_thumbnail_reject_rate": avg_reject,
            "permission_blocked_channels": permission_blocked,
        },
        "backlog": items,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate optimization backlog")
    parser.add_argument("--output", default=str(ROOT / "logs" / "optimization_backlog.json"))
    args = parser.parse_args(argv)

    report = build_backlog()
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(out_path), "backlog_count": len(report["backlog"])}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
