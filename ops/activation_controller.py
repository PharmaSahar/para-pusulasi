#!/usr/bin/env python3
"""Controlled activation controller for analytics and thumbnail learning gates.

Safety model:
- This script never writes new code or mutates runtime behavior by itself.
- It only evaluates evidence (probe + cache), writes a readiness report,
  and optionally applies pre-defined feature flags via explicit command.
- Activation is blocked unless all hard gates are GO.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.runtime_storage import runtime_path

ROOT = Path(__file__).resolve().parents[1]
ANALYTICS_PROBE_SCRIPT = ROOT / "ops" / "analytics_single_channel_probe.py"


def _env_path(key: str, default: Path) -> Path:
    raw = str(os.getenv(key, "")).strip()
    return Path(raw) if raw else default


def _preprod_isolation_enabled() -> bool:
    raw = str(os.getenv("PREPROD_ISOLATION_MODE", "false")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _assert_preprod_mutable_path(path: Path, *, env_key: str) -> None:
    if not _preprod_isolation_enabled():
        return

    root_raw = str(os.getenv("PREPROD_STATE_ROOT", "")).strip()
    if not root_raw:
        raise RuntimeError("preprod_isolation_invalid: PREPROD_STATE_ROOT missing")

    if not str(os.getenv(env_key, "")).strip():
        raise RuntimeError(f"preprod_isolation_invalid: {env_key} missing")

    resolved = path.resolve()
    state_root = Path(root_raw).resolve()
    repo_root = ROOT.resolve()

    inside_state_root = resolved == state_root or state_root in resolved.parents
    inside_repo = resolved == repo_root or repo_root in resolved.parents
    if (not inside_state_root) or inside_repo:
        raise RuntimeError(
            f"preprod_isolation_violation: {env_key}={resolved} outside PREPROD_STATE_ROOT or inside repo"
        )


THUMB_CACHE_PATH = _env_path("THUMBNAIL_PERMISSION_CACHE_PATH", runtime_path("state/thumbnail_permission_cache.json"))
DEFAULT_REPORT_PATH = _env_path("ACTIVATION_CONTROLLER_REPORT_PATH", runtime_path("state/activation_controller_report.json"))
DEFAULT_FLAGS_PATH = _env_path("ACTIVATION_FLAGS_PATH", runtime_path("state/learning_activation_flags.json"))
DEFAULT_REPORT_ARCHIVE_DIR = _env_path("ACTIVATION_CONTROLLER_REPORT_ARCHIVE_DIR", ROOT / "output" / "state" / "activation_reports")


@dataclass
class GateDecision:
    name: str
    go: bool
    status: str
    reason: str
    evidence: dict[str, Any]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_json_loads(raw: str) -> dict[str, Any]:
    raw = (raw or "").strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            snippet = raw[start : end + 1]
            try:
                return json.loads(snippet)
            except Exception:
                return {}
    return {}


def _run_analytics_probe(*, python_bin: str, channel_id: str, limit: int, timeout_seconds: int) -> dict[str, Any]:
    cmd = [
        python_bin,
        str(ANALYTICS_PROBE_SCRIPT),
        "--channel",
        channel_id,
        "--limit",
        str(limit),
    ]

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except Exception as exc:
        return {
            "attempted": True,
            "ok": False,
            "error": str(exc),
            "exit_code": None,
            "probe_result": {},
            "command": cmd,
        }

    payload = _safe_json_loads(proc.stdout)
    return {
        "attempted": True,
        "ok": proc.returncode == 0,
        "error": None if proc.returncode == 0 else (proc.stderr.strip() or "probe_failed"),
        "exit_code": proc.returncode,
        "probe_result": payload,
        "stdout_tail": "\n".join((proc.stdout or "").splitlines()[-20:]),
        "stderr_tail": "\n".join((proc.stderr or "").splitlines()[-20:]),
        "command": cmd,
    }


def _read_thumbnail_cache() -> dict[str, Any]:
    if not THUMB_CACHE_PATH.exists():
        return {"channels": {}}
    try:
        return json.loads(THUMB_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"channels": {}}


def _analytics_gate_from_probe(probe: dict[str, Any]) -> GateDecision:
    probe_result = probe.get("probe_result") if isinstance(probe, dict) else {}
    token_after = probe_result.get("token_after") if isinstance(probe_result, dict) else {}
    oauth = probe_result.get("oauth") if isinstance(probe_result, dict) else {}

    ready = bool(probe.get("ok")) and bool((token_after or {}).get("ready")) and bool((oauth or {}).get("ok"))

    if ready:
        return GateDecision(
            name="analytics_api_probe",
            go=True,
            status="go",
            reason="analytics_api_enabled_and_oauth_ready",
            evidence={
                "probe": probe,
                "token_after": token_after,
                "oauth": oauth,
            },
        )

    reason = "analytics_api_not_ready"
    if isinstance(probe, dict) and str(probe.get("error")) == "skipped_by_flag":
        reason = "analytics_probe_skipped"
    elif isinstance(probe, dict) and probe.get("error"):
        reason = "analytics_probe_execution_failed"

    return GateDecision(
        name="analytics_api_probe",
        go=False,
        status="no_go",
        reason=reason,
        evidence={
            "probe": probe,
            "token_after": token_after,
            "oauth": oauth,
        },
    )


def _thumbnail_gate_from_cache(*, channel_id: str, required_streak: int) -> GateDecision:
    cache = _read_thumbnail_cache()
    channels = dict(cache.get("channels") or {})
    entry = dict(channels.get(channel_id) or {})

    streak = int(entry.get("success_streak", 0) or 0)
    can_upload = bool(entry.get("can_upload_thumbnail", False))
    go = can_upload and streak >= int(required_streak)

    if go:
        reason = "thumbnail_set_success_streak_reached"
        status = "go"
    else:
        reason = "thumbnail_set_streak_below_threshold"
        status = "no_go"

    return GateDecision(
        name="thumbnail_permission_probe",
        go=go,
        status=status,
        reason=reason,
        evidence={
            "channel_id": channel_id,
            "required_streak": int(required_streak),
            "cache_entry": entry,
            "cache_path": str(THUMB_CACHE_PATH),
        },
    )


def _build_flags(analytics_gate: GateDecision, thumbnail_gate: GateDecision) -> dict[str, Any]:
    analytics_enabled = bool(analytics_gate.go)
    thumbnail_enabled = bool(thumbnail_gate.go)
    ready_for_learning = analytics_enabled and thumbnail_enabled

    return {
        "analytics_collector_enabled": analytics_enabled,
        "thumbnail_learning_enabled": thumbnail_enabled,
        "analytics_live_status": "go_enabled" if analytics_enabled else "no_go_api_not_enabled",
        "thumbnail_permission_status": "go_streak_met" if thumbnail_enabled else "no_go_streak_not_met",
        "ready_for_learning_activation": ready_for_learning,
        "generated_at_utc": _utc_now_iso(),
        "source": "activation_controller",
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _archive_report(*, report: dict[str, Any], archive_dir: Path) -> dict[str, str]:
    _assert_preprod_mutable_path(
        archive_dir,
        env_key="ACTIVATION_CONTROLLER_REPORT_ARCHIVE_DIR",
    )

    archive_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    stamped_path = archive_dir / f"{ts}.json"
    latest_path = archive_dir / "latest.json"

    _write_json(stamped_path, report)
    _write_json(latest_path, report)

    return {
        "stamped": str(stamped_path),
        "latest": str(latest_path),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Controlled activation controller for learning gates")
    parser.add_argument("--channel", required=True, help="Target channel id for probe/cache checks")
    parser.add_argument("--python-bin", default=sys.executable, help="Python binary for running probe scripts")
    parser.add_argument("--analytics-limit", type=int, default=3, help="Max videos for analytics probe")
    parser.add_argument("--required-thumbnail-streak", type=int, default=3, help="Required thumbnails.set success streak")
    parser.add_argument("--timeout-seconds", type=int, default=120, help="Probe timeout in seconds")
    parser.add_argument("--skip-analytics-probe", action="store_true", help="Skip running analytics probe script")
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT_PATH), help="Path to write controller report JSON")
    parser.add_argument(
        "--report-archive-dir",
        default=str(DEFAULT_REPORT_ARCHIVE_DIR),
        help="Directory for timestamped activation history reports and latest.json",
    )
    parser.add_argument("--no-report-archive", action="store_true", help="Disable writing activation history archive")
    parser.add_argument("--flags-path", default=str(DEFAULT_FLAGS_PATH), help="Path to write activation flags JSON")
    parser.add_argument("--activate-learning", action="store_true", help="Explicitly apply learning flags when all gates are GO")
    args = parser.parse_args(argv)

    if args.skip_analytics_probe:
        analytics_probe = {
            "attempted": False,
            "ok": False,
            "error": "skipped_by_flag",
            "exit_code": None,
            "probe_result": {},
            "command": [],
        }
    else:
        analytics_probe = _run_analytics_probe(
            python_bin=args.python_bin,
            channel_id=args.channel,
            limit=max(1, int(args.analytics_limit)),
            timeout_seconds=max(5, int(args.timeout_seconds)),
        )

    analytics_gate = _analytics_gate_from_probe(analytics_probe)
    thumbnail_gate = _thumbnail_gate_from_cache(
        channel_id=args.channel,
        required_streak=max(1, int(args.required_thumbnail_streak)),
    )

    flags = _build_flags(analytics_gate, thumbnail_gate)

    activation = {
        "requested": bool(args.activate_learning),
        "applied": False,
        "reason": "not_requested",
        "flags_path": str(Path(args.flags_path)),
    }

    if args.activate_learning:
        if flags.get("ready_for_learning_activation"):
            activation["applied"] = True
            activation["reason"] = "all_gates_go"
            applied_payload = dict(flags)
            applied_payload["activated_at_utc"] = _utc_now_iso()
            _write_json(Path(args.flags_path), applied_payload)
        else:
            activation["applied"] = False
            activation["reason"] = "blocked_by_no_go"

    report = {
        "controller": "activation_controller",
        "generated_at_utc": _utc_now_iso(),
        "channel_id": args.channel,
        "gates": {
            "analytics_api_probe": {
                "go": analytics_gate.go,
                "status": analytics_gate.status,
                "reason": analytics_gate.reason,
                "evidence": analytics_gate.evidence,
            },
            "thumbnail_permission_probe": {
                "go": thumbnail_gate.go,
                "status": thumbnail_gate.status,
                "reason": thumbnail_gate.reason,
                "evidence": thumbnail_gate.evidence,
            },
        },
        "flags": flags,
        "activation": activation,
        "system_status": "ready_for_learning_activation"
        if flags.get("ready_for_learning_activation")
        else "blocked_for_learning_activation",
        "safety_policy": {
            "analytics_api_go_required": True,
            "thumbnail_success_streak_required": int(args.required_thumbnail_streak),
            "explicit_activation_command_required": True,
            "auto_code_generation": False,
        },
    }

    report_path = Path(args.report_path)
    _write_json(report_path, report)

    archive_paths = None
    if not args.no_report_archive:
        archive_paths = _archive_report(report=report, archive_dir=Path(args.report_archive_dir))

    if archive_paths:
        report["report_paths"] = {
            "report_path": str(report_path),
            "archive_stamped": archive_paths["stamped"],
            "archive_latest": archive_paths["latest"],
        }
        _write_json(report_path, report)
        _write_json(Path(archive_paths["stamped"]), report)
        _write_json(Path(archive_paths["latest"]), report)

    print(json.dumps(report, ensure_ascii=False, indent=2))

    if args.activate_learning and not activation["applied"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
