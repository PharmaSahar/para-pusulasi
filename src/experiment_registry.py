"""Experiment registry core (Sprint 2.1A).

Provides an append-only JSONL registry with a minimal API to create experiments,
load/list current snapshots, and apply status transitions.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
import uuid


DEFAULT_REGISTRY_PATH = Path("output/telemetry/experiments.jsonl")
DEFAULT_SCHEMA_VERSION = "1.0"

EXPERIMENT_STATUSES = {
    "draft",
    "active",
    "completed",
    "rolled_back",
    "archived",
}

ALLOWED_WINNERS = {"control", "treatment", "inconclusive", "pending"}
ALLOWED_ROLLBACK_STATUS = {"none", "triggered", "completed"}

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"active"},
    "active": {"completed", "rolled_back"},
    "completed": {"archived"},
    "rolled_back": {"archived"},
}

REQUIRED_CREATE_FIELDS = (
    "hypothesis",
    "variant",
    "randomization_unit",
    "stratification",
    "start_date",
    "end_date",
    "kpi",
    "minimum_sample",
    "significance_method",
)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_experiment_id() -> str:
    """Generate a new UUID-based experiment identifier."""
    return uuid.uuid4().hex


def _normalize_status(status: str) -> str:
    lowered = str(status or "").strip().lower()
    if lowered not in EXPERIMENT_STATUSES:
        raise ValueError(f"Unsupported experiment status: {status}")
    return lowered


def _validate_winner(winner: str) -> str:
    value = str(winner or "").strip().lower()
    if value not in ALLOWED_WINNERS:
        raise ValueError(f"Unsupported winner value: {winner}")
    return value


def _validate_rollback_status(rollback_status: str) -> str:
    value = str(rollback_status or "").strip().lower()
    if value not in ALLOWED_ROLLBACK_STATUS:
        raise ValueError(f"Unsupported rollback status: {rollback_status}")
    return value


def can_transition(current_status: str, target_status: str) -> bool:
    current = _normalize_status(current_status)
    target = _normalize_status(target_status)
    return target in ALLOWED_TRANSITIONS.get(current, set())


def _append_event(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)


def load_experiment_events(*, registry_path: Path = DEFAULT_REGISTRY_PATH) -> list[dict[str, Any]]:
    """Load raw event lines from the append-only JSONL registry."""
    path = Path(registry_path)
    if not path.exists():
        return []

    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                events.append(parsed)
    return events


def list_experiments(*, registry_path: Path = DEFAULT_REGISTRY_PATH) -> list[dict[str, Any]]:
    """Return latest snapshot for each experiment id."""
    latest_by_id: dict[str, dict[str, Any]] = {}
    for event in load_experiment_events(registry_path=registry_path):
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        experiment_id = payload.get("experiment_id")
        if not experiment_id:
            continue
        latest_by_id[str(experiment_id)] = payload
    return list(latest_by_id.values())


def get_experiment(experiment_id: str, *, registry_path: Path = DEFAULT_REGISTRY_PATH) -> dict[str, Any] | None:
    for item in list_experiments(registry_path=registry_path):
        if item.get("experiment_id") == experiment_id:
            return item
    return None


def create_experiment(
    metadata: dict[str, Any],
    *,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    experiment_id: str | None = None,
    created_by: str = "pipeline",
    schema_version: str = DEFAULT_SCHEMA_VERSION,
    occurred_at: str | None = None,
) -> dict[str, Any]:
    """Create a draft experiment and append one event line."""
    missing = [field for field in REQUIRED_CREATE_FIELDS if field not in metadata]
    if missing:
        raise ValueError(f"Missing required experiment metadata fields: {', '.join(missing)}")

    resolved_experiment_id = str(experiment_id or build_experiment_id()).strip()
    if not resolved_experiment_id:
        raise ValueError("experiment_id must be non-empty")
    if get_experiment(resolved_experiment_id, registry_path=registry_path) is not None:
        raise ValueError(f"Experiment id already exists: {resolved_experiment_id}")

    creator = str(created_by or "").strip()
    if not creator:
        raise ValueError("created_by must be non-empty")

    version = str(schema_version or "").strip()
    if not version:
        raise ValueError("schema_version must be non-empty")

    payload = dict(metadata)
    payload["experiment_id"] = resolved_experiment_id
    payload["status"] = "draft"
    payload["winner"] = _validate_winner(str(payload.get("winner", "pending")))
    payload["rollback_status"] = _validate_rollback_status(str(payload.get("rollback_status", "none")))
    payload["schema_version"] = version
    payload["created_by"] = creator

    event = {
        "event_type": "experiment_created",
        "occurred_at": occurred_at or _utcnow_iso(),
        "experiment_id": resolved_experiment_id,
        "schema_version": version,
        "created_by": creator,
        "payload": payload,
    }
    _append_event(Path(registry_path), event)
    return payload


def update_experiment_status(
    experiment_id: str,
    target_status: str,
    *,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    winner: str | None = None,
    rollback_status: str | None = None,
    created_by: str = "pipeline",
    schema_version: str = DEFAULT_SCHEMA_VERSION,
    occurred_at: str | None = None,
) -> dict[str, Any]:
    """Apply a status transition by appending a new snapshot event."""
    current = get_experiment(experiment_id, registry_path=registry_path)
    if current is None:
        raise ValueError(f"Experiment not found: {experiment_id}")

    normalized_target = _normalize_status(target_status)
    current_status = _normalize_status(str(current.get("status", "")))
    if not can_transition(current_status, normalized_target):
        raise ValueError(f"Invalid experiment transition: {current_status} -> {normalized_target}")

    creator = str(created_by or "").strip()
    if not creator:
        raise ValueError("created_by must be non-empty")

    version = str(schema_version or "").strip()
    if not version:
        raise ValueError("schema_version must be non-empty")

    updated = dict(current)
    updated["status"] = normalized_target
    updated["created_by"] = creator
    updated["schema_version"] = version

    if winner is not None:
        if normalized_target != "completed":
            raise ValueError("winner can be set only when status is completed")
        winner_value = _validate_winner(winner)
        if winner_value == "pending":
            raise ValueError("winner cannot be pending when status is completed")
        updated["winner"] = winner_value
    elif normalized_target == "completed":
        winner_value = _validate_winner(str(updated.get("winner", "pending")))
        if winner_value == "pending":
            raise ValueError("winner must be finalized for completed experiments")
        updated["winner"] = winner_value

    if rollback_status is not None:
        rollback_value = _validate_rollback_status(rollback_status)
        if rollback_value in {"triggered", "completed"} and normalized_target not in {"rolled_back", "archived"}:
            raise ValueError("rollback_status triggered/completed requires rolled_back or archived status")
        if normalized_target == "archived" and rollback_value in {"triggered", "completed"} and current_status != "rolled_back":
            raise ValueError("archived rollback state requires previous status rolled_back")
        updated["rollback_status"] = rollback_value
    elif normalized_target == "rolled_back" and _validate_rollback_status(str(updated.get("rollback_status", "none"))) == "none":
        updated["rollback_status"] = "triggered"

    event = {
        "event_type": "experiment_status_updated",
        "occurred_at": occurred_at or _utcnow_iso(),
        "experiment_id": str(experiment_id),
        "schema_version": version,
        "created_by": creator,
        "payload": updated,
    }
    _append_event(Path(registry_path), event)
    return updated
