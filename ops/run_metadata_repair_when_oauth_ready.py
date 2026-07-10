#!/usr/bin/env python3
"""Run metadata repair automatically for channels that become OAuth-ready."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "channels/channel_registry.json"
LOG_DIR = ROOT / "logs"
VALIDATION_DIR = ROOT / "output/local_validation"


def load_pending_channels() -> list[str]:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    channels = registry.get("channels", {})
    return [channel_id for channel_id, config in channels.items() if config.get("status") == "pending_oauth"]


def is_ready(channel_id: str) -> bool:
    base_dir = ROOT / "channels" / channel_id
    return (base_dir / "youtube_token.pickle").exists() and (base_dir / "client_secrets.json").exists()


def run_cmd(cmd: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True)
    return proc.returncode, proc.stdout, proc.stderr


def quota_like(text: str) -> bool:
    low = (text or "").lower()
    return any(token in low for token in ["quota", "429", "rate limit", "ratelimit", "quotaexceeded", "dailylimit", "resourceexhausted"])


def process_channel(channel_id: str, max_videos: int, apply_limit: int, min_tags: int, min_seo: int) -> dict[str, object]:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dry_report = LOG_DIR / f"metadata_repair_dryrun_{channel_id}_{stamp}.json"
    ids_file = VALIDATION_DIR / f"problematic_video_ids_{channel_id}_{stamp}.txt"
    apply_report = LOG_DIR / f"metadata_repair_apply_{channel_id}_{stamp}.json"
    verify_report = LOG_DIR / f"metadata_repair_verify_{channel_id}_{stamp}.json"

    dry_cmd = [
        sys.executable,
        "ops/metadata_repair.py",
        "--channel",
        channel_id,
        "--all-videos",
        "--max-videos",
        str(max_videos),
        "--only-problematic",
        "--min-tags",
        str(min_tags),
        "--min-seo",
        str(min_seo),
        "--problematic-ids-out",
        str(ids_file),
        "--report",
        str(dry_report),
    ]
    dry_code, dry_out, dry_err = run_cmd(dry_cmd)
    merged = (dry_out or "") + "\n" + (dry_err or "")

    result: dict[str, object] = {
        "channel": channel_id,
        "ready": True,
        "dry_report": str(dry_report.relative_to(ROOT)),
        "apply_report": None,
        "verify_report": None,
        "status": "dryrun_failed" if dry_code != 0 else "dryrun_clean",
        "quota_like_error": quota_like(merged),
        "stdout_tail": (dry_out or "")[-800:],
        "stderr_tail": (dry_err or "")[-800:],
    }

    if dry_code != 0:
        if result["quota_like_error"]:
            result["status"] = "quota_retry_needed"
        return result

    if not ids_file.exists() or ids_file.stat().st_size == 0:
        result["status"] = "clean_no_action_needed"
        return result

    apply_cmd = [
        sys.executable,
        "ops/metadata_repair.py",
        "--channel",
        channel_id,
        "--video-ids-file",
        str(ids_file),
        "--only-problematic",
        "--apply",
        "--apply-limit",
        str(apply_limit),
        "--min-tags",
        str(min_tags),
        "--min-seo",
        str(min_seo),
        "--report",
        str(apply_report),
    ]
    apply_code, apply_out, apply_err = run_cmd(apply_cmd)
    result["apply_report"] = str(apply_report.relative_to(ROOT))
    result["apply_stdout_tail"] = (apply_out or "")[-800:]
    result["apply_stderr_tail"] = (apply_err or "")[-800:]
    if apply_code != 0:
        result["status"] = "apply_failed"
        return result

    first_id = ids_file.read_text(encoding="utf-8").splitlines()[0].strip()
    verify_cmd = [
        sys.executable,
        "ops/metadata_repair.py",
        "--channel",
        channel_id,
        "--video-ids",
        first_id,
        "--only-problematic",
        "--min-tags",
        str(min_tags),
        "--min-seo",
        str(min_seo),
        "--report",
        str(verify_report),
    ]
    verify_code, verify_out, verify_err = run_cmd(verify_cmd)
    result["verify_report"] = str(verify_report.relative_to(ROOT))
    result["verify_stdout_tail"] = (verify_out or "")[-800:]
    result["verify_stderr_tail"] = (verify_err or "")[-800:]
    result["status"] = "repaired_and_verified" if verify_code == 0 else "verify_failed"
    return result


def write_watch_report(events: list[dict[str, object]]) -> Path:
    out = LOG_DIR / f"metadata_repair_oauth_ready_watch_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps({"generated_at": datetime.now().isoformat(), "events": events}, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Run metadata repair for channels that become OAuth-ready")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=900)
    parser.add_argument("--max-videos", type=int, default=20)
    parser.add_argument("--apply-limit", type=int, default=1)
    parser.add_argument("--min-tags", type=int, default=8)
    parser.add_argument("--min-seo", type=int, default=60)
    args = parser.parse_args()

    if not args.watch and not args.once:
        args.once = True

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)

    events: list[dict[str, object]] = []
    processed_channels: set[str] = set()

    while True:
        ready_channels = [channel_id for channel_id in load_pending_channels() if is_ready(channel_id) and channel_id not in processed_channels]

        for channel_id in ready_channels:
            event = process_channel(
                channel_id=channel_id,
                max_videos=args.max_videos,
                apply_limit=args.apply_limit,
                min_tags=args.min_tags,
                min_seo=args.min_seo,
            )
            processed_channels.add(channel_id)
            events.append(event)

        if args.once:
            break

        time.sleep(max(30, args.interval_seconds))

    report = write_watch_report(events)
    print(json.dumps({
        "report": str(report.relative_to(ROOT)),
        "ready_channels_processed": len(events),
        "channels": [event["channel"] for event in events],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
