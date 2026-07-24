from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .analytics_snapshot_foundation import (
    AnalyticsSnapshotStore,
    AnalyticsSnapshotStoreError,
    AnalyticsSnapshotValidationError,
    canonicalize_snapshot_payload,
)

SUPPORTED_EXTENSIONS = {".json"}
MAX_FIXTURE_RECORDS = 1000
SUPPORTED_ROOT_TYPES = (dict, list)
ALLOWED_FIELDS = {
    "schema_version",
    "snapshot_timestamp",
    "channel_id",
    "youtube_channel_id",
    "internal_video_id",
    "youtube_video_id",
    "content_job_id",
    "content_type",
    "metric_source",
    "provenance_reference",
    "title_at_snapshot",
    "topic",
    "topic_domain",
    "language",
    "duration_seconds",
    "publication_timestamp",
    "thumbnail_identity",
    "prompt_template_version",
    "impressions",
    "impressions_ctr",
    "views",
    "watch_time_minutes",
    "average_view_duration_seconds",
    "average_percentage_viewed",
    "subscribers_gained",
    "subscribers_lost",
    "likes",
    "comments",
    "shares",
    "fetched_at",
    "freshness_status",
    "completeness_status",
    "missing_fields",
    "partial_data_reason",
    "validation_status",
    "source_query_version",
}


