"""Lightweight thumbnail diversity history persistence (JSONL)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DEFAULT_HISTORY_PATH = Path("logs/thumbnail_history.jsonl")


def _parse_dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return datetime.now(timezone.utc)


def load_recent_thumbnail_history(
    *,
    history_path: Path | str = DEFAULT_HISTORY_PATH,
    lookback_days: int = 14,
    max_items: int = 500,
) -> list[dict[str, Any]]:
    path = Path(history_path)
    if not path.exists():
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, lookback_days))
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw:
                continue
            try:
                item = json.loads(raw)
            except Exception:
                continue
            created_at = _parse_dt(item.get("created_at"))
            if created_at >= cutoff:
                rows.append(item)
    except Exception:
        return []

    return rows[-max_items:]


def append_thumbnail_history(
    entry: dict[str, Any],
    *,
    history_path: Path | str = DEFAULT_HISTORY_PATH,
) -> None:
    path = Path(history_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = dict(entry)
    payload.setdefault("created_at", datetime.now(timezone.utc).isoformat())

    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
