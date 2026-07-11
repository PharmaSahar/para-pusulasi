#!/usr/bin/env python3
"""Build executive dashboard summary from governance/runtime artifacts.

Focus:
- evidence quality scoring
- top growth blockers (why, not only what)
- expected business impact with confidence/risk
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_EVIDENCE_PATH = ROOT / "logs" / "runtime_optimization_evidence_latest.json"
FLEET_PATH = ROOT / "logs" / "fleet_health_report.json"
BACKLOG_PATH = ROOT / "logs" / "optimization_backlog.json"
MEMORY_PATH = ROOT / "logs" / "optimization_memory.json"
ACTIVATION_PATH = ROOT / "logs" / "activation_controller_report.json"
BUNDLE_PATH = ROOT / "logs" / "p0_p1_artifacts_bundle_latest.json"
GOVERNANCE_RUN_PATH = ROOT / "logs" / "governance_refresh_run_latest.json"
STRICT_EVIDENCE_PATH = ROOT / "logs" / "strict_evidence_report_latest.md"
BRIDGE_LAYER_PATH = ROOT / "logs" / "governance_dashboard_bridge_latest.json"
CONTENT_PLATFORM_HEALTH_PATH = ROOT / "logs" / "content_platform_health_latest.json"
CONTENT_PLATFORM_RECOMMENDATIONS_PATH = ROOT / "logs" / "content_platform_recommendations_latest.json"
CONTENT_PLATFORM_EXPERIMENTS_PATH = ROOT / "logs" / "content_platform_experiments_latest.json"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _health_status(fleet: dict[str, Any], runtime_ok: bool) -> str:
    fleet_counts = dict(fleet.get("fleet") or {})
    red_count = int(fleet_counts.get("red_channels", 0) or 0)
    yellow_count = int(fleet_counts.get("yellow_channels", 0) or 0)

    if not runtime_ok:
        return "at_risk"
    if red_count > 0:
        return "at_risk"
    if yellow_count > 0:
        return "watch"
    return "healthy"


def _impact_gain_text(expected_impact: str) -> str:
    normalized = str(expected_impact or "").strip().lower()
    if normalized == "high":
        return "~3-8% relative KPI improvement if executed safely"
    if normalized == "medium":
        return "~1-3% relative KPI improvement if executed safely"
    if normalized == "low":
        return "<1% relative KPI improvement"
    return "impact_not_estimated"


def _normalize_evidence_status(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"observed", "measured"}:
        return "observed"
    if normalized in {"inferred"}:
        return "inferred"
    if normalized in {"insufficient_evidence", "no_evidence", "unknown", ""}:
        return "insufficient_evidence"
    return "insufficient_evidence"


def _rollback_difficulty(estimated_risk: str) -> str:
    normalized = str(estimated_risk or "").strip().lower()
    if normalized == "low":
        return "low"
    if normalized == "high":
        return "high"
    return "medium"


def _strict_report_line_value(report_text: str, key: str) -> str | None:
    prefix = f"- {key}:"
    for line in report_text.splitlines():
        raw = str(line or "").strip()
        if raw.startswith(prefix):
            value = raw.split(":", 1)[1].strip()
            return value or None
    return None


def _build_p0_thumbnail_auth_worklist(*, bundle: dict[str, Any]) -> dict[str, Any]:
    streak_payload = dict(((bundle.get("artifacts") or {}).get("thumbnail_streak_path") or {}).get("payload") or {})
    required_streak = int(streak_payload.get("required_streak", 3) or 3)
    rows = [row for row in list(streak_payload.get("rows") or []) if isinstance(row, dict)]
    blocked_rows = [row for row in rows if str(row.get("state") or "").strip().lower() == "blocked"]

    worklist: list[dict[str, Any]] = []
    for row in blocked_rows:
        probe = dict(row.get("last_probe") or {})
        worklist.append(
            {
                "channel_id": str(row.get("channel_id") or "").strip(),
                "state": "blocked",
                "block_reason": str(row.get("block_reason") or row.get("last_reason") or "unknown"),
                "success_streak": int(row.get("success_streak", 0) or 0),
                "remaining_successes": int(row.get("remaining_successes", required_streak) or required_streak),
                "last_probe_status": probe.get("status"),
                "youtube_channel_id": probe.get("authenticated_channel_id"),
                "youtube_channel_title": probe.get("authenticated_channel_title"),
                "next_actions": [
                    "youtube_brand_or_channel_permission_fix",
                    "channel_token_reauth",
                    "run_thumbnail_only_probe_until_streak_met",
                ],
                "exit_criteria": {
                    "required_success_streak": required_streak,
                    "thumbnail_set_403_recurrence": "must_be_zero_in_observation_window",
                },
                "maturity_status": "REPORTED",
            }
        )

    worklist.sort(key=lambda item: str(item.get("channel_id") or ""))
    return {
        "required_success_streak": required_streak,
        "blocked_channels_total": len(worklist),
        "worklist": worklist,
    }


def _build_p1_validation_queue_worklist(
    *,
    activation: dict[str, Any],
    fleet: dict[str, Any],
    bundle: dict[str, Any],
) -> dict[str, Any]:
    trace_payload = dict(((bundle.get("artifacts") or {}).get("trace_completeness") or {}).get("payload") or {})
    upload_runs = dict(((trace_payload.get("trace_completeness") or {}).get("upload_runs_by_channel") or {}))
    coverage = dict(trace_payload.get("metrics_coverage") or {})
    ctr_cov = float(dict(coverage.get("click_through_rate") or {}).get("percent", 0.0) or 0.0)
    wt_cov = float(dict(coverage.get("watch_time_hours") or {}).get("percent", 0.0) or 0.0)
    imp_cov = float(dict(coverage.get("impressions") or {}).get("percent", 0.0) or 0.0)
    avd_cov = float(dict(coverage.get("average_view_duration_seconds") or {}).get("percent", 0.0) or 0.0)

    analytics_gate_go = bool((((activation.get("gates") or {}).get("analytics_api_probe") or {}).get("go", False)))
    analytics_reason = str((((activation.get("gates") or {}).get("analytics_api_probe") or {}).get("reason") or "unknown"))
    downstream_consumption_ok = min(ctr_cov, wt_cov, imp_cov, avd_cov) > 0.0

    fleet_channels = [row for row in list(fleet.get("channels") or []) if isinstance(row, dict)]
    channel_ids = sorted(
        {
            *(str(row.get("channel_id") or "").strip() for row in fleet_channels),
            *(str(cid).strip() for cid in upload_runs.keys()),
        }
    )
    channel_ids = [cid for cid in channel_ids if cid]

    rows: list[dict[str, Any]] = []
    for channel_id in channel_ids:
        fleet_row = next((row for row in fleet_channels if str(row.get("channel_id") or "").strip() == channel_id), {})
        analytics_data_status = str(fleet_row.get("analytics_data_status") or "UNKNOWN").strip().upper()
        eligible_input_seen = int(upload_runs.get(channel_id, 0) or 0) > 0
        rows_appended_evidence = analytics_data_status == "OBSERVED"

        criteria = {
            "analytics_api_go": analytics_gate_go,
            "eligible_input_seen": eligible_input_seen,
            "rows_appended_evidence": rows_appended_evidence,
            "downstream_consumption_evidence": downstream_consumption_ok,
        }
        missing = [name for name, ok in criteria.items() if not bool(ok)]
        rows.append(
            {
                "channel_id": channel_id,
                "validation_queue_status": "READY_TO_EXIT" if not missing else "VALIDATION_QUEUE",
                "criteria": criteria,
                "missing_criteria": missing,
                "analytics_data_status": analytics_data_status,
                "upload_runs_considered": int(upload_runs.get(channel_id, 0) or 0),
                "analytics_gate_reason": analytics_reason,
                "next_actions": [
                    "enable_and_verify_analytics_api_probe",
                    "collect_eligible_upload_inputs",
                    "append_backfill_rows_and_verify",
                    "confirm_downstream_metric_consumption",
                ],
                "maturity_status": "REPORTED",
            }
        )

    rows.sort(key=lambda item: (str(item.get("validation_queue_status") or ""), str(item.get("channel_id") or "")))
    ready_count = sum(1 for row in rows if row.get("validation_queue_status") == "READY_TO_EXIT")
    return {
        "status": "VALIDATION_QUEUE",
        "channels_total": len(rows),
        "ready_to_exit_channels": ready_count,
        "worklist": rows,
    }


def _strict_evidence_bridge_layer(
    *,
    activation: dict[str, Any],
    fleet: dict[str, Any],
    bundle: dict[str, Any],
    governance_run: dict[str, Any],
) -> dict[str, Any]:
    strict_report = _read_text(STRICT_EVIDENCE_PATH)
    strict_date = None
    first_line = strict_report.splitlines()[0].strip() if strict_report else ""
    if first_line.startswith("# Strict Evidence Report - "):
        strict_date = first_line.replace("# Strict Evidence Report - ", "").strip() or None

    strict_activation_state = _strict_report_line_value(strict_report, "Activation learning state")
    strict_p1_status = _strict_report_line_value(strict_report, "P1 backfill SLO")

    p0_auth = _build_p0_thumbnail_auth_worklist(bundle=bundle)
    p1_queue = _build_p1_validation_queue_worklist(activation=activation, fleet=fleet, bundle=bundle)

    return {
        "schema_version": "v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "maturity_lifecycle": ["PLANNED", "REPORTED", "PROVEN", "VALIDATED", "ROLLED_OUT"],
        "max_claim_maturity": "REPORTED",
        "strict_evidence": {
            "path": str(STRICT_EVIDENCE_PATH),
            "exists": STRICT_EVIDENCE_PATH.exists(),
            "report_date": strict_date,
            "activation_learning_state": strict_activation_state,
            "p1_backfill_status": strict_p1_status,
        },
        "p0_thumbnail_youtube_auth_followup": p0_auth,
        "p1_analytics_validation_queue": p1_queue,
        "governance_dashboard_binding": {
            "governance_ok": bool(governance_run.get("ok", False)),
            "governance_degraded": bool(governance_run.get("degraded", False)),
            "activation_system_status": activation.get("system_status"),
            "fleet_active_channels": int(((fleet.get("fleet") or {}).get("active_channels", 0) or 0)),
        },
    }


def _evidence_quality(
    *,
    runtime_evidence: dict[str, Any],
    fleet: dict[str, Any],
    backlog: dict[str, Any],
    memory: dict[str, Any],
    activation: dict[str, Any],
    bundle: dict[str, Any],
    governance_run: dict[str, Any],
) -> dict[str, Any]:
    steps = dict(runtime_evidence.get("steps") or {})
    step_count = len(steps)
    step_ok_count = sum(1 for _, item in steps.items() if bool((item or {}).get("ok", False)))

    factors = [
        {
            "name": "runtime_evidence_ok",
            "weight": 20,
            "pass": bool(runtime_evidence.get("ok", False)),
            "note": "latest runtime cycle result",
        },
        {
            "name": "runtime_steps_completeness",
            "weight": 15,
            "pass": step_count > 0 and step_ok_count == step_count,
            "note": f"{step_ok_count}/{step_count} runtime steps ok",
        },
        {
            "name": "fleet_snapshot_present",
            "weight": 10,
            "pass": int(((fleet.get("fleet") or {}).get("active_channels", 0) or 0)) > 0,
            "note": "fleet health has active channels",
        },
        {
            "name": "activation_snapshot_present",
            "weight": 10,
            "pass": bool(activation.get("system_status")),
            "note": "activation controller status available",
        },
        {
            "name": "p0_bundle_present",
            "weight": 10,
            "pass": bool(bundle.get("summary")),
            "note": "p0/p1 bundle summary available",
        },
        {
            "name": "backlog_observed",
            "weight": 10,
            "pass": len(list(backlog.get("backlog") or [])) > 0,
            "note": "optimization backlog contains ranked items",
        },
        {
            "name": "memory_present",
            "weight": 10,
            "pass": str(memory.get("status") or "ok").strip().lower() in {"ok", "insufficient_data"},
            "note": "optimization memory artifact present",
        },
        {
            "name": "governance_refresh_latest_ok",
            "weight": 5,
            "pass": bool(governance_run.get("ok", False)),
            "note": "latest governance refresh run status",
        },
        {
            "name": "production_duration_observed",
            "weight": 10,
            "pass": False,
            "note": "multi-day stability window not yet verified",
        },
    ]

    score = sum(int(item["weight"]) for item in factors if bool(item["pass"]))
    failed = [item["name"] for item in factors if not bool(item["pass"])]

    return {
        "score": int(score),
        "max_score": 100,
        "grade": "high" if score >= 85 else ("medium" if score >= 65 else "low"),
        "factors": factors,
        "failed_factors": failed,
    }


def _top_growth_blockers(
    *,
    bundle: dict[str, Any],
    fleet: dict[str, Any],
    activation: dict[str, Any],
    backlog_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    summary = dict(bundle.get("summary") or {})
    fleet_summary = dict(fleet.get("fleet") or {})

    blocked_channels = int(summary.get("streak_blocked_channels", 0) or 0)
    p0a_pending = int(summary.get("p0a_guard_review_pending", 0) or 0)
    p0b_rows = int(summary.get("p0b_shorts_safety_rows", 0) or 0)
    activation_status = str(summary.get("activation_system_status") or activation.get("system_status") or "")
    no_data_channels = int(fleet_summary.get("channels_without_data_last_24h", 0) or 0)

    blockers: list[dict[str, Any]] = []

    if activation_status and activation_status != "ready_for_learning_activation":
        blockers.append(
            {
                "title": "Activation gate blocked",
                "why": "Learning rollout cannot proceed while activation controller is blocked.",
                "metric": "activation_system_status",
                "current_value": activation_status,
                "severity": "high",
                "evidence_status": "observed",
            }
        )

    if blocked_channels > 0:
        blockers.append(
            {
                "title": "Thumbnail permission bottleneck",
                "why": "Blocked thumbnail permissions reduce publish quality loop and learning throughput.",
                "metric": "streak_blocked_channels",
                "current_value": blocked_channels,
                "severity": "high",
                "evidence_status": "observed",
            }
        )

    if p0a_pending > 0:
        blockers.append(
            {
                "title": "P0-A review labeling gap",
                "why": "Without review labels, precision/false-block rates cannot be validated.",
                "metric": "p0a_guard_review_pending",
                "current_value": p0a_pending,
                "severity": "medium",
                "evidence_status": "insufficient_evidence",
            }
        )

    if p0b_rows == 0:
        blockers.append(
            {
                "title": "P0-B safety evidence gap",
                "why": "No structured short safety decisions means visual safety KPIs are not validated.",
                "metric": "p0b_shorts_safety_rows",
                "current_value": p0b_rows,
                "severity": "medium",
                "evidence_status": "insufficient_evidence",
            }
        )

    if no_data_channels > 0:
        blockers.append(
            {
                "title": "Data freshness gap",
                "why": "Channels without recent data reduce confidence in optimization decisions.",
                "metric": "channels_without_data_last_24h",
                "current_value": no_data_channels,
                "severity": "medium",
                "evidence_status": "observed",
            }
        )

    # Backlog-driven blockers as fallback/detail
    for item in backlog_items:
        signal = str(item.get("signal") or "").strip()
        if not signal:
            continue
        blockers.append(
            {
                "title": f"Backlog signal: {signal}",
                "why": str(item.get("reason") or "backlog identified issue"),
                "metric": signal,
                "current_value": item.get("value"),
                "severity": str(item.get("expected_impact") or "low"),
                "evidence_status": str(item.get("evidence_status") or "unknown"),
            }
        )

    # De-duplicate blockers by title+metric so we don't overstate the same issue.
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in blockers:
        key = (str(item.get("title") or "").strip().lower(), str(item.get("metric") or "").strip().lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    severity_rank = {"high": 0, "medium": 1, "low": 2}
    deduped.sort(key=lambda x: (severity_rank.get(str(x.get("severity") or "low").lower(), 3), str(x.get("title") or "")))
    return deduped[:5]


def _expected_business_impact(backlog_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in backlog_items[:5]:
        expected_impact = str(item.get("expected_impact") or "unknown")
        estimated_risk = str(item.get("estimated_risk") or "medium")
        evidence_status = _normalize_evidence_status(item.get("evidence_status"))
        evidence_source = str(item.get("evidence_source") or BACKLOG_PATH)
        sample_count = int(item.get("sample_count", 0) or 0)
        observation_window = str(item.get("observation_window") or "unknown_window")

        has_sufficient_evidence = evidence_status == "observed" and sample_count > 0
        impact_status = "inferred" if has_sufficient_evidence else "unknown"

        raw_confidence = item.get("confidence")
        confidence_method = "backlog_input_with_observed_evidence"
        if has_sufficient_evidence:
            try:
                confidence_value = float(raw_confidence) if raw_confidence is not None else 0.6
                confidence: Any = round(max(0.0, min(1.0, confidence_value)), 3)
            except Exception:
                confidence = 0.6
        else:
            confidence = "insufficient_evidence"
            confidence_method = "insufficient_evidence_guardrail"

        estimated_kpi_gain: Any = _impact_gain_text(expected_impact) if has_sufficient_evidence else None

        items.append(
            {
                "recommendation": str(item.get("recommended_work") or item.get("signal") or "unspecified"),
                "expected_impact": expected_impact,
                "impact_status": impact_status,
                "confidence": confidence,
                "confidence_method": confidence_method,
                "risk": estimated_risk,
                "estimated_kpi_gain": estimated_kpi_gain,
                "rollback_difficulty": _rollback_difficulty(estimated_risk),
                "evidence_status": evidence_status,
                "evidence_source": evidence_source,
                "sample_count": sample_count,
                "observation_window": observation_window,
            }
        )
    return items


def build_dashboard() -> dict[str, Any]:
    runtime_evidence = _read_json(RUNTIME_EVIDENCE_PATH)
    fleet = _read_json(FLEET_PATH)
    backlog = _read_json(BACKLOG_PATH)
    memory = _read_json(MEMORY_PATH)
    activation = _read_json(ACTIVATION_PATH)
    bundle = _read_json(BUNDLE_PATH)
    governance_run = _read_json(GOVERNANCE_RUN_PATH)
    content_platform_health = _read_json(CONTENT_PLATFORM_HEALTH_PATH)
    content_platform_recommendations = _read_json(CONTENT_PLATFORM_RECOMMENDATIONS_PATH)
    content_platform_experiments = _read_json(CONTENT_PLATFORM_EXPERIMENTS_PATH)

    runtime_steps = dict(runtime_evidence.get("steps") or {})
    backlog_items = list(backlog.get("backlog") or [])
    memory_insights = list(memory.get("insights") or [])

    top_priority = None
    if backlog_items:
        top_priority = min(int(item.get("priority", 999) or 999) for item in backlog_items)

    runtime_ok = bool(runtime_evidence.get("ok", False))
    fleet_counts = dict(fleet.get("fleet") or {})
    blockers = _top_growth_blockers(
        bundle=bundle,
        fleet=fleet,
        activation=activation,
        backlog_items=backlog_items,
    )
    business_impact = _expected_business_impact(backlog_items)
    evidence_quality = _evidence_quality(
        runtime_evidence=runtime_evidence,
        fleet=fleet,
        backlog=backlog,
        memory=memory,
        activation=activation,
        bundle=bundle,
        governance_run=governance_run,
    )
    strict_evidence_bridge = _strict_evidence_bridge_layer(
        activation=activation,
        fleet=fleet,
        bundle=bundle,
        governance_run=governance_run,
    )

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "platform_status": _health_status(fleet, runtime_ok),
        "runtime_evidence": {
            "ok": runtime_ok,
            "target_channel": runtime_evidence.get("target_channel"),
            "flag_changed": bool(runtime_evidence.get("flag_changed", False)),
            "steps_ok": {
                name: bool((detail or {}).get("ok", False))
                for name, detail in runtime_steps.items()
            },
            "artifact": str(RUNTIME_EVIDENCE_PATH),
        },
        "activation": {
            "system_status": activation.get("system_status"),
            "analytics_gate_go": bool((((activation.get("gates") or {}).get("analytics_api_probe") or {}).get("go", False))),
            "thumbnail_gate_go": bool((((activation.get("gates") or {}).get("thumbnail_permission_probe") or {}).get("go", False))),
            "runtime_gate_go": bool((((activation.get("gates") or {}).get("runtime_policy_engine") or {}).get("go", False))),
            "report": str(ACTIVATION_PATH),
        },
        "fleet": {
            "active_channels": int(fleet_counts.get("active_channels", 0) or 0),
            "green_channels": int(fleet_counts.get("green_channels", 0) or 0),
            "yellow_channels": int(fleet_counts.get("yellow_channels", 0) or 0),
            "red_channels": int(fleet_counts.get("red_channels", 0) or 0),
            "safe_mode_channels": int(fleet_counts.get("safe_mode_channels", 0) or 0),
            "report": str(FLEET_PATH),
        },
        "optimization_backlog": {
            "item_count": len(backlog_items),
            "top_priority": top_priority,
            "top_items": backlog_items[:3],
            "report": str(BACKLOG_PATH),
        },
        "optimization_memory": {
            "insight_count": len(memory_insights),
            "coverage": memory.get("coverage") or {},
            "top_insights": memory_insights[:5],
            "report": str(MEMORY_PATH),
        },
        "evidence_quality": evidence_quality,
        "top_growth_blockers": blockers,
        "expected_business_impact": business_impact,
        "strict_evidence_bridge_layer": strict_evidence_bridge,
        "content_platform_control_loop": {
            "health": {
                "path": str(CONTENT_PLATFORM_HEALTH_PATH),
                "exists": CONTENT_PLATFORM_HEALTH_PATH.exists(),
                "system_health_score": ((content_platform_health.get("channel_health") or {}).get("system_health_score")),
                "channels_scored": len(dict(((content_platform_health.get("channel_health") or {}).get("channel_scores") or {}))),
                "triggered_regressions": sum(
                    1 for item in list(content_platform_health.get("regressions") or []) if bool(item.get("triggered"))
                ),
            },
            "recommendations": {
                "path": str(CONTENT_PLATFORM_RECOMMENDATIONS_PATH),
                "exists": CONTENT_PLATFORM_RECOMMENDATIONS_PATH.exists(),
                "recommendation_count": len(list(content_platform_recommendations.get("recommendations") or [])),
                "stages": dict(content_platform_recommendations.get("separation_of_stages") or {}),
            },
            "experiments": {
                "path": str(CONTENT_PLATFORM_EXPERIMENTS_PATH),
                "exists": CONTENT_PLATFORM_EXPERIMENTS_PATH.exists(),
                "tracked_experiments": len(list(content_platform_experiments.get("experiments") or [])),
                "rollback_triggered": sum(
                    1
                    for item in list(content_platform_experiments.get("experiments") or [])
                    if str(((item.get("rollback") or {}).get("status") or "none")) == "triggered"
                ),
            },
        },
        "governance": {
            "rule": "new module accepted only with runtime evidence and decision impact",
            "claim_discipline": [
                "implementation_reported",
                "runtime_deployment_reported",
                "multi_day_stability_required_before_live_claim",
            ],
            "data_freshness_inputs": {
                "runtime": str(RUNTIME_EVIDENCE_PATH),
                "fleet": str(FLEET_PATH),
                "backlog": str(BACKLOG_PATH),
                "memory": str(MEMORY_PATH),
                "bundle": str(BUNDLE_PATH),
                "governance_run": str(GOVERNANCE_RUN_PATH),
            },
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate executive dashboard report")
    parser.add_argument("--output", default=str(ROOT / "logs" / "executive_dashboard.json"))
    args = parser.parse_args(argv)

    report = build_dashboard()
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    BRIDGE_LAYER_PATH.parent.mkdir(parents=True, exist_ok=True)
    BRIDGE_LAYER_PATH.write_text(
        json.dumps(report.get("strict_evidence_bridge_layer") or {}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "report": str(out_path),
                "platform_status": report["platform_status"],
                "runtime_ok": report["runtime_evidence"]["ok"],
                "evidence_quality_score": report["evidence_quality"]["score"],
                "backlog_items": report["optimization_backlog"]["item_count"],
                "memory_insights": report["optimization_memory"]["insight_count"],
                "strict_bridge_report": str(BRIDGE_LAYER_PATH),
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
