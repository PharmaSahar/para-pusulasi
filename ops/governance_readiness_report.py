#!/usr/bin/env python3
"""Generate a concise governance readiness markdown report from the bundle."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUNDLE = ROOT / "logs" / "p0_p1_artifacts_bundle_latest.json"
DEFAULT_OUTPUT = ROOT / "docs" / "governance_readiness_latest.md"
DEFAULT_DASHBOARD = ROOT / "logs" / "executive_dashboard.json"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Bundle not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Bundle must be a JSON object")
    return payload


def _load_optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _v(obj: dict[str, Any], *keys: str, default: Any = None) -> Any:
    cur: Any = obj
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return default if cur is None else cur


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.1f}%"
    except Exception:
        return str(value)


def _fmt_bool(value: Any) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return "n/a"


def _status_icon(ok: bool | None) -> str:
    if ok is None:
        return "[?]"
    return "[OK]" if ok else "[BLOCKED]"


def build_markdown(bundle: dict[str, Any], bundle_path: Path, dashboard: dict[str, Any]) -> str:
    generated_at = datetime.now(timezone.utc).isoformat()
    summary = bundle.get("summary") if isinstance(bundle.get("summary"), dict) else {}

    trace_pct = summary.get("trace_completeness_percent")
    p0a_wrong = summary.get("p0a_wrong_channel_publish_rate")
    p0a_pending = summary.get("p0a_guard_review_pending")
    p0b_rows = summary.get("p0b_shorts_safety_rows")
    p0c_comp = summary.get("p0c_chapter_contract_compliance")
    streak_resolved = summary.get("streak_resolved_channels")
    streak_blocked = summary.get("streak_blocked_channels")
    activation_status = summary.get("activation_system_status")
    runtime_ok = summary.get("runtime_flag_ab_ok")
    evidence_quality = dict(dashboard.get("evidence_quality") or {})
    expected_impact = list(dashboard.get("expected_business_impact") or [])

    activation_blocked = activation_status is not None and activation_status != "ready_for_learning_activation"
    runtime_bool = runtime_ok if isinstance(runtime_ok, bool) else None

    lines: list[str] = []
    lines.append("# Governance Readiness Report")
    lines.append("")
    lines.append(f"- Generated (UTC): {generated_at}")
    lines.append(f"- Source bundle: {bundle_path}")
    lines.append(f"- Dashboard artifact: {DEFAULT_DASHBOARD}")
    lines.append("")

    lines.append("## Executive Snapshot")
    lines.append("")
    lines.append(f"- {_status_icon(False if activation_blocked else True)} Activation status: {activation_status or 'n/a'}")
    lines.append(f"- {_status_icon(runtime_bool)} Runtime flag AB evidence ok: {_fmt_bool(runtime_ok)}")
    lines.append(f"- {_status_icon(trace_pct == 100.0)} Trace completeness: {_fmt_pct(trace_pct)}")
    lines.append(f"- {_status_icon(p0a_wrong == 0.0)} P0-A wrong channel publish rate: {_fmt_pct(p0a_wrong)}")
    lines.append(f"- {_status_icon(None if p0a_pending is None else p0a_pending == 0)} P0-A pending review labels: {p0a_pending if p0a_pending is not None else 'n/a'}")
    lines.append(f"- {_status_icon(None if p0b_rows is None else p0b_rows > 0)} P0-B shorts safety decision rows: {p0b_rows if p0b_rows is not None else 'n/a'}")
    lines.append(f"- {_status_icon(p0c_comp == 100.0)} P0-C chapter contract compliance: {_fmt_pct(p0c_comp)}")
    lines.append(f"- {_status_icon(None if streak_blocked is None else streak_blocked == 0)} Streak path blocked channels: {streak_blocked if streak_blocked is not None else 'n/a'}")
    lines.append(f"- [INFO] Streak path resolved channels: {streak_resolved if streak_resolved is not None else 'n/a'}")
    lines.append("")

    lines.append("## Gate Assessment")
    lines.append("")
    lines.append("- GO gate: blocked") if activation_blocked else lines.append("- GO gate: pass")
    lines.append("- Primary blockers:")
    if activation_blocked:
        lines.append("  - Activation controller is not in ready state.")
    if isinstance(p0a_pending, int) and p0a_pending > 0:
        lines.append("  - P0-A precision cannot be finalized until review_outcome labels are filled.")
    if isinstance(p0b_rows, int) and p0b_rows == 0:
        lines.append("  - P0-B evidence is insufficient because no structured short decisions were observed.")
    if (not activation_blocked) and not (isinstance(p0a_pending, int) and p0a_pending > 0) and not (isinstance(p0b_rows, int) and p0b_rows == 0):
        lines.append("  - No blocking item detected in current snapshot.")
    lines.append("")

    lines.append("## Deployment Evidence Status")
    lines.append("")
    lines.append("- Scheduler integration: implemented and reported")
    lines.append("- Runtime deployment: reported")
    lines.append("- Operational claim level: further runtime observation required before long-term stability claim")
    lines.append("")

    lines.append("## Evidence Quality")
    lines.append("")
    if evidence_quality:
        lines.append(
            f"- Evidence Quality Score: {evidence_quality.get('score', 'n/a')}/{evidence_quality.get('max_score', 'n/a')}"
        )
        lines.append(f"- Grade: {evidence_quality.get('grade', 'n/a')}")
        failed = list(evidence_quality.get("failed_factors") or [])
        if failed:
            lines.append("- Pending factors:")
            for item in failed:
                lines.append(f"  - {item}")
    else:
        lines.append("- Evidence Quality Score: n/a (dashboard artifact missing)")
    lines.append("")

    lines.append("## Expected Business Impact (Modeled)")
    lines.append("")
    if expected_impact:
        for idx, item in enumerate(expected_impact[:5], start=1):
            lines.append(
                f"{idx}. Recommendation: {item.get('recommendation', 'n/a')} | Expected impact: {item.get('expected_impact', 'n/a')} | Confidence: {item.get('confidence', 'n/a')} | Risk: {item.get('risk', 'n/a')} | Estimated KPI gain: {item.get('estimated_kpi_gain', 'n/a')} | Rollback difficulty: {item.get('rollback_difficulty', 'n/a')}"
            )
    else:
        lines.append("1. Impact model not available (dashboard artifact missing or empty).")
    lines.append("")

    lines.append("## Recommended Next Actions")
    lines.append("")
    lines.append("1. Fill review_outcome labels for pending routing guard queue rows and rerun P0 metrics report.")
    lines.append("2. Run at least one real short pipeline pass to emit structured shorts safety decisions.")
    lines.append("3. Rebuild artifact bundle and regenerate this report to confirm gate transition.")
    lines.append("")

    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate governance readiness markdown report")
    parser.add_argument("--bundle", default=str(DEFAULT_BUNDLE))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args(argv)

    bundle_path = Path(args.bundle)
    output_path = Path(args.output)

    bundle = _load_json(bundle_path)
    dashboard = _load_optional_json(DEFAULT_DASHBOARD)
    md = build_markdown(bundle, bundle_path, dashboard)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(md, encoding="utf-8")

    print(
        json.dumps(
            {
                "ok": True,
                "bundle": str(bundle_path),
                "output": str(output_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
