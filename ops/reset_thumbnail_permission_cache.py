#!/usr/bin/env python3
"""Reset per-channel thumbnail permission cache entries."""

from __future__ import annotations

import json
import sys
from pathlib import Path

CACHE_PATH = Path("logs/thumbnail_permission_cache.json")


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python ops/reset_thumbnail_permission_cache.py <channel_id|all>")
        return 1

    target = sys.argv[1].strip()
    if not CACHE_PATH.exists():
        print("No cache file found.")
        return 0

    payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    channels = dict(payload.get("channels") or {})

    if target == "all":
        channels = {}
    else:
        channels.pop(target, None)

    CACHE_PATH.write_text(json.dumps({"channels": channels}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Reset done: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
