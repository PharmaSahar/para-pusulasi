#!/usr/bin/env python3
"""Audit thumbnail permission health from scheduler logs."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOG_FILE = ROOT / "logs" / "production_scheduler.out"


def _extract_channel_from_telemetry(line: str) -> str | None:
    # telemetry_event={... "channel_id": "..." ...}
    m = re.search(r'"channel_id"\s*:\s*"([^"]+)"', line)
    if not m:
        return None
    return m.group(1)


def main() -> int:
    if not LOG_FILE.exists():
        print(json.dumps({"ok": False, "reason": "missing_log", "log": str(LOG_FILE)}, ensure_ascii=False, indent=2))
        return 1

    current_channel = "unknown"
    uploads = 0
    thumbnail_forbidden = 0
    by_channel_forbidden = Counter()
    forbidden_samples: list[str] = []

    for line in LOG_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
        ch = _extract_channel_from_telemetry(line)
        if ch:
            current_channel = ch

        if "Video yuklendi: https://youtube.com/watch?v=" in line:
            uploads += 1

        if "Thumbnail yükleme izni yok (403)" in line:
            thumbnail_forbidden += 1
            by_channel_forbidden[current_channel] += 1
            if len(forbidden_samples) < 10:
                forbidden_samples.append(line)

    ratio = (thumbnail_forbidden / uploads * 100.0) if uploads else 0.0
    result = {
        "ok": True,
        "log": str(LOG_FILE),
        "video_upload_count": uploads,
        "thumbnail_403_count": thumbnail_forbidden,
        "thumbnail_403_ratio_percent": round(ratio, 2),
        "thresholds": {
            "target_ratio_percent": 0.0,
            "alert_if_ratio_percent_gt": 0.0,
        },
        "forbidden_by_channel": dict(by_channel_forbidden),
        "sample_lines": forbidden_samples,
    }

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
