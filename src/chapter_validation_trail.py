"""Structured chapter validate/auto-fix/revalidate trail artifacts (JSONL)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DEFAULT_CHAPTER_VALIDATION_TRAIL_PATH = Path("logs/chapter_validation_trail.jsonl")
DEFAULT_CHAPTER_VALIDATOR_LATEST_PATH = Path("logs/chapter_validator_latest.json")


def _parse_dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return datetime.now(timezone.utc)


def append_chapter_validation_event(
    entry: dict[str, Any],
    *,
    trail_path: Path | str = DEFAULT_CHAPTER_VALIDATION_TRAIL_PATH,
) -> None:
    """Persist a single chapter validation trail event in fail-open mode."""
    path = Path(trail_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(entry)
        payload.setdefault("created_at", datetime.now(timezone.utc).isoformat())

        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception:
        return


def write_latest_chapter_validator_artifact(
    *,
    channel_id: str,
    title: str,
    duration_seconds: int,
    chapter_result: dict[str, Any],
    input_description: str,
    latest_path: Path | str = DEFAULT_CHAPTER_VALIDATOR_LATEST_PATH,
) -> None:
    """Persist latest validator artifact snapshot in fail-open mode."""
    path = Path(latest_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "artifact_type": "chapter_validator_latest",
            "schema_version": str(chapter_result.get("schema_version", "unknown")),
            "validator_version": str(chapter_result.get("validator_version", "unknown")),
            "channel": str(channel_id or ""),
            "title": str(title or "")[:180],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "duration": int(max(0, int(duration_seconds or 0))),
            "input_hash": hashlib.sha256(str(input_description or "").encode("utf-8")).hexdigest(),
            "valid_before": bool(chapter_result.get("valid_before", False)),
            "valid_after": bool(chapter_result.get("valid_after", False)),
            "issues": list(chapter_result.get("issue_codes", [])),
            "issue_labels": list(chapter_result.get("issue_labels", [])),
            "actions": list(chapter_result.get("auto_fix_actions", [])),
            "fix_counts": dict(chapter_result.get("fix_counts", {})),
            "chapter_contract_pass": bool(chapter_result.get("chapter_contract_pass", False)),
            "bypass_reason": chapter_result.get("bypass_reason"),
            "input_chapter_count": int(chapter_result.get("input_chapter_count", 0)),
            "chapter_count": int(chapter_result.get("chapter_count", 0)),
        }

        path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    except Exception:
        return


def load_recent_chapter_validation_events(
    *,
    trail_path: Path | str = DEFAULT_CHAPTER_VALIDATION_TRAIL_PATH,
    lookback_days: int = 14,
    max_items: int = 5000,
) -> list[dict[str, Any]]:
    path = Path(trail_path)
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
            if not isinstance(item, dict):
                continue
            created_at = _parse_dt(item.get("created_at"))
            if created_at >= cutoff:
                rows.append(item)
    except Exception:
        return []

    return rows[-max_items:]
