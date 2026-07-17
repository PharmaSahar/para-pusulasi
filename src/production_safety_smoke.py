from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from types import SimpleNamespace

from .analytics_quality_guard import validate_performance_snapshot
from .channel_manager import get_channel
from .config import config as default_config
from .pipeline import run_full_pipeline
from .production_quality_platform import record_production_event
from .production_readiness import run_production_health_check
from .production_safety_gate import ProductionSafetyGateBlocked, evaluate_production_safety_gate, _resolve_git_head
from .youtube_analytics_smoke import run_read_only_smoke


@dataclass(frozen=True, slots=True)
class SmokeCheck:
    name: str
    ok: bool
    message: str
    evidence: dict[str, Any]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    try:
        return asdict(value)
    except Exception:
        return dict(getattr(value, "__dict__", {}) or {})


def _build_runtime_health_config(cfg: Any) -> Any:
    base_dir = str(getattr(cfg, "base_dir", f"channels/{getattr(cfg, 'channel_id', '')}") or f"channels/{getattr(cfg, 'channel_id', '')}")
    return SimpleNamespace(
        output_dir=str(getattr(cfg, "output_dir", f"{base_dir}/output")),
        scripts_dir=str(getattr(cfg, "scripts_dir", f"{base_dir}/output/scripts")),
        audio_dir=str(getattr(cfg, "audio_dir", f"{base_dir}/output/audio")),
        videos_dir=str(getattr(cfg, "videos_dir", f"{base_dir}/output/videos")),
        assets_dir=str(getattr(cfg, "assets_dir", getattr(default_config, "assets_dir", "assets"))),
        logs_dir=str(getattr(cfg, "logs_dir", getattr(default_config, "logs_dir", "logs"))),
        anthropic_api_key=str(getattr(cfg, "anthropic_api_key", "")),
        youtube_client_id=str(getattr(cfg, "youtube_client_id", "")),
        youtube_client_secret=str(getattr(cfg, "youtube_client_secret", "")),
        niche=str(getattr(cfg, "niche", "")),
        channel_language=str(getattr(cfg, "channel_language", getattr(cfg, "language", ""))),
        timezone="UTC",
        ensure_directories=lambda: (default_config.ensure_directories(), cfg.ensure_directories()),
        validate=lambda: [
            key
            for key, value in {
                "ANTHROPIC_API_KEY": getattr(cfg, "anthropic_api_key", ""),
                "YOUTUBE_CLIENT_ID": getattr(cfg, "youtube_client_id", ""),
                "YOUTUBE_CLIENT_SECRET": getattr(cfg, "youtube_client_secret", ""),
            }.items()
            if not str(value or "").strip()
        ],
    )


def run_production_safety_smoke(*, channel_id: str, output_path: str | Path = Path("artifacts/local/production_safety_smoke.json")) -> dict[str, Any]:
    cfg = get_channel(channel_id)
    health_cfg = _build_runtime_health_config(cfg)
    checks: list[SmokeCheck] = []

    health = run_production_health_check(health_cfg, require_telegram=False, create_missing_directories=False)
    checks.append(SmokeCheck("environment", bool(health.ok), "Production readiness baseline.", {"errors": list(health.errors)}))

    startup_gate = evaluate_production_safety_gate(
        operation="scheduler_startup",
        startup_health=health,
        ready_channels=[channel_id],
        queue_path=Path(os.getenv("SCHEDULER_QUEUE_FILE", "output/state/channel_queue.json")),
        writable_paths=[health_cfg.output_dir, health_cfg.logs_dir],
        job_id="smoke_startup",
    )
    checks.append(SmokeCheck("startup_safety_gate", startup_gate.allowed, startup_gate.status, startup_gate.to_dict()))

    try:
        dry_run_result = run_full_pipeline(channel_cfg=cfg, privacy="private", dry_run=True)
    except ProductionSafetyGateBlocked as exc:
        dry_run_result = {
            "final_status": "blocked",
            "video_path": "",
            "upload_metadata": {},
            "upload_precheck": {},
            "performance_snapshot": {},
            "production_safety_gate": exc.gate_result.to_dict(),
        }
    checks.append(SmokeCheck("render_path_reachability", bool(dry_run_result.get("video_path")), "Dry-run pipeline render completed.", {"final_status": dry_run_result.get("final_status"), "upload_metadata": dry_run_result.get("upload_metadata", {})}))
    checks.append(SmokeCheck("upload_precheck", dry_run_result.get("upload_precheck", {}).get("status") != "blocked", "Upload precheck executed during dry-run.", dry_run_result.get("upload_precheck", {})))
    checks.append(SmokeCheck("channel_isolation", "channel_dna_mismatch" not in list(dry_run_result.get("upload_precheck", {}).get("guard_reason_codes") or []), "Channel isolation verified through upload precheck.", dry_run_result.get("upload_precheck", {})))

    snapshot = dict(dry_run_result.get("performance_snapshot") or {})
    analytics_guard = validate_performance_snapshot(snapshot, existing_rows=[])
    checks.append(SmokeCheck("analytics_snapshot_validation", analytics_guard.accepted, analytics_guard.message, _as_mapping(analytics_guard)))

    with TemporaryDirectory() as tmp:
        smoke_path = Path(tmp) / "analytics_smoke.json"
        analytics_smoke = run_read_only_smoke(
            channel_slugs=[channel_id],
            start_date=datetime.now(timezone.utc).date().isoformat(),
            end_date=datetime.now(timezone.utc).date().isoformat(),
            output_path=smoke_path,
        )
    analytics_ok = analytics_smoke.get("status") in {"PASS", "SKIPPED_NO_GO"}
    checks.append(SmokeCheck("analytics_read_only_smoke", analytics_ok, str(analytics_smoke.get("status") or "unknown"), analytics_smoke))

    duplicate_upload = bool((dry_run_result.get("upload_metadata") or {}).get("duplicate_prevented", False))
    checks.append(SmokeCheck("duplicate_upload_attempt", not duplicate_upload, "Dry-run must not trigger duplicate upload registration.", {"duplicate_prevented": duplicate_upload}))

    passed = all(item.ok for item in checks)
    report = {
        "generated_at": _now_iso(),
        "release_sha": _resolve_git_head(),
        "channel_id": channel_id,
        "decision": "PASS" if passed else "FAIL",
        "summary": f"{sum(1 for item in checks if item.ok)}/{len(checks)} checks passed",
        "checks": [asdict(item) for item in checks],
    }
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    record_production_event(
        {
            "event_type": "production_safety_smoke",
            "timestamp": report["generated_at"],
            "severity": "INFO" if passed else "ERROR",
            "status": report["decision"].lower(),
            "reason": "smoke_passed" if passed else "smoke_failed",
            "operation": "production_safety_smoke",
            "release_sha": report["release_sha"],
            "channel": channel_id,
            "channel_id": channel_id,
            "job_id": "smoke",
            "source_component": "production_safety_smoke",
            "evidence": {"output_path": str(output_path), "summary": report["summary"]},
        }
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Sprint 11 production safety smoke checks.")
    parser.add_argument("--channel", required=True)
    parser.add_argument("--output", default="artifacts/local/production_safety_smoke.json")
    args = parser.parse_args(argv)
    report = run_production_safety_smoke(channel_id=args.channel, output_path=args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("decision") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())