"""T2.3 binding layer between thumbnail candidates and experiment registry.

This module is strict by design (not fail-open): registry write/read failures are
raised explicitly so callers can decide retry/abort behavior.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Iterable

from .experiment_registry import DEFAULT_REGISTRY_PATH, DEFAULT_REGISTRY_VERSION
from .thumbnail_experiment import ThumbnailVariant, validate_thumbnail_variant, validate_unique_variant_ids


THUMBNAIL_BINDING_EVENT_TYPE = "thumbnail_variant_registered"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _required_text(field_name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing_required_field:{field_name}")
    return value.strip()


def _load_existing_bindings(registry_path: Path) -> set[tuple[str, str]]:
    if not registry_path.exists():
        return set()

    pairs: set[tuple[str, str]] = set()
    try:
        with registry_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                raw = line.strip()
                if not raw:
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                if event.get("event_type") != THUMBNAIL_BINDING_EVENT_TYPE:
                    continue
                experiment_id = str(event.get("experiment_id") or "").strip()
                variant_id = str(event.get("variant_id") or "").strip()
                if experiment_id and variant_id:
                    pairs.add((experiment_id, variant_id))
    except OSError as exc:
        raise RuntimeError(f"registry_unavailable:{registry_path}") from exc
    return pairs


def _append_event(registry_path: Path, event: dict) -> None:
    try:
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        with registry_path.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError as exc:
        raise RuntimeError(f"registry_unavailable:{registry_path}") from exc


def register_thumbnail_variant_bindings(
    *,
    experiment_id: str,
    candidates: Iterable[ThumbnailVariant],
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    created_by: str = "thumbnail_binding",
    registry_version: str = DEFAULT_REGISTRY_VERSION,
) -> list[dict]:
    """Append one binding event per candidate.

    Rules:
    - Duplicate variant_id for same experiment is rejected.
    - Candidate must be valid by ThumbnailVariant model contract.
    - Candidate must include content_id or video_id.
    - Registry failures are raised explicitly.
    """
    expected_experiment_id = _required_text("experiment_id", experiment_id)
    creator = _required_text("created_by", created_by)
    resolved_registry_version = _required_text("registry_version", registry_version)

    candidate_list = list(candidates)
    validate_unique_variant_ids(candidate_list)

    existing_pairs = _load_existing_bindings(Path(registry_path))

    events: list[dict] = []
    for candidate in candidate_list:
        validate_thumbnail_variant(candidate)

        if candidate.experiment_id != expected_experiment_id:
            raise ValueError("candidate_experiment_id_mismatch")

        if not ((candidate.content_id and candidate.content_id.strip()) or (candidate.video_id and candidate.video_id.strip())):
            raise ValueError("missing_required_field:content_id_or_video_id")

        pair = (candidate.experiment_id, candidate.variant_id)
        if pair in existing_pairs:
            raise ValueError(f"duplicate_binding_exists:{candidate.experiment_id}:{candidate.variant_id}")

        event = {
            "event_type": THUMBNAIL_BINDING_EVENT_TYPE,
            "experiment_id": candidate.experiment_id,
            "variant_id": candidate.variant_id,
            "variant_label": candidate.variant_label,
            "channel_id": candidate.channel_id,
            "content_id": candidate.content_id,
            "video_id": candidate.video_id,
            "thumbnail_path": candidate.thumbnail_path,
            "strategy": candidate.strategy,
            "created_at": candidate.created_at,
            "schema_version": candidate.schema_version,
            "registry_version": resolved_registry_version,
            "occurred_at": _utcnow_iso(),
            "created_by": creator,
        }

        _append_event(Path(registry_path), event)
        events.append(event)
        existing_pairs.add(pair)

    return events
