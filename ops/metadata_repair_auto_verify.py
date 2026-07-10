#!/usr/bin/env python3
"""Wait for quota/rate-limit recovery, then run repair verification and report.

The script repeatedly runs metadata repair in dry-run mode over targeted ids.
When API transient quota errors disappear, it produces a verification report.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run_command(cmd: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True)
    return proc.returncode, proc.stdout, proc.stderr


def _is_quota_like(text: str) -> bool:
    low = (text or "").lower()
    keys = [
        "quota",
        "ratelimit",
        "rate limit",
        "429",
        "quotaexceeded",
        "dailylimit",
        "resourceexhausted",
    ]
    return any(k in low for k in keys)


def _build_repair_cmd(args, report_path: Path) -> list[str]:
    cmd = [
        sys.executable,
        "ops/metadata_repair.py",
        "--channel",
        args.channel,
        "--video-ids-file",
        args.video_ids_file,
        "--only-problematic",
        "--min-tags",
        str(args.min_tags),
        "--min-seo",
        str(args.min_seo),
        "--report",
        str(report_path),
    ]
    if args.apply:
        cmd.extend(["--apply", "--apply-limit", str(args.apply_limit)])
    return cmd


def main() -> int:
    parser = argparse.ArgumentParser(description="Auto-run metadata verification when quota recovers")
    parser.add_argument("--channel", required=True)
    parser.add_argument("--video-ids-file", required=True)
    parser.add_argument("--interval-seconds", type=int, default=600)
    parser.add_argument("--max-attempts", type=int, default=24)
    parser.add_argument("--min-tags", type=int, default=8)
    parser.add_argument("--min-seo", type=int, default=60)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--apply-limit", type=int, default=3)
    parser.add_argument("--report-dir", default="logs")
    args = parser.parse_args()

    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)

    watch_report = {
        "started_at": datetime.now().isoformat(),
        "channel": args.channel,
        "video_ids_file": args.video_ids_file,
        "attempts": [],
        "status": "watching",
        "final_report": None,
    }

    for attempt in range(1, args.max_attempts + 1):
        attempt_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_report = report_dir / f"metadata_repair_verify_{attempt_stamp}.json"
        cmd = _build_repair_cmd(args=args, report_path=run_report)

        code, out, err = _run_command(cmd)
        merged = (out or "") + "\n" + (err or "")

        event = {
            "attempt": attempt,
            "time": datetime.now().isoformat(),
            "exit_code": code,
            "report": str(run_report),
            "quota_like_error": _is_quota_like(merged),
            "stdout_tail": (out or "")[-1200:],
            "stderr_tail": (err or "")[-1200:],
        }
        watch_report["attempts"].append(event)

        if code == 0:
            watch_report["status"] = "completed"
            watch_report["final_report"] = str(run_report)
            break

        if not event["quota_like_error"]:
            watch_report["status"] = "failed_non_quota"
            watch_report["final_report"] = str(run_report)
            break

        if attempt < args.max_attempts:
            time.sleep(max(30, args.interval_seconds))
        else:
            watch_report["status"] = "timed_out"

    watch_path = report_dir / f"metadata_repair_watch_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    watch_path.write_text(json.dumps(watch_report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"watch_report": str(watch_path), "status": watch_report["status"], "final_report": watch_report["final_report"]}, ensure_ascii=False, indent=2))

    return 0 if watch_report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
