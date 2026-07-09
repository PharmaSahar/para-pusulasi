#!/usr/bin/env python3
"""Audit channel upload tokens for required YouTube upload scopes."""

from __future__ import annotations

import json
import pickle
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.channel_manager import get_channel, list_channels
from src.youtube_auth import UPLOAD_SCOPES


def _safe_scopes(token_path: Path) -> list[str]:
    try:
        with token_path.open("rb") as fh:
            creds = pickle.load(fh)
        scopes = list(getattr(creds, "scopes", []) or [])
        return [str(s) for s in scopes]
    except Exception:
        return []


def main() -> int:
    required = set(UPLOAD_SCOPES)
    rows: list[dict] = []

    for channel_id in list_channels():
        cfg = get_channel(channel_id)
        token_path = Path(cfg.token_path)
        if not token_path.exists():
            rows.append(
                {
                    "channel_id": channel_id,
                    "token_path": str(token_path),
                    "token_exists": False,
                    "has_required_upload_scopes": False,
                    "missing_scopes": sorted(required),
                }
            )
            continue

        scopes = set(_safe_scopes(token_path))
        missing = sorted(required - scopes)
        rows.append(
            {
                "channel_id": channel_id,
                "token_path": str(token_path),
                "token_exists": True,
                "has_required_upload_scopes": len(missing) == 0,
                "missing_scopes": missing,
            }
        )

    fail_count = sum(1 for r in rows if not r["has_required_upload_scopes"])
    result = {
        "required_upload_scopes": sorted(required),
        "channels_checked": len(rows),
        "channels_missing_required_scopes": fail_count,
        "rows": rows,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
