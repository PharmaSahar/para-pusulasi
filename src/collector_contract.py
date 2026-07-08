"""Shared raw observation contract for research collectors."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def _is_iso_like(value: str) -> bool:
    # Accept common ISO-8601 variants including trailing Z.
    candidate = value.strip()
    if not candidate:
        return False
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        datetime.fromisoformat(candidate)
        return True
    except ValueError:
        return False


def validate_raw_observation(observation: dict[str, Any]) -> list[str]:
    """Return validation errors for collector raw observation payload."""
    errors: list[str] = []

    for field in ("source", "observed_at", "raw"):
        if field not in observation:
            errors.append(f"missing_required_field:{field}")

    source = observation.get("source")
    if "source" in observation and (not isinstance(source, str) or not source.strip()):
        errors.append("invalid_source")

    observed_at = observation.get("observed_at")
    if "observed_at" in observation and (not isinstance(observed_at, str) or not _is_iso_like(observed_at)):
        errors.append("invalid_observed_at")

    raw = observation.get("raw")
    if "raw" in observation and not isinstance(raw, dict):
        errors.append("invalid_raw")

    return errors


def is_valid_raw_observation(observation: dict[str, Any]) -> bool:
    return len(validate_raw_observation(observation)) == 0
