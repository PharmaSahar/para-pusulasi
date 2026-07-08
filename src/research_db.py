"""Append-only event store for Research Foundation v0.

Storage layout:
research/
  raw/YYYY-MM-DD.jsonl
  normalized/opportunities.jsonl
  schema/opportunity_v1.json
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .opportunity_normalizer import OPPORTUNITY_SCHEMA_VERSION


DEFAULT_RESEARCH_ROOT = Path("research")


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _day_key(now_utc: datetime | None = None) -> str:
    now = now_utc or datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%d")


def raw_day_path(*, root: Path = DEFAULT_RESEARCH_ROOT, now_utc: datetime | None = None) -> Path:
    return Path(root) / "raw" / f"{_day_key(now_utc)}.jsonl"


def normalized_path(*, root: Path = DEFAULT_RESEARCH_ROOT) -> Path:
    return Path(root) / "normalized" / "opportunities.jsonl"


def schema_path(*, root: Path = DEFAULT_RESEARCH_ROOT) -> Path:
    return Path(root) / "schema" / f"{OPPORTUNITY_SCHEMA_VERSION}.json"


def ensure_layout(*, root: Path = DEFAULT_RESEARCH_ROOT) -> None:
    root = Path(root)
    (root / "raw").mkdir(parents=True, exist_ok=True)
    (root / "normalized").mkdir(parents=True, exist_ok=True)
    (root / "schema").mkdir(parents=True, exist_ok=True)

    schema_file = schema_path(root=root)
    if not schema_file.exists():
        schema = {
            "schema_version": OPPORTUNITY_SCHEMA_VERSION,
            "type": "object",
            "required": [
                "opportunity_id",
                "topic",
                "category",
                "country",
                "language",
                "source",
                "first_seen",
                "last_seen",
            ],
            "properties": {
                "opportunity_id": {"type": "string"},
                "schema_version": {"type": "string"},
                "topic": {"type": "string"},
                "category": {"type": "string"},
                "country": {"type": "string"},
                "language": {"type": "string"},
                "source": {"type": "string"},
                "first_seen": {"type": "string"},
                "last_seen": {"type": "string"},
                "search_volume": {},
                "competition": {},
                "confidence": {},
                "raw_context": {"type": "object"},
            },
        }
        schema_file.write_text(json.dumps(schema, ensure_ascii=True, sort_keys=True, separators=(",", ":")), encoding="utf-8")


def append_jsonl(path: Path, payload: dict[str, Any]) -> bool:
    """Append one JSON event line. Fail-open by returning False."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)
        return True
    except Exception:
        return False


def append_raw_observation(raw_observation: dict[str, Any], *, root: Path = DEFAULT_RESEARCH_ROOT, observed_at_utc: str | None = None) -> bool:
    ensure_layout(root=root)
    event = {
        "event_type": "raw_observation",
        "schema_version": "raw_v1",
        "observed_at": observed_at_utc or _iso_utc_now(),
        "payload": raw_observation,
    }
    return append_jsonl(raw_day_path(root=root), event)


def load_latest_opportunities(*, root: Path = DEFAULT_RESEARCH_ROOT) -> dict[str, dict[str, Any]]:
    """Read the append-only stream and return latest state by opportunity_id."""
    path = normalized_path(root=root)
    if not path.exists():
        return {}

    latest: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = event.get("payload", {})
            opp_id = payload.get("opportunity_id")
            if opp_id:
                latest[opp_id] = payload
    return latest


def append_or_update_opportunity(opportunity: dict[str, Any], *, root: Path = DEFAULT_RESEARCH_ROOT, observed_at_utc: str | None = None) -> dict[str, Any]:
    """Append a normalized opportunity event while preserving first_seen.

    Returns the merged latest snapshot that was appended.
    """
    ensure_layout(root=root)
    observed_at = observed_at_utc or _iso_utc_now()
    opp_id = opportunity["opportunity_id"]

    latest = load_latest_opportunities(root=root).get(opp_id)
    merged = dict(opportunity)
    if latest:
        merged["first_seen"] = latest.get("first_seen", opportunity.get("first_seen", observed_at))
    else:
        merged["first_seen"] = opportunity.get("first_seen", observed_at)
    merged["last_seen"] = observed_at

    event = {
        "event_type": "opportunity_upsert",
        "schema_version": OPPORTUNITY_SCHEMA_VERSION,
        "observed_at": observed_at,
        "payload": merged,
    }
    append_jsonl(normalized_path(root=root), event)
    return merged
