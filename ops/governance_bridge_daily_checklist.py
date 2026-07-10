#!/usr/bin/env python3
"""Build a daily operational checklist from governance dashboard bridge artifact.

Source artifact:
- logs/governance_dashboard_bridge_latest.json

Output:
- logs/governance_bridge_daily_checklist_latest.md
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "logs" / "governance_dashboard_bridge_latest.json"
DEFAULT_OUTPUT = ROOT / "logs" / "governance_bridge_daily_checklist_latest.md"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _line(items: list[str], text: str = "") -> None:
    items.append(text)


def build_checklist(payload: dict[str, Any]) -> str:
    generated_at = datetime.now(timezone.utc).isoformat()
    strict = dict(payload.get("strict_evidence") or {})
    p0 = dict(payload.get("p0_thumbnail_youtube_auth_followup") or {})
    p1 = dict(payload.get("p1_analytics_validation_queue") or {})

    p0_rows = [row for row in list(p0.get("worklist") or []) if isinstance(row, dict)]
    p1_rows = [row for row in list(p1.get("worklist") or []) if isinstance(row, dict)]

    out: list[str] = []
    _line(out, "# Governance Bridge Daily Checklist")
    _line(out)
    _line(out, f"- Generated at UTC: {generated_at}")
    _line(out, f"- Source artifact: {DEFAULT_INPUT}")
    _line(out, f"- Max claim maturity: {payload.get('max_claim_maturity', 'REPORTED')}")
    _line(out)
    _line(out, "## Maturity Discipline")
    _line(out)
    _line(out, "- Lifecycle: PLANNED -> REPORTED -> PROVEN -> VALIDATED -> ROLLED_OUT")
    _line(out, "- Current safe classification: REPORTED")
    _line(out, "- Rule: Do not claim PROVEN/VALIDATED from tests only; runtime production artifacts are required.")
    _line(out)
    _line(out, "## Strict Evidence Snapshot")
    _line(out)
    _line(out, f"- Report date: {strict.get('report_date', 'unknown')}")
    _line(out, f"- Activation learning state: {strict.get('activation_learning_state', 'unknown')}")
    _line(out, f"- P1 backfill status: {strict.get('p1_backfill_status', 'unknown')}")
    _line(out)
    _line(out, "## P0 Blocked Thumbnail Channels")
    _line(out)
    _line(out, f"- Blocked channels total: {int(p0.get('blocked_channels_total', 0) or 0)}")
    _line(out)

    if not p0_rows:
        _line(out, "- [ ] No blocked channels in current snapshot")
    else:
        for row in p0_rows:
            channel_id = str(row.get("channel_id") or "unknown")
            reason = str(row.get("block_reason") or "unknown")
            remaining = int(row.get("remaining_successes", 0) or 0)
            status = row.get("last_probe_status")
            _line(out, f"- [ ] {channel_id}: reason={reason}, last_probe_status={status}, remaining_successes={remaining}")

    _line(out)
    _line(out, "## P1 VALIDATION_QUEUE Missing Criteria (Per Channel)")
    _line(out)
    _line(out, f"- Queue status: {p1.get('status', 'unknown')}")
    _line(out, f"- Channels total: {int(p1.get('channels_total', 0) or 0)}")
    _line(out, f"- Ready to exit: {int(p1.get('ready_to_exit_channels', 0) or 0)}")
    _line(out)

    if not p1_rows:
        _line(out, "- [ ] No channel worklist rows in current snapshot")
    else:
        for row in p1_rows:
            channel_id = str(row.get("channel_id") or "unknown")
            missing = list(row.get("missing_criteria") or [])
            missing_text = ", ".join(str(item) for item in missing) if missing else "none"
            queue_status = str(row.get("validation_queue_status") or "UNKNOWN")
            _line(out, f"- [ ] {channel_id}: {queue_status}, missing={missing_text}")

    _line(out)
    _line(out, "## Daily Operator Steps")
    _line(out)
    _line(out, "- [ ] Refresh artifacts: python ops/refresh_governance_readiness.py --lookback-rows 500")
    _line(out, "- [ ] Regenerate this checklist")
    _line(out, "- [ ] Run short-loop tests before claiming status updates")
    _line(out)

    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate daily checklist from governance bridge artifact")
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="Bridge JSON input path")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Markdown output path")
    args = parser.parse_args(argv)

    payload = _read_json(Path(args.input))
    checklist = build_checklist(payload)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(checklist, encoding="utf-8")

    print(
        json.dumps(
            {
                "ok": True,
                "input": str(Path(args.input)),
                "output": str(output_path),
                "blocked_channels": int((payload.get("p0_thumbnail_youtube_auth_followup") or {}).get("blocked_channels_total", 0) or 0),
                "queue_channels": int((payload.get("p1_analytics_validation_queue") or {}).get("channels_total", 0) or 0),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
