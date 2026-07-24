from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SUPPORTED_SCHEMA_VERSIONS = {"1.0"}
SUPPORTED_CONTENT_TYPES = {"SHORT", "LONG_FORM"}


class AnalyticsSnapshotValidationError(ValueError):
    """Raised when a snapshot payload is invalid."""


class AnalyticsSnapshotStoreError(RuntimeError):
    """Raised when the append-only store cannot safely process a snapshot."""


@dataclass(frozen=True, slots=True)
class AnalyticsSnapshotRecord:
    schema_version: str
    snapshot_id: str
    snapshot_timestamp: str
    snapshot_date: str
    channel_id: str
    youtube_channel_id: str
    internal_video_id: str
    youtube_video_id: str
    content_job_id: str
    content_type: str
    metric_source: str
    provenance_reference: str
    title_at_snapshot: str | None
    topic: str | None
    topic_domain: str | None
    language: str | None
    duration_seconds: int | None
    publication_timestamp: str | None
    thumbnail_identity: str | None
    prompt_template_version: str | None
    impressions: int | None
    views: int | None
    watch_time_minutes: int | None
    subscribers_gained: int | None
    subscribers_lost: int | None
    likes: int | None
    comments: int | None
    shares: int | None
    impressions_ctr: float | None
    average_view_duration_seconds: float | None
    average_percentage_viewed: float | None
    fetched_at: str | None
    freshness_status: str | None
    completeness_status: str | None
    missing_fields: list[str]
    partial_data_reason: str | None
    validation_status: str | None
    source_query_version: str | None

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "snapshot_timestamp": self.snapshot_timestamp,
            "snapshot_date": self.snapshot_date,
            "channel_id": self.channel_id,
            "youtube_channel_id": self.youtube_channel_id,
            "internal_video_id": self.internal_video_id,
            "youtube_video_id": self.youtube_video_id,
            "content_job_id": self.content_job_id,
            "content_type": self.content_type,
            "metric_source": self.metric_source,
            "provenance_reference": self.provenance_reference,
            "title_at_snapshot": self.title_at_snapshot,
            "topic": self.topic,
            "topic_domain": self.topic_domain,
            "language": self.language,
            "duration_seconds": self.duration_seconds,
            "publication_timestamp": self.publication_timestamp,
            "thumbnail_identity": self.thumbnail_identity,
            "prompt_template_version": self.prompt_template_version,
            "impressions": self.impressions,
            "views": self.views,
            "watch_time_minutes": self.watch_time_minutes,
            "subscribers_gained": self.subscribers_gained,
            "subscribers_lost": self.subscribers_lost,
            "likes": self.likes,
            "comments": self.comments,
            "shares": self.shares,
            "impressions_ctr": self.impressions_ctr,
            "average_view_duration_seconds": self.average_view_duration_seconds,
            "average_percentage_viewed": self.average_percentage_viewed,
            "fetched_at": self.fetched_at,
            "freshness_status": self.freshness_status,
            "completeness_status": self.completeness_status,
            "missing_fields": list(self.missing_fields),
            "partial_data_reason": self.partial_data_reason,
            "validation_status": self.validation_status,
            "source_query_version": self.source_query_version,
        }


