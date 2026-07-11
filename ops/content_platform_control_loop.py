#!/usr/bin/env python3
"""Generate measurable self-improving content platform artifacts."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.content_platform_control_loop import LearningRules, run_control_loop


ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "logs"
DOCS = ROOT / "docs"

DEFAULT_PERFORMANCE_PATH = LOGS / "channel_performance.jsonl"
DEFAULT_ROUTING_GUARD_PATH = LOGS / "routing_guard_decisions.jsonl"
DEFAULT_EXPERIMENT_REGISTRY_PATH = ROOT / "output" / "telemetry" / "experiments.jsonl"
DEFAULT_LEARNING_AUDIT_PATH = LOGS / "content_platform_learning_audit.jsonl"

HEALTH_OUTPUT = LOGS / "content_platform_health_latest.json"
RECOMMENDATIONS_OUTPUT = LOGS / "content_platform_recommendations_latest.json"
EXPERIMENTS_OUTPUT = LOGS / "content_platform_experiments_latest.json"
WEEKLY_REVIEW_OUTPUT = DOCS / "content_platform_weekly_review.md"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_weekly_review(
    *,
    health: dict[str, Any],
    recommendations: dict[str, Any],
    experiments: dict[str, Any],
) -> str:
    generated_at = datetime.now(timezone.utc).isoformat()

    channel_scores = dict(((health.get("channel_health") or {}).get("channel_scores") or {}))
    regressions = list(health.get("regressions") or [])
    triggered = [item for item in regressions if bool(item.get("triggered"))]

    recs = list(recommendations.get("recommendations") or [])
    accepted = [r for r in recs if r.get("status") == "recommended"]
    rejected = [r for r in recs if r.get("status") != "recommended"]

    exps = list(experiments.get("experiments") or [])
    rollbacked = [e for e in exps if str(((e.get("rollback") or {}).get("status") or "none")) == "triggered"]

    lines = [
        "# Content Platform Weekly Review",
        "",
        f"- Generated at UTC: {generated_at}",
        f"- Health artifact: {HEALTH_OUTPUT}",
        f"- Recommendations artifact: {RECOMMENDATIONS_OUTPUT}",
        f"- Experiments artifact: {EXPERIMENTS_OUTPUT}",
        "",
        "## System Health",
        "",
        f"- Channels scored: {len(channel_scores)}",
        f"- Triggered regressions: {len(triggered)}",
        "",
        "## Channel Health Scores",
        "",
    ]

    if channel_scores:
        for channel_id in sorted(channel_scores.keys()):
            lines.append(f"- {channel_id}: {channel_scores[channel_id]}")
    else:
        lines.append("- No channel health data available.")

    lines.extend([
        "",
        "## Regressions",
        "",
    ])

    if triggered:
        for item in triggered:
            lines.append(
                "- {name}: current={current} baseline={baseline} delta={delta} confidence={confidence}".format(
                    name=item.get("name"),
                    current=item.get("current"),
                    baseline=item.get("baseline"),
                    delta=item.get("delta"),
                    confidence=item.get("confidence"),
                )
            )
    else:
        lines.append("- No triggered regressions in current window.")

    lines.extend([
        "",
        "## Recommendation Pipeline",
        "",
        f"- Recommended: {len(accepted)}",
        f"- Rejected/blocked: {len(rejected)}",
        "",
    ])

    for rec in accepted[:10]:
        lines.append(f"- RECOMMENDED {rec.get('type')}: {rec.get('action')} (confidence={rec.get('confidence')})")
    for rec in rejected[:10]:
        lines.append(
            f"- BLOCKED {rec.get('type')}: {rec.get('reason') or rec.get('blocked_by_rule') or 'not_recommended'}"
        )

    lines.extend([
        "",
        "## Experiments",
        "",
        f"- Tracked experiments: {len(exps)}",
        f"- Rollback-triggered experiments: {len(rollbacked)}",
        "",
        "## Governance Notes",
        "",
        "- No automatic production rollout is allowed without validated canary evidence and explicit approval.",
        "- Topic accuracy and safety floors are enforced before any change can enter canary.",
        "- Every learned adjustment is persisted in content_platform_learning_audit.jsonl.",
        "",
    ])

    return "\n".join(lines)


def run(
    *,
    performance_path: Path,
    routing_guard_path: Path,
    experiment_registry_path: Path,
    learning_audit_path: Path,
) -> dict[str, Any]:
    payload = run_control_loop(
        performance_path=performance_path,
        routing_guard_path=routing_guard_path,
        experiment_registry_path=experiment_registry_path,
        learning_audit_path=learning_audit_path,
        rules=LearningRules(),
    )

    _write_json(HEALTH_OUTPUT, dict(payload.get("health") or {}))
    _write_json(RECOMMENDATIONS_OUTPUT, dict(payload.get("recommendations") or {}))
    _write_json(EXPERIMENTS_OUTPUT, dict(payload.get("experiments") or {}))

    WEEKLY_REVIEW_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    WEEKLY_REVIEW_OUTPUT.write_text(
        _build_weekly_review(
            health=dict(payload.get("health") or {}),
            recommendations=dict(payload.get("recommendations") or {}),
            experiments=dict(payload.get("experiments") or {}),
        ),
        encoding="utf-8",
    )

    health = dict(payload.get("health") or {})
    regressions = list(health.get("regressions") or [])
    recommendation_count = len(list((payload.get("recommendations") or {}).get("recommendations") or []))

    summary = {
        "ok": True,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "artifacts": {
            "health": str(HEALTH_OUTPUT),
            "recommendations": str(RECOMMENDATIONS_OUTPUT),
            "experiments": str(EXPERIMENTS_OUTPUT),
            "weekly_review": str(WEEKLY_REVIEW_OUTPUT),
        },
        "metrics": {
            "channels": len(dict((health.get("channel_health") or {}).get("channel_scores") or {})),
            "triggered_regressions": sum(1 for item in regressions if bool(item.get("triggered"))),
            "recommendations": recommendation_count,
        },
    }

    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate content platform control loop artifacts")
    parser.add_argument("--performance-path", default=str(DEFAULT_PERFORMANCE_PATH))
    parser.add_argument("--routing-guard-path", default=str(DEFAULT_ROUTING_GUARD_PATH))
    parser.add_argument("--experiment-registry-path", default=str(DEFAULT_EXPERIMENT_REGISTRY_PATH))
    parser.add_argument("--learning-audit-path", default=str(DEFAULT_LEARNING_AUDIT_PATH))
    args = parser.parse_args(argv)

    summary = run(
        performance_path=Path(args.performance_path),
        routing_guard_path=Path(args.routing_guard_path),
        experiment_registry_path=Path(args.experiment_registry_path),
        learning_audit_path=Path(args.learning_audit_path),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
