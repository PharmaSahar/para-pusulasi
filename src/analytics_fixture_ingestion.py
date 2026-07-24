from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
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
OBSERVABILITY_SCHEMA_VERSION = "project009.b3.v1"
OBSERVABILITY_EVIDENCE_VERSION = "evidence.v1"
TRANSACTION_POLICY = "VALIDATE_ALL_THEN_WRITE"


class FixtureIngestionError(RuntimeError):
    """Raised when fixture ingestion cannot be completed safely."""


class IngestionObservabilityError(RuntimeError):
    """Raised when observability evidence cannot be serialized safely."""


@dataclass(frozen=True, slots=True)
class IngestionRecordObservation:
    record_index: int
    snapshot_id: str | None
    channel_id: str | None
    youtube_video_id: str | None
    result: str
    error_category: str | None = None
    validation_stage: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "record_index": self.record_index,
            "snapshot_id": self.snapshot_id,
            "channel_id": self.channel_id,
            "youtube_video_id": self.youtube_video_id,
            "result": self.result,
            "error_category": self.error_category,
            "validation_stage": self.validation_stage,
        }


@dataclass(frozen=True, slots=True)
class IngestionRunReport:
    observability_schema_version: str
    run_id: str
    started_at: str
    completed_at: str
    duration_ms: int
    fixture_identity: str
    fixture_path_identity: str
    dry_run: bool
    transaction_policy: str
    storage_mutated: bool
    input_record_count: int
    valid_record_count: int
    appended_count: int
    duplicate_count: int
    rejected_count: int
    channel_ids_seen: tuple[str, ...]
    youtube_channel_ids_seen: tuple[str, ...]
    schema_versions_seen: tuple[str, ...]
    snapshot_ids: tuple[str, ...]
    error_categories: tuple[str, ...]
    outcome: str
    evidence_version: str
    record_results: tuple[IngestionRecordObservation, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "observability_schema_version": self.observability_schema_version,
            "run_id": self.run_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
            "fixture_identity": self.fixture_identity,
            "fixture_path_identity": self.fixture_path_identity,
            "dry_run": self.dry_run,
            "transaction_policy": self.transaction_policy,
            "storage_mutated": self.storage_mutated,
            "input_record_count": self.input_record_count,
            "valid_record_count": self.valid_record_count,
            "appended_count": self.appended_count,
            "duplicate_count": self.duplicate_count,
            "rejected_count": self.rejected_count,
            "channel_ids_seen": list(self.channel_ids_seen),
            "youtube_channel_ids_seen": list(self.youtube_channel_ids_seen),
            "schema_versions_seen": list(self.schema_versions_seen),
            "snapshot_ids": list(self.snapshot_ids),
            "error_categories": list(self.error_categories),
            "outcome": self.outcome,
            "evidence_version": self.evidence_version,
            "record_results": [record.to_payload() for record in self.record_results],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_payload(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def to_summary(self) -> str:
        return "\n".join(
            [
                f"run={self.run_id}",
                f"outcome={self.outcome}",
                f"records={self.input_record_count}",
                f"appended={self.appended_count}",
                f"duplicates={self.duplicate_count}",
                f"rejected={self.rejected_count}",
                f"dry_run={str(self.dry_run).lower()}",
                f"storage_mutated={str(self.storage_mutated).lower()}",
            ]
        )


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


def _build_fixture_path_identity(fixture_path: str | os.PathLike[str] | Path) -> str:
    path = Path(fixture_path)
    return hashlib.sha256(str(path.resolve().as_posix()).encode("utf-8")).hexdigest()


def _build_run_id(*, fixture_identity: str, dry_run: bool, expected_channel_id: str | None, evidence_version: str) -> str:
    payload = {
        "schema_version": OBSERVABILITY_SCHEMA_VERSION,
        "fixture_identity": fixture_identity,
        "dry_run": dry_run,
        "expected_channel_id": expected_channel_id or "",
        "transaction_policy": TRANSACTION_POLICY,
        "evidence_version": evidence_version,
    }
    return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


def _map_error_category(error: Exception, *, stage: str) -> tuple[str, str]:
    message = str(error).lower()
    if "fixture file is missing" in message:
        return "FIXTURE_NOT_FOUND", stage
    if "unsupported fixture extension" in message:
        return "UNSUPPORTED_FIXTURE_EXTENSION", stage
    if "invalid json fixture" in message:
        return "INVALID_JSON", stage
    if "fixture root must be a list or object" in message or "fixture root must be a list" in message:
        return "INVALID_ROOT_TYPE", stage
    if "fixture is empty" in message:
        return "EMPTY_FIXTURE", stage
    if "fixture exceeds maximum record count" in message:
        return "RECORD_LIMIT_EXCEEDED", stage
    if "unknown fields" in message:
        return "UNKNOWN_FIELD", stage
    if "unsupported schema_version" in message or "schema_version is required" in message:
        return "INVALID_SCHEMA_VERSION", stage
    if "snapshot_timestamp" in message and "timezone-aware" in message:
        return "INVALID_TIMESTAMP", stage
    if "channel_id is required" in message or "youtube_channel_id is required" in message or "internal_video_id is required" in message or "youtube_video_id is required" in message or "content_job_id is required" in message or "metric_source is required" in message or "provenance_reference is required" in message:
        return "INVALID_IDENTITY", stage
    if "must be numeric or null" in message or "must not be boolean" in message or "must not be negative" in message or "between 0 and 1" in message or "between 0 and 100" in message:
        return "INVALID_METRIC", stage
    if "expected channel mismatch" in message or "mixed-channel fixture" in message:
        return "CHANNEL_MISMATCH", stage
    if "youtube channel mismatch" in message or "youtube_channel_id is inconsistent" in message:
        return "YOUTUBE_CHANNEL_MISMATCH", stage
    if "malformed ledger content" in message:
        return "MALFORMED_STORE", stage
    if "traversal" in message or "storage root must not contain traversal segments" in message:
        return "PATH_SAFETY_VIOLATION", stage
    if "conflicting snapshot already exists" in message:
        return "DUPLICATE_CONFLICT", stage
    return "INTERNAL_ERROR", stage


def _serialize_report(report: IngestionRunReport) -> str:
    return report.to_json()


def write_ingestion_evidence(report: IngestionRunReport, output_path: str | os.PathLike[str] | Path) -> dict[str, Any]:
    if output_path is None:
        raise IngestionObservabilityError("output_path is required")
    target = Path(output_path)
    if any(part == ".." for part in target.parts):
        raise IngestionObservabilityError("path traversal is not allowed")
    payload = _serialize_report(report).encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(prefix="ingestion-report-", suffix=".json", dir=str(target.parent))
    try:
        with os.fdopen(tmp_fd, "wb") as handle:
            handle.write(payload)
        if target.exists():
            existing = target.read_bytes()
            if existing == payload:
                os.unlink(tmp_path)
                return {"status": "unchanged", "path": str(target)}
            raise IngestionObservabilityError("evidence conflict")
        os.replace(tmp_path, target)
        return {"status": "written", "path": str(target)}
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


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


def _build_summary_result(
    *,
    input_record_count: int,
    valid_record_count: int,
    appended_count: int,
    duplicate_count: int,
    rejected_count: int,
    channel_ids_seen: list[str],
    youtube_channel_ids_seen: list[str],
    schema_versions_seen: list[str],
    snapshot_ids: list[str],
    error_categories: list[str],
    dry_run: bool,
    fixture_identity: str,
    fixture_path_identity: str,
    report_outcome: str,
    started_at: str,
    completed_at: str,
    duration_ms: int,
    record_results: list[IngestionRecordObservation],
    storage_mutated: bool,
    run_id: str,
) -> dict[str, Any]:
    return {
        "input_record_count": input_record_count,
        "valid_record_count": valid_record_count,
        "appended_count": appended_count,
        "duplicate_count": duplicate_count,
        "rejected_count": rejected_count,
        "channel_ids_seen": sorted(channel_ids_seen),
        "youtube_channel_ids_seen": sorted(youtube_channel_ids_seen),
        "schema_versions_seen": sorted(schema_versions_seen),
        "snapshot_ids": snapshot_ids,
        "error_categories": sorted(error_categories),
        "dry_run": dry_run,
        "fixture_identity": fixture_identity,
        "fixture_path_identity": fixture_path_identity,
        "run_id": run_id,
        "observability_report": {
            "observability_schema_version": OBSERVABILITY_SCHEMA_VERSION,
            "run_id": run_id,
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_ms": duration_ms,
            "fixture_identity": fixture_identity,
            "fixture_path_identity": fixture_path_identity,
            "dry_run": dry_run,
            "transaction_policy": TRANSACTION_POLICY,
            "storage_mutated": storage_mutated,
            "input_record_count": input_record_count,
            "valid_record_count": valid_record_count,
            "appended_count": appended_count,
            "duplicate_count": duplicate_count,
            "rejected_count": rejected_count,
            "channel_ids_seen": sorted(channel_ids_seen),
            "youtube_channel_ids_seen": sorted(youtube_channel_ids_seen),
            "schema_versions_seen": sorted(schema_versions_seen),
            "snapshot_ids": snapshot_ids,
            "error_categories": sorted(error_categories),
            "outcome": report_outcome,
            "evidence_version": OBSERVABILITY_EVIDENCE_VERSION,
            "record_results": [record.to_payload() for record in record_results],
        },
    }


def ingest_fixture_with_observability(
    fixture_path: str | os.PathLike[str] | Path,
    store_root: str | os.PathLike[str] | Path,
    *,
    expected_channel_id: str | None = None,
    dry_run: bool = False,
    evidence_output_path: str | os.PathLike[str] | Path | None = None,
) -> tuple[dict[str, Any], IngestionRunReport]:
    fixture_path = Path(fixture_path)
    store_root = Path(store_root)
    started_monotonic = time.perf_counter()
    started_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    if not fixture_path.exists():
        completed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        duration_ms = max(0, int((time.perf_counter() - started_monotonic) * 1000))
        fixture_identity = ""
        fixture_path_identity = _build_fixture_path_identity(fixture_path)
        run_id = _build_run_id(fixture_identity=fixture_identity, dry_run=dry_run, expected_channel_id=expected_channel_id, evidence_version=OBSERVABILITY_EVIDENCE_VERSION)
        report = IngestionRunReport(
            observability_schema_version=OBSERVABILITY_SCHEMA_VERSION,
            run_id=run_id,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            fixture_identity=fixture_identity,
            fixture_path_identity=fixture_path_identity,
            dry_run=dry_run,
            transaction_policy=TRANSACTION_POLICY,
            storage_mutated=False,
            input_record_count=0,
            valid_record_count=0,
            appended_count=0,
            duplicate_count=0,
            rejected_count=0,
            channel_ids_seen=tuple(),
            youtube_channel_ids_seen=tuple(),
            schema_versions_seen=tuple(),
            snapshot_ids=tuple(),
            error_categories=("FIXTURE_NOT_FOUND",),
            outcome="REJECTED",
            evidence_version=OBSERVABILITY_EVIDENCE_VERSION,
            record_results=tuple(),
        )
        return _build_summary_result(
            input_record_count=0,
            valid_record_count=0,
            appended_count=0,
            duplicate_count=0,
            rejected_count=0,
            channel_ids_seen=[],
            youtube_channel_ids_seen=[],
            schema_versions_seen=[],
            snapshot_ids=[],
            error_categories=["FIXTURE_NOT_FOUND"],
            dry_run=dry_run,
            fixture_identity=fixture_identity,
            fixture_path_identity=fixture_path_identity,
            report_outcome="REJECTED",
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            record_results=[],
            storage_mutated=False,
            run_id=run_id,
        ), report

    try:
        records = load_fixture_records(fixture_path)
    except FixtureIngestionError as exc:
        completed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        duration_ms = max(0, int((time.perf_counter() - started_monotonic) * 1000))
        fixture_identity = ""
        fixture_path_identity = _build_fixture_path_identity(fixture_path)
        run_id = _build_run_id(fixture_identity=fixture_identity, dry_run=dry_run, expected_channel_id=expected_channel_id, evidence_version=OBSERVABILITY_EVIDENCE_VERSION)
        error_category, stage = _map_error_category(exc, stage="FIXTURE_LOAD")
        report = IngestionRunReport(
            observability_schema_version=OBSERVABILITY_SCHEMA_VERSION,
            run_id=run_id,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            fixture_identity=fixture_identity,
            fixture_path_identity=fixture_path_identity,
            dry_run=dry_run,
            transaction_policy=TRANSACTION_POLICY,
            storage_mutated=False,
            input_record_count=0,
            valid_record_count=0,
            appended_count=0,
            duplicate_count=0,
            rejected_count=0,
            channel_ids_seen=tuple(),
            youtube_channel_ids_seen=tuple(),
            schema_versions_seen=tuple(),
            snapshot_ids=tuple(),
            error_categories=(error_category,),
            outcome="REJECTED",
            evidence_version=OBSERVABILITY_EVIDENCE_VERSION,
            record_results=tuple(),
        )
        return _build_summary_result(
            input_record_count=0,
            valid_record_count=0,
            appended_count=0,
            duplicate_count=0,
            rejected_count=0,
            channel_ids_seen=[],
            youtube_channel_ids_seen=[],
            schema_versions_seen=[],
            snapshot_ids=[],
            error_categories=[error_category],
            dry_run=dry_run,
            fixture_identity=fixture_identity,
            fixture_path_identity=fixture_path_identity,
            report_outcome="REJECTED",
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            record_results=[],
            storage_mutated=False,
            run_id=run_id,
        ), report

    fixture_identity = build_fixture_identity(fixture_path)
    fixture_path_identity = _build_fixture_path_identity(fixture_path)
    run_id = _build_run_id(fixture_identity=fixture_identity, dry_run=dry_run, expected_channel_id=expected_channel_id, evidence_version=OBSERVABILITY_EVIDENCE_VERSION)

    if expected_channel_id is not None:
        expected_channel_id = str(expected_channel_id).strip()
        if not expected_channel_id:
            completed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            duration_ms = max(0, int((time.perf_counter() - started_monotonic) * 1000))
            report = IngestionRunReport(
                observability_schema_version=OBSERVABILITY_SCHEMA_VERSION,
                run_id=run_id,
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=duration_ms,
                fixture_identity=fixture_identity,
                fixture_path_identity=fixture_path_identity,
                dry_run=dry_run,
                transaction_policy=TRANSACTION_POLICY,
                storage_mutated=False,
                input_record_count=0,
                valid_record_count=0,
                appended_count=0,
                duplicate_count=0,
                rejected_count=0,
                channel_ids_seen=tuple(),
                youtube_channel_ids_seen=tuple(),
                schema_versions_seen=tuple(),
                snapshot_ids=tuple(),
                error_categories=("CHANNEL_MISMATCH",),
                outcome="REJECTED",
                evidence_version=OBSERVABILITY_EVIDENCE_VERSION,
                record_results=tuple(),
            )
            return _build_summary_result(
                input_record_count=0,
                valid_record_count=0,
                appended_count=0,
                duplicate_count=0,
                rejected_count=0,
                channel_ids_seen=[],
                youtube_channel_ids_seen=[],
                schema_versions_seen=[],
                snapshot_ids=[],
                error_categories=["CHANNEL_MISMATCH"],
                dry_run=dry_run,
                fixture_identity=fixture_identity,
                fixture_path_identity=fixture_path_identity,
                report_outcome="REJECTED",
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=duration_ms,
                record_results=[],
                storage_mutated=False,
                run_id=run_id,
            ), report

    canonical_records: list[dict[str, Any]] = []
    record_results: list[IngestionRecordObservation] = []
    channel_ids_seen: set[str] = set()
    youtube_channel_ids_seen: set[str] = set()
    schema_versions_seen: set[str] = set()
    snapshot_ids: list[str] = []
    error_categories: set[str] = set()
    valid_record_count = 0
    appended_count = 0
    duplicate_count = 0
    rejected_count = 0

    for index, record in enumerate(records):
        channel_id = str(record.get("channel_id") or "").strip()
        channel_ids_seen.add(channel_id)
        schema_versions_seen.add(str(record.get("schema_version") or ""))

        if expected_channel_id is not None and channel_id != expected_channel_id:
            rejected_count += 1
            record_results.append(
                IngestionRecordObservation(
                    record_index=index,
                    snapshot_id=None,
                    channel_id=channel_id,
                    youtube_video_id=str(record.get("youtube_video_id") or "").strip() or None,
                    result="REJECTED",
                    error_category="CHANNEL_MISMATCH",
                    validation_stage="CHANNEL_VALIDATION",
                )
            )
            error_categories.add("CHANNEL_MISMATCH")
            break

        youtube_channel_id = str(record.get("youtube_channel_id") or "").strip()
        youtube_channel_ids_seen.add(youtube_channel_id)
        if not youtube_channel_id:
            rejected_count += 1
            record_results.append(
                IngestionRecordObservation(
                    record_index=index,
                    snapshot_id=None,
                    channel_id=channel_id,
                    youtube_video_id=str(record.get("youtube_video_id") or "").strip() or None,
                    result="REJECTED",
                    error_category="INVALID_IDENTITY",
                    validation_stage="CHANNEL_VALIDATION",
                )
            )
            error_categories.add("INVALID_IDENTITY")
            break
        if not youtube_channel_id.startswith("UC"):
            rejected_count += 1
            record_results.append(
                IngestionRecordObservation(
                    record_index=index,
                    snapshot_id=None,
                    channel_id=channel_id,
                    youtube_video_id=str(record.get("youtube_video_id") or "").strip() or None,
                    result="REJECTED",
                    error_category="YOUTUBE_CHANNEL_MISMATCH",
                    validation_stage="CHANNEL_VALIDATION",
                )
            )
            error_categories.add("YOUTUBE_CHANNEL_MISMATCH")
            break
        expected_youtube_channel_id = f"UC-{channel_id.split('_')[-1]}"
        if youtube_channel_id != expected_youtube_channel_id:
            rejected_count += 1
            record_results.append(
                IngestionRecordObservation(
                    record_index=index,
                    snapshot_id=None,
                    channel_id=channel_id,
                    youtube_video_id=str(record.get("youtube_video_id") or "").strip() or None,
                    result="REJECTED",
                    error_category="YOUTUBE_CHANNEL_MISMATCH",
                    validation_stage="CHANNEL_VALIDATION",
                )
            )
            error_categories.add("YOUTUBE_CHANNEL_MISMATCH")
            break

        try:
            canonical_record = canonicalize_snapshot_payload(record)
        except AnalyticsSnapshotValidationError as exc:
            rejected_count += 1
            error_category, stage = _map_error_category(exc, stage="CANONICAL_VALIDATION")
            record_results.append(
                IngestionRecordObservation(
                    record_index=index,
                    snapshot_id=None,
                    channel_id=channel_id,
                    youtube_video_id=str(record.get("youtube_video_id") or "").strip() or None,
                    result="REJECTED",
                    error_category=error_category,
                    validation_stage=stage,
                )
            )
            error_categories.add(error_category)
            break

        valid_record_count += 1
        canonical_records.append(canonical_record)
        snapshot_ids.append(canonical_record["snapshot_id"])

    if rejected_count:
        completed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        duration_ms = max(0, int((time.perf_counter() - started_monotonic) * 1000))
        report = IngestionRunReport(
            observability_schema_version=OBSERVABILITY_SCHEMA_VERSION,
            run_id=run_id,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            fixture_identity=fixture_identity,
            fixture_path_identity=fixture_path_identity,
            dry_run=dry_run,
            transaction_policy=TRANSACTION_POLICY,
            storage_mutated=False,
            input_record_count=len(records),
            valid_record_count=valid_record_count,
            appended_count=0,
            duplicate_count=0,
            rejected_count=rejected_count,
            channel_ids_seen=tuple(sorted(channel_ids_seen)),
            youtube_channel_ids_seen=tuple(sorted(youtube_channel_ids_seen)),
            schema_versions_seen=tuple(sorted(schema_versions_seen)),
            snapshot_ids=tuple(snapshot_ids),
            error_categories=tuple(sorted(error_categories)),
            outcome="REJECTED",
            evidence_version=OBSERVABILITY_EVIDENCE_VERSION,
            record_results=tuple(record_results),
        )
        return _build_summary_result(
            input_record_count=len(records),
            valid_record_count=valid_record_count,
            appended_count=0,
            duplicate_count=0,
            rejected_count=rejected_count,
            channel_ids_seen=list(channel_ids_seen),
            youtube_channel_ids_seen=list(youtube_channel_ids_seen),
            schema_versions_seen=list(schema_versions_seen),
            snapshot_ids=snapshot_ids,
            error_categories=list(error_categories),
            dry_run=dry_run,
            fixture_identity=fixture_identity,
            fixture_path_identity=fixture_path_identity,
            report_outcome="REJECTED",
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            record_results=record_results,
            storage_mutated=False,
            run_id=run_id,
        ), report

    if dry_run:
        completed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        duration_ms = max(0, int((time.perf_counter() - started_monotonic) * 1000))
        report = IngestionRunReport(
            observability_schema_version=OBSERVABILITY_SCHEMA_VERSION,
            run_id=run_id,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            fixture_identity=fixture_identity,
            fixture_path_identity=fixture_path_identity,
            dry_run=True,
            transaction_policy=TRANSACTION_POLICY,
            storage_mutated=False,
            input_record_count=len(records),
            valid_record_count=valid_record_count,
            appended_count=0,
            duplicate_count=0,
            rejected_count=0,
            channel_ids_seen=tuple(sorted(channel_ids_seen)),
            youtube_channel_ids_seen=tuple(sorted(youtube_channel_ids_seen)),
            schema_versions_seen=tuple(sorted(schema_versions_seen)),
            snapshot_ids=tuple(snapshot_ids),
            error_categories=tuple(),
            outcome="SUCCESS",
            evidence_version=OBSERVABILITY_EVIDENCE_VERSION,
            record_results=tuple(
                IngestionRecordObservation(
                    record_index=index,
                    snapshot_id=canonical_record["snapshot_id"],
                    channel_id=canonical_record.get("channel_id"),
                    youtube_video_id=canonical_record.get("youtube_video_id"),
                    result="APPENDED",
                    error_category=None,
                    validation_stage="APPEND",
                )
                for index, canonical_record in enumerate(canonical_records)
            ),
        )
        return _build_summary_result(
            input_record_count=len(records),
            valid_record_count=valid_record_count,
            appended_count=0,
            duplicate_count=0,
            rejected_count=0,
            channel_ids_seen=list(channel_ids_seen),
            youtube_channel_ids_seen=list(youtube_channel_ids_seen),
            schema_versions_seen=list(schema_versions_seen),
            snapshot_ids=snapshot_ids,
            error_categories=[],
            dry_run=True,
            fixture_identity=fixture_identity,
            fixture_path_identity=fixture_path_identity,
            report_outcome="SUCCESS",
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            record_results=report.record_results,
            storage_mutated=False,
            run_id=run_id,
        ), report

    store = AnalyticsSnapshotStore(store_root, channel_id=next(iter(channel_ids_seen)))
    try:
        existing_rows = store.load_snapshots()
    except AnalyticsSnapshotStoreError as exc:
        completed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        duration_ms = max(0, int((time.perf_counter() - started_monotonic) * 1000))
        error_category, stage = _map_error_category(exc, stage="STORE_VALIDATION")
        report = IngestionRunReport(
            observability_schema_version=OBSERVABILITY_SCHEMA_VERSION,
            run_id=run_id,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            fixture_identity=fixture_identity,
            fixture_path_identity=fixture_path_identity,
            dry_run=False,
            transaction_policy=TRANSACTION_POLICY,
            storage_mutated=False,
            input_record_count=len(records),
            valid_record_count=valid_record_count,
            appended_count=0,
            duplicate_count=0,
            rejected_count=len(canonical_records),
            channel_ids_seen=tuple(sorted(channel_ids_seen)),
            youtube_channel_ids_seen=tuple(sorted(youtube_channel_ids_seen)),
            schema_versions_seen=tuple(sorted(schema_versions_seen)),
            snapshot_ids=tuple(snapshot_ids),
            error_categories=(error_category,),
            outcome="FAILED",
            evidence_version=OBSERVABILITY_EVIDENCE_VERSION,
            record_results=tuple(
                IngestionRecordObservation(
                    record_index=index,
                    snapshot_id=canonical_record["snapshot_id"],
                    channel_id=canonical_record.get("channel_id"),
                    youtube_video_id=canonical_record.get("youtube_video_id"),
                    result="REJECTED",
                    error_category=error_category,
                    validation_stage=stage,
                )
                for index, canonical_record in enumerate(canonical_records)
            ),
        )
        return _build_summary_result(
            input_record_count=len(records),
            valid_record_count=valid_record_count,
            appended_count=0,
            duplicate_count=0,
            rejected_count=len(canonical_records),
            channel_ids_seen=list(channel_ids_seen),
            youtube_channel_ids_seen=list(youtube_channel_ids_seen),
            schema_versions_seen=list(schema_versions_seen),
            snapshot_ids=snapshot_ids,
            error_categories=[error_category],
            dry_run=False,
            fixture_identity=fixture_identity,
            fixture_path_identity=fixture_path_identity,
            report_outcome="FAILED",
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            record_results=report.record_results,
            storage_mutated=False,
            run_id=run_id,
        ), report

    write_results: list[IngestionRecordObservation] = []
    for index, canonical_record in enumerate(canonical_records):
        try:
            append_result = store.append_snapshot(canonical_record)
        except AnalyticsSnapshotStoreError as exc:
            error_category, stage = _map_error_category(exc, stage="APPEND")
            write_results.append(
                IngestionRecordObservation(
                    record_index=index,
                    snapshot_id=canonical_record.get("snapshot_id"),
                    channel_id=canonical_record.get("channel_id"),
                    youtube_video_id=canonical_record.get("youtube_video_id"),
                    result="REJECTED",
                    error_category=error_category,
                    validation_stage=stage,
                )
            )
            error_categories.add(error_category)
            continue
        if append_result["status"] == "appended":
            appended_count += 1
            write_results.append(
                IngestionRecordObservation(
                    record_index=index,
                    snapshot_id=append_result.get("snapshot_id"),
                    channel_id=append_result.get("channel_id"),
                    youtube_video_id=append_result.get("youtube_video_id"),
                    result="APPENDED",
                    error_category=None,
                    validation_stage="APPEND",
                )
            )
        elif append_result["status"] == "duplicate":
            duplicate_count += 1
            write_results.append(
                IngestionRecordObservation(
                    record_index=index,
                    snapshot_id=append_result.get("snapshot_id"),
                    channel_id=append_result.get("channel_id"),
                    youtube_video_id=append_result.get("youtube_video_id"),
                    result="DUPLICATE",
                    error_category="DUPLICATE_CONFLICT",
                    validation_stage="APPEND",
                )
            )
        else:
            error_categories.add("INTERNAL_ERROR")
            write_results.append(
                IngestionRecordObservation(
                    record_index=index,
                    snapshot_id=canonical_record.get("snapshot_id"),
                    channel_id=canonical_record.get("channel_id"),
                    youtube_video_id=canonical_record.get("youtube_video_id"),
                    result="REJECTED",
                    error_category="INTERNAL_ERROR",
                    validation_stage="APPEND",
                )
            )

    if evidence_output_path is not None:
        write_ingestion_evidence(
            IngestionRunReport(
                observability_schema_version=OBSERVABILITY_SCHEMA_VERSION,
                run_id=run_id,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                duration_ms=max(0, int((time.perf_counter() - started_monotonic) * 1000)),
                fixture_identity=fixture_identity,
                fixture_path_identity=fixture_path_identity,
                dry_run=False,
                transaction_policy=TRANSACTION_POLICY,
                storage_mutated=appended_count > 0,
                input_record_count=len(records),
                valid_record_count=valid_record_count,
                appended_count=appended_count,
                duplicate_count=duplicate_count,
                rejected_count=0,
                channel_ids_seen=tuple(sorted(channel_ids_seen)),
                youtube_channel_ids_seen=tuple(sorted(youtube_channel_ids_seen)),
                schema_versions_seen=tuple(sorted(schema_versions_seen)),
                snapshot_ids=tuple(snapshot_ids),
                error_categories=tuple(sorted(error_categories)),
                outcome="SUCCESS_WITH_DUPLICATES" if duplicate_count and appended_count else "SUCCESS",
                evidence_version=OBSERVABILITY_EVIDENCE_VERSION,
                record_results=tuple(write_results),
            ),
            evidence_output_path,
        )

    completed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    duration_ms = max(0, int((time.perf_counter() - started_monotonic) * 1000))
    report = IngestionRunReport(
        observability_schema_version=OBSERVABILITY_SCHEMA_VERSION,
        run_id=run_id,
        started_at=started_at,
        completed_at=completed_at,
        duration_ms=duration_ms,
        fixture_identity=fixture_identity,
        fixture_path_identity=fixture_path_identity,
        dry_run=False,
        transaction_policy=TRANSACTION_POLICY,
        storage_mutated=appended_count > 0,
        input_record_count=len(records),
        valid_record_count=valid_record_count,
        appended_count=appended_count,
        duplicate_count=duplicate_count,
        rejected_count=0,
        channel_ids_seen=tuple(sorted(channel_ids_seen)),
        youtube_channel_ids_seen=tuple(sorted(youtube_channel_ids_seen)),
        schema_versions_seen=tuple(sorted(schema_versions_seen)),
        snapshot_ids=tuple(snapshot_ids),
        error_categories=tuple(sorted(error_categories)),
        outcome="SUCCESS_WITH_DUPLICATES" if duplicate_count > 0 and appended_count == 0 else "SUCCESS_WITH_DUPLICATES" if duplicate_count > 0 else "SUCCESS",
        evidence_version=OBSERVABILITY_EVIDENCE_VERSION,
        record_results=tuple(write_results),
    )
    return _build_summary_result(
        input_record_count=len(records),
        valid_record_count=valid_record_count,
        appended_count=appended_count,
        duplicate_count=duplicate_count,
        rejected_count=0,
        channel_ids_seen=list(channel_ids_seen),
        youtube_channel_ids_seen=list(youtube_channel_ids_seen),
        schema_versions_seen=list(schema_versions_seen),
        snapshot_ids=snapshot_ids,
        error_categories=list(error_categories),
        dry_run=False,
        fixture_identity=fixture_identity,
        fixture_path_identity=fixture_path_identity,
        report_outcome=report.outcome,
        started_at=started_at,
        completed_at=completed_at,
        duration_ms=duration_ms,
        record_results=write_results,
        storage_mutated=appended_count > 0,
        run_id=run_id,
    ), report


def ingest_fixture(
    fixture_path: str | os.PathLike[str] | Path,
    store_root: str | os.PathLike[str] | Path,
    *,
    expected_channel_id: str | None = None,
    dry_run: bool = False,
    include_observability: bool = False,
    evidence_output_path: str | os.PathLike[str] | Path | None = None,
) -> dict[str, Any]:
    result, report = ingest_fixture_with_observability(
        fixture_path,
        store_root,
        expected_channel_id=expected_channel_id,
        dry_run=dry_run,
        evidence_output_path=evidence_output_path,
    )
    if report.outcome in {"REJECTED", "FAILED"}:
        raise FixtureIngestionError("ingestion rejected")
    if include_observability:
        result["observability_report"] = report.to_payload()
    return result