def _parse_timestamp(value: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise AnalyticsSnapshotValidationError("snapshot_timestamp is required")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AnalyticsSnapshotValidationError("snapshot_timestamp must be a valid ISO 8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise AnalyticsSnapshotValidationError("snapshot_timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _stable_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_snapshot_id(payload: dict[str, Any]) -> str:
    """Create a deterministic snapshot id from canonical identity fields.

    The function uses a stable serialization of the schema version, channel id,
    YouTube video id, normalized timestamp, and metric source. Title and
    thumbnail changes do not affect the identity because they are not part of
    the canonical identity material. Null and zero are encoded distinctly so
    they produce different identities when they are semantically different.
    """

    identity_payload = {
        "schema_version": str(payload.get("schema_version") or ""),
        "channel_id": str(payload.get("channel_id") or ""),
        "youtube_video_id": str(payload.get("youtube_video_id") or ""),
        "snapshot_timestamp": _parse_timestamp(str(payload.get("snapshot_timestamp") or "")).isoformat(),
        "metric_source": str(payload.get("metric_source") or ""),
    }
    for field in (
        "impressions",
        "views",
        "watch_time_minutes",
        "subscribers_gained",
        "subscribers_lost",
        "likes",
        "comments",
        "shares",
        "impressions_ctr",
        "average_view_duration_seconds",
        "average_percentage_viewed",
    ):
        value = payload.get(field)
        if value is None:
            identity_payload[f"{field}:null"] = "null"
        else:
            identity_payload[f"{field}:value"] = value
    return hashlib.sha256(_stable_json(identity_payload).encode("utf-8")).hexdigest()


def canonicalize_snapshot_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise AnalyticsSnapshotValidationError("snapshot payload must be a mapping")

    version = str(payload.get("schema_version") or "").strip()
    if not version:
        raise AnalyticsSnapshotValidationError("schema_version is required")
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise AnalyticsSnapshotValidationError("unsupported schema_version")

    required_identity = [
        "channel_id",
        "youtube_channel_id",
        "internal_video_id",
        "youtube_video_id",
        "content_job_id",
        "metric_source",
        "provenance_reference",
    ]
    missing_identity = [field for field in required_identity if not str(payload.get(field) or "").strip()]
    if missing_identity:
        raise AnalyticsSnapshotValidationError(f"missing required identity fields: {', '.join(missing_identity)}")

    content_type = str(payload.get("content_type") or "").strip().upper()
    if content_type not in SUPPORTED_CONTENT_TYPES:
        raise AnalyticsSnapshotValidationError("content_type must be SHORT or LONG_FORM")

    snapshot_timestamp = str(payload.get("snapshot_timestamp") or "").strip()
    parsed_timestamp = _parse_timestamp(snapshot_timestamp)
    snapshot_date = parsed_timestamp.strftime("%Y-%m-%d")

    for field_name in ("impressions", "views", "watch_time_minutes", "subscribers_gained", "subscribers_lost", "likes", "comments", "shares"):
        value = payload.get(field_name)
        if value is None:
            continue
        if isinstance(value, (int, float)) and value < 0:
            raise AnalyticsSnapshotValidationError(f"{field_name} must not be negative")

    duration = payload.get("duration_seconds")
    if duration is not None:
        if isinstance(duration, (int, float)) and duration < 0:
            raise AnalyticsSnapshotValidationError("duration_seconds must not be negative")

    ctr = payload.get("impressions_ctr")
    if ctr is not None:
        try:
            ctr_value = float(ctr)
        except (TypeError, ValueError) as exc:
            raise AnalyticsSnapshotValidationError("impressions_ctr must be numeric") from exc
        if ctr_value < 0 or ctr_value > 1:
            raise AnalyticsSnapshotValidationError("impressions_ctr must be between 0 and 1")

    percentage_viewed = payload.get("average_percentage_viewed")
    if percentage_viewed is not None:
        try:
            pct_value = float(percentage_viewed)
        except (TypeError, ValueError) as exc:
            raise AnalyticsSnapshotValidationError("average_percentage_viewed must be numeric") from exc
        if pct_value < 0 or pct_value > 100:
            raise AnalyticsSnapshotValidationError("average_percentage_viewed must be between 0 and 100")

    missing_fields = payload.get("missing_fields") or []
    if not isinstance(missing_fields, list):
        raise AnalyticsSnapshotValidationError("missing_fields must be a list")

    canonicalized = dict(payload)
    canonicalized["schema_version"] = version
    canonicalized["snapshot_timestamp"] = parsed_timestamp.isoformat()
    canonicalized["snapshot_date"] = snapshot_date
    canonicalized["content_type"] = content_type
    canonicalized["missing_fields"] = list(missing_fields)
    canonicalized["snapshot_id"] = build_snapshot_id(canonicalized)
    return canonicalized


class AnalyticsSnapshotStore:
    def __init__(self, root: str | os.PathLike[str] | Path, *, channel_id: str) -> None:
        candidate_root = Path(root)
        if any(part in {"..", ""} for part in candidate_root.parts):
            raise AnalyticsSnapshotValidationError("storage root must not contain traversal segments")
        self.root = candidate_root.resolve()
        self.channel_id = str(channel_id or "").strip()
        if not self.channel_id:
            raise AnalyticsSnapshotValidationError("channel_id is required")
        self.store_path = self.root / self.channel_id / "snapshots.jsonl"
        self.store_path.parent.mkdir(parents=True, exist_ok=True)

        resolved_store = self.store_path.resolve()
        if not resolved_store.is_relative_to(self.root):
            raise AnalyticsSnapshotValidationError("storage path traversal is not allowed")

    def _load_existing_rows(self) -> list[dict[str, Any]]:
        if not self.store_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        try:
            for raw_line in self.store_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                parsed = json.loads(line)
                if not isinstance(parsed, dict):
                    raise AnalyticsSnapshotStoreError("malformed ledger content")
                rows.append(parsed)
        except json.JSONDecodeError as exc:
            raise AnalyticsSnapshotStoreError("malformed ledger content") from exc
        return rows

    def load_snapshots(self) -> list[dict[str, Any]]:
        return self._load_existing_rows()

    def append_snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        canonical = canonicalize_snapshot_payload(payload)
        if str(canonical.get("channel_id") or "") != self.channel_id:
            raise AnalyticsSnapshotValidationError("channel mismatch")

        existing_rows = self._load_existing_rows()
        for row in existing_rows:
            if row.get("snapshot_id") == canonical["snapshot_id"]:
                if row != canonical:
                    raise AnalyticsSnapshotStoreError("conflicting snapshot already exists")
                return {"status": "duplicate", **canonical}

        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        with self.store_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(canonical, ensure_ascii=False, sort_keys=True) + "\n")
        return {"status": "appended", **canonical}
