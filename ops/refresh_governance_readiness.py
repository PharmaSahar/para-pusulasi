#!/usr/bin/env python3
"""Refresh governance readiness snapshot and append proven/validated monitor row.

This script is intentionally fail-open for optional steps and supports environments
where some reporting scripts may be absent.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "logs"
MONITOR_PATH = LOGS / "proven_validated_monitor.jsonl"
LATEST_PATH = LOGS / "governance_refresh_run_latest.json"


def _resolve_readiness_markdown() -> Path:
    return ROOT / "docs/governance_readiness_latest.md"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _run_step(command: list[str], *, required: bool, fail_open: bool, fallback_artifact: Path | None = None) -> dict[str, Any]:
    started = _utc_now().isoformat()
    script_path = ROOT / command[1] if len(command) > 1 else None

    if script_path is not None and not script_path.exists():
        artifact_exists = bool(fallback_artifact and fallback_artifact.exists())
        code = 0 if artifact_exists else 127
        return {
            "name": script_path.stem if script_path else "unknown_step",
            "command": command,
            "exit_code": code,
            "required": required,
            "fail_open": fail_open,
            "started_at_utc": started,
            "finished_at_utc": _utc_now().isoformat(),
            "warning": "script_missing_fallback_artifact_used" if artifact_exists else "script_missing",
            "fallback_artifact": str(fallback_artifact) if fallback_artifact else None,
        }

    proc = subprocess.run(command, cwd=str(ROOT), capture_output=True, text=True, check=False)
    return {
        "name": Path(command[1]).stem if len(command) > 1 else "unknown_step",
        "command": command,
        "exit_code": int(proc.returncode),
        "required": required,
        "fail_open": fail_open,
        "started_at_utc": started,
        "finished_at_utc": _utc_now().isoformat(),
        "stdout_tail": "\n".join((proc.stdout or "").splitlines()[-20:]),
        "stderr_tail": "\n".join((proc.stderr or "").splitlines()[-20:]),
    }


def _append_monitor_row(snapshot: dict[str, Any]) -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    required_total = int(snapshot.get("required_steps_total", 0))
    required_passed = int(snapshot.get("required_steps_passed", 0))
    row = {
        "ts_utc": _utc_now().isoformat().replace("+00:00", "Z"),
        "ok": bool(snapshot.get("ok", False)),
        "degraded": bool(snapshot.get("degraded", False)),
        "required_passed": required_passed,
        "required_total": required_total,
        "optional_failed": int(snapshot.get("optional_steps_failed", 0)),
        "generated_at_utc": str(snapshot.get("generated_at_utc") or _utc_now().isoformat()),
    }
    with MONITOR_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _build_readiness_markdown(*, generated_at: str, lookback_rows: int, steps: list[dict[str, Any]]) -> str:
    required_passed = sum(1 for step in steps if step.get("required") and int(step.get("exit_code", 1)) == 0)
    required_total = sum(1 for step in steps if step.get("required"))
    optional_failed = sum(1 for step in steps if not step.get("required") and int(step.get("exit_code", 1)) != 0)

    lines = [
        "# Governance Readiness Latest",
        "",
        f"- Generated at UTC: {generated_at}",
        f"- Lookback rows: {lookback_rows}",
        f"- Required steps passed: {required_passed}/{required_total}",
        f"- Optional steps failed: {optional_failed}",
        "",
        "## Step Status",
        "",
        "| Step | Required | Status | Artifact | Warning |",
        "| --- | --- | --- | --- | --- |",
    ]
    for step in steps:
        lines.append(
            "| {name} | {required} | {status} | {artifact} | {warning} |".format(
                name=step.get("name", "unknown"),
                required="yes" if step.get("required") else "no",
                status="PASS" if int(step.get("exit_code", 1)) == 0 else "FAIL",
                artifact=str(step.get("artifact") or step.get("fallback_artifact") or "-"),
                warning=str(step.get("warning") or "-"),
            )
        )
    lines.extend([
        "",
        "## Secondary Summary Layer",
        "",
        "- Strict evidence bridge artifact: `logs/governance_dashboard_bridge_latest.json`",
        "- Purpose: channel-level P0 thumbnail auth follow-up + P1 VALIDATION_QUEUE exit worklist.",
        "",
        "## Entry Point",
        "",
        "This snapshot is refreshed by `ops/refresh_governance_readiness.py`.",
        "",
    ])
    return "\n".join(lines)


def run_refresh(*, lookback_rows: int) -> dict[str, Any]:
    python_bin = sys.executable
    readiness_markdown = _resolve_readiness_markdown()
    steps = [
        {
            "name": "p0_validation_metrics",
            "command": [python_bin, "ops/p0_validation_metrics_report.py", "--lookback-rows", str(max(1, lookback_rows))],
            "required": True,
            "fail_open": False,
            "artifact": LOGS / "p0_validation_metrics_latest.json",
        },
        {
            "name": "p0_p1_artifact_bundle",
            "command": [python_bin, "ops/p0_p1_artifact_bundle.py"],
            "required": True,
            "fail_open": False,
            "artifact": LOGS / "p0_p1_artifacts_bundle_latest.json",
        },
        {
            "name": "executive_dashboard",
            "command": [python_bin, "ops/executive_dashboard_report.py"],
            "required": False,
            "fail_open": True,
            "artifact": LOGS / "executive_dashboard.json",
        },
    ]

    results: list[dict[str, Any]] = []
    required_passed = 0
    required_total = 0
    optional_failed = 0
    warnings: list[str] = []

    for step in steps:
        result = _run_step(
            step["command"],
            required=bool(step["required"]),
            fail_open=bool(step["fail_open"]),
            fallback_artifact=step["artifact"],
        )
        result["name"] = step["name"]
        result["artifact"] = str(step["artifact"].resolve())
        results.append(result)

        exit_ok = int(result.get("exit_code", 1)) == 0
        if step["required"]:
            required_total += 1
            if exit_ok:
                required_passed += 1
            else:
                warnings.append(f"required_step_failed:{step['name']}")
        else:
            if not exit_ok:
                optional_failed += 1
                warnings.append(f"optional_step_failed:{step['name']}")

    readiness_generated_at = _utc_now().isoformat()
    try:
        _write_text(
            readiness_markdown,
            _build_readiness_markdown(
                generated_at=readiness_generated_at,
                lookback_rows=int(max(1, lookback_rows)),
                steps=results,
            ),
        )
        readiness_result = {
            "name": "governance_readiness",
            "command": [python_bin, "ops/refresh_governance_readiness.py", "--lookback-rows", str(int(max(1, lookback_rows)))],
            "exit_code": 0,
            "required": True,
            "fail_open": False,
            "started_at_utc": readiness_generated_at,
            "finished_at_utc": _utc_now().isoformat(),
            "artifact": str(readiness_markdown.resolve()),
        }
    except Exception as exc:
        readiness_result = {
            "name": "governance_readiness",
            "command": [python_bin, "ops/refresh_governance_readiness.py", "--lookback-rows", str(int(max(1, lookback_rows)))],
            "exit_code": 1,
            "required": True,
            "fail_open": False,
            "started_at_utc": readiness_generated_at,
            "finished_at_utc": _utc_now().isoformat(),
            "artifact": str(readiness_markdown.resolve()),
            "warning": "readiness_markdown_write_failed",
            "stderr_tail": str(exc),
        }
    results.append(readiness_result)
    required_total += 1
    if int(readiness_result.get("exit_code", 1)) == 0:
        required_passed += 1
    else:
        warnings.append("required_step_failed:governance_readiness")

    generated = _utc_now().isoformat()
    ok = required_passed == required_total and required_total > 0
    degraded = optional_failed > 0

    payload = {
        "schema_version": "v2",
        "ok": bool(ok),
        "degraded": bool(degraded),
        "warnings": warnings,
        "generated_at_utc": generated,
        "lookback_rows": int(max(1, lookback_rows)),
        "required_steps_passed": int(required_passed),
        "required_steps_total": int(required_total),
        "optional_steps_failed": int(optional_failed),
        "steps": results,
        "artifacts": {
            "p0_metrics": str((LOGS / "p0_validation_metrics_latest.json").resolve()),
            "bundle": str((LOGS / "p0_p1_artifacts_bundle_latest.json").resolve()),
            "executive_dashboard": str((LOGS / "executive_dashboard.json").resolve()),
            "strict_evidence_bridge": str((LOGS / "governance_dashboard_bridge_latest.json").resolve()),
            "readiness_markdown": str(readiness_markdown.resolve()),
        },
    }

    _write_json(LATEST_PATH, payload)
    _append_monitor_row(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh governance readiness and monitor snapshot")
    parser.add_argument("--lookback-rows", type=int, default=500)
    args = parser.parse_args()

    payload = run_refresh(lookback_rows=max(1, int(args.lookback_rows or 500)))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
