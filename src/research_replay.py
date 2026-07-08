"""Passive replay engine for append-only research event files.

This module is read-only and one-shot friendly:
- Reads JSONL files line by line
- Fail-open on invalid JSON lines
- Supports source/schema_version/date filters
- Returns structured replay summary
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any, Iterator


def _to_iso_like(value: str) -> str:
    text = value.strip()
    if text.endswith("Z"):
        return text[:-1] + "+00:00"
    return text


def _is_in_range(value: str | None, *, lower: str | None, upper: str | None) -> bool:
    if value is None:
        return False
    try:
        observed_dt = datetime.fromisoformat(_to_iso_like(value))
    except ValueError:
        return False

    if lower:
        try:
            lower_dt = datetime.fromisoformat(_to_iso_like(lower))
        except ValueError:
            return False
        if observed_dt < lower_dt:
            return False

    if upper:
        try:
            upper_dt = datetime.fromisoformat(_to_iso_like(upper))
        except ValueError:
            return False
        if observed_dt > upper_dt:
            return False

    return True


def _iter_jsonl_files(root: Path) -> Iterator[Path]:
    if not root.exists():
        return iter(())
    return iter(sorted(root.rglob("*.jsonl")))


def _try_parse_iso_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(_to_iso_like(value))
    except ValueError:
        return None


def replay_research_events_once(
    *,
    research_root: Path | str,
    source: str | None = None,
    schema_version: int | None = None,
    observed_at_from: str | None = None,
    observed_at_to: str | None = None,
) -> dict[str, Any]:
    """Replay research events from append-only JSONL files with filters."""
    root = Path(research_root)

    total_events_read = 0
    total_events_emitted = 0
    skipped_invalid = 0
    by_source: dict[str, int] = {}
    files_scanned = 0
    files_with_events = 0
    first_observed_dt: datetime | None = None
    last_observed_dt: datetime | None = None

    source_filter = source.strip().lower() if isinstance(source, str) and source.strip() else None

    for path in _iter_jsonl_files(root):
        files_scanned += 1
        file_has_valid_event = False
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                text = line.strip()
                if not text:
                    continue

                total_events_read += 1
                try:
                    event = json.loads(text)
                except json.JSONDecodeError:
                    skipped_invalid += 1
                    continue

                file_has_valid_event = True

                payload = event.get("payload", {})
                event_source = payload.get("source") or event.get("source")
                event_schema_version = payload.get("schema_version")
                observed_at = payload.get("observed_at") or event.get("observed_at")

                if source_filter and str(event_source or "").strip().lower() != source_filter:
                    continue

                if schema_version is not None and event_schema_version != schema_version:
                    continue

                if observed_at_from is not None or observed_at_to is not None:
                    if not _is_in_range(observed_at, lower=observed_at_from, upper=observed_at_to):
                        continue

                total_events_emitted += 1
                source_key = str(event_source or "unknown")
                by_source[source_key] = by_source.get(source_key, 0) + 1

                observed_dt = _try_parse_iso_datetime(observed_at)
                if observed_dt is not None:
                    if first_observed_dt is None or observed_dt < first_observed_dt:
                        first_observed_dt = observed_dt
                    if last_observed_dt is None or observed_dt > last_observed_dt:
                        last_observed_dt = observed_dt

        if file_has_valid_event:
            files_with_events += 1

    return {
        "total_events_read": total_events_read,
        "total_events_emitted": total_events_emitted,
        "skipped_invalid": skipped_invalid,
        "by_source": by_source,
        "files_scanned": files_scanned,
        "files_with_events": files_with_events,
        "first_observed_at": first_observed_dt.isoformat() if first_observed_dt else None,
        "last_observed_at": last_observed_dt.isoformat() if last_observed_dt else None,
    }