class FixtureIngestionError(RuntimeError):
    """Raised when fixture ingestion cannot be completed safely."""


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _normalize_record(raw_record: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw_record, dict):
        raise FixtureIngestionError("fixture records must be objects")

    unknown_fields = sorted(set(raw_record) - ALLOWED_FIELDS)
    if unknown_fields:
        raise FixtureIngestionError(f"unknown fields: {', '.join(unknown_fields)}")

    normalized = {}
    for field in sorted(ALLOWED_FIELDS):
        if field in raw_record:
            value = raw_record[field]
            if field in {"schema_version", "channel_id", "youtube_channel_id", "internal_video_id", "youtube_video_id", "content_job_id", "metric_source", "provenance_reference", "content_type", "title_at_snapshot", "topic", "topic_domain", "language", "freshness_status", "completeness_status", "partial_data_reason", "validation_status", "source_query_version"}:
                if isinstance(value, str):
                    normalized[field] = value.strip()
                else:
                    normalized[field] = value
            elif field in {"missing_fields"}:
                if value is None:
                    normalized[field] = []
                elif isinstance(value, list):
                    normalized[field] = [str(item).strip() for item in value if str(item).strip()]
                else:
                    raise FixtureIngestionError("missing_fields must be a list")
            elif field in {"duration_seconds", "impressions", "views", "watch_time_minutes", "subscribers_gained", "subscribers_lost", "likes", "comments", "shares"}:
                if value is None:
                    normalized[field] = None
                elif isinstance(value, bool):
                    raise FixtureIngestionError(f"{field} must not be boolean")
                elif isinstance(value, (int, float)):
                    normalized[field] = int(value) if isinstance(value, int) else float(value)
                else:
                    raise FixtureIngestionError(f"{field} must be numeric or null")
            elif field in {"impressions_ctr", "average_view_duration_seconds", "average_percentage_viewed"}:
                if value is None:
                    normalized[field] = None
                elif isinstance(value, bool):
                    raise FixtureIngestionError(f"{field} must not be boolean")
                elif isinstance(value, (int, float)):
                    normalized[field] = float(value)
                else:
                    raise FixtureIngestionError(f"{field} must be numeric or null")
            else:
                normalized[field] = value

    if not str(normalized.get("schema_version") or "").strip():
        raise FixtureIngestionError("schema_version is required")
    if str(normalized.get("channel_id") or "").strip() == "":
        raise FixtureIngestionError("channel_id is required")
    if str(normalized.get("youtube_channel_id") or "").strip() == "":
        raise FixtureIngestionError("youtube_channel_id is required")
    if str(normalized.get("internal_video_id") or "").strip() == "":
        raise FixtureIngestionError("internal_video_id is required")
    if str(normalized.get("youtube_video_id") or "").strip() == "":
        raise FixtureIngestionError("youtube_video_id is required")
    if str(normalized.get("content_job_id") or "").strip() == "":
        raise FixtureIngestionError("content_job_id is required")
    if str(normalized.get("metric_source") or "").strip() == "":
        raise FixtureIngestionError("metric_source is required")
    if str(normalized.get("provenance_reference") or "").strip() == "":
        raise FixtureIngestionError("provenance_reference is required")

    if str(normalized.get("snapshot_timestamp") or "").strip() == "":
        raise FixtureIngestionError("snapshot_timestamp is required")
    try:
        import datetime as dt
        parsed = dt.datetime.fromisoformat(str(normalized["snapshot_timestamp"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise FixtureIngestionError("snapshot_timestamp must be timezone-aware") from exc
    if parsed.tzinfo is None:
        raise FixtureIngestionError("snapshot_timestamp must be timezone-aware")
    normalized["snapshot_timestamp"] = parsed.astimezone(dt.timezone.utc).isoformat()

    return normalized


def build_fixture_identity(fixture_path: str | os.PathLike[str] | Path) -> str:
    path = Path(fixture_path)
    if not path.exists():
        raise FixtureIngestionError("fixture file is missing")
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise FixtureIngestionError("unsupported fixture extension")
    raw_bytes = path.read_bytes()
    return hashlib.sha256(raw_bytes).hexdigest()


def load_fixture_records(fixture_path: str | os.PathLike[str] | Path) -> list[dict[str, Any]]:
    path = Path(fixture_path)
    if not path.exists():
        raise FixtureIngestionError("fixture file is missing")
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise FixtureIngestionError("unsupported fixture extension")

    try:
        raw_payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FixtureIngestionError("invalid JSON fixture") from exc

    if isinstance(raw_payload, dict):
        raw_payload = [raw_payload]
    elif not isinstance(raw_payload, list):
        raise FixtureIngestionError("fixture root must be a list or object")
    if not raw_payload:
        raise FixtureIngestionError("fixture is empty")
    if len(raw_payload) > MAX_FIXTURE_RECORDS:
        raise FixtureIngestionError("fixture exceeds maximum record count")

    normalized_records: list[dict[str, Any]] = []
    for raw_record in raw_payload:
        normalized_records.append(_normalize_record(raw_record))
    return normalized_records


def ingest_fixture(
    fixture_path: str | os.PathLike[str] | Path,
    store_root: str | os.PathLike[str] | Path,
    *,
    expected_channel_id: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    fixture_path = Path(fixture_path)
    store_root = Path(store_root)
    if not fixture_path.exists():
        raise FixtureIngestionError("fixture file is missing")
    if fixture_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise FixtureIngestionError("unsupported fixture extension")

    records = load_fixture_records(fixture_path)
    fixture_identity = build_fixture_identity(fixture_path)
    channel_ids_seen: set[str] = set()
    snapshot_ids: list[str] = []
    error_categories: list[str] = []
    schema_versions_seen: set[str] = set()
    duplicate_count = 0

    if expected_channel_id is not None:
        expected_channel_id = str(expected_channel_id).strip()
        if not expected_channel_id:
            raise FixtureIngestionError("expected_channel_id must not be empty")

    for record in records:
        channel_id = str(record.get("channel_id") or "").strip()
        channel_ids_seen.add(channel_id)
        schema_versions_seen.add(str(record.get("schema_version") or ""))

        if expected_channel_id is not None and channel_id != expected_channel_id:
            raise FixtureIngestionError("expected channel mismatch")

        youtube_channel_id = str(record.get("youtube_channel_id") or "").strip()
        if not youtube_channel_id:
            raise FixtureIngestionError("youtube_channel_id is required")
        if not youtube_channel_id.startswith("UC"):
            raise FixtureIngestionError("youtube_channel_id is inconsistent")
        expected_youtube_channel_id = f"UC-{channel_id.split('_')[-1]}"
        if youtube_channel_id != expected_youtube_channel_id:
            raise FixtureIngestionError("youtube channel mismatch")

        if len(channel_ids_seen) > 1:
            raise FixtureIngestionError("mixed-channel fixture")

        try:
            canonical_record = canonicalize_snapshot_payload(record)
        except AnalyticsSnapshotValidationError as exc:
            error_categories.append(type(exc).__name__)
            raise FixtureIngestionError(str(exc)) from exc

        if dry_run:
            snapshot_ids.append(canonical_record["snapshot_id"])
            continue

        store = AnalyticsSnapshotStore(store_root, channel_id=channel_id)
        try:
            append_result = store.append_snapshot(canonical_record)
        except AnalyticsSnapshotStoreError as exc:
            raise FixtureIngestionError(str(exc)) from exc
        if append_result["status"] == "appended":
            snapshot_ids.append(append_result["snapshot_id"])
        elif append_result["status"] == "duplicate":
            duplicate_count += 1
            snapshot_ids.append(append_result["snapshot_id"])
        else:
            raise FixtureIngestionError("unexpected append result")

    if dry_run:
        return {
            "input_record_count": len(records),
            "valid_record_count": len(records),
            "appended_count": 0,
            "duplicate_count": duplicate_count,
            "rejected_count": 0,
            "channel_ids_seen": sorted(channel_ids_seen),
            "snapshot_ids": snapshot_ids,
            "error_categories": error_categories,
            "dry_run": True,
            "fixture_identity": fixture_identity,
            "schema_versions_seen": sorted(schema_versions_seen),
        }

    return {
        "input_record_count": len(records),
        "valid_record_count": len(records),
        "appended_count": len(snapshot_ids) - duplicate_count,
        "duplicate_count": duplicate_count,
        "rejected_count": 0,
        "channel_ids_seen": sorted(channel_ids_seen),
        "snapshot_ids": snapshot_ids,
        "error_categories": error_categories,
        "dry_run": False,
        "fixture_identity": fixture_identity,
        "schema_versions_seen": sorted(schema_versions_seen),
    }
