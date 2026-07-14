from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
from typing import Any

ANALYTICS_EVIDENCE_JOIN_SCHEMA_VERSION = "v1"
DEFAULT_ANALYTICS_EVIDENCE_JOIN_PATH = Path("logs/analytics_evidence_join.jsonl")
DEFAULT_CHANNEL_PERFORMANCE_PATH = Path("logs/channel_performance.jsonl")
DEFAULT_ANALYTICS_FEEDBACK_PATH = Path("logs/analytics_feedback.jsonl")
DEFAULT_RUNTIME_EVIDENCE_DIR = Path("output/runtime/evidence")
DEFAULT_OWNERSHIP_DIR = Path("output/state/content_ownership")


class MetricAvailability(str, Enum):
    OBSERVED = "observed"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class AnalyticsJoinMethod(str, Enum):
    BY_CONTENT_ID = "BY_CONTENT_ID"
    BY_UPLOAD_ID = "BY_UPLOAD_ID"
    BY_RUN_ID = "BY_RUN_ID"
    BY_OWNERSHIP_LINKAGE = "BY_OWNERSHIP_LINKAGE"
    UNRESOLVED = "UNRESOLVED"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True)
class AnalyticsEvidenceAppendResult:
    appended: bool
    duplicate: bool
    reason: str


@dataclass(frozen=True)
class AnalyticsEvidenceReplayDiagnostics:
    malformed_rows: int
    replay_errors: list[str]


@dataclass(frozen=True)
class AnalyticsLineageCandidate:
    content_id: str | None
    run_id: str | None
    upload_id: str | None
    channel_id: str | None
    ownership_id: str | None
    provenance: str


@dataclass(frozen=True)
class AnalyticsEvidenceRecord:
    schema_version: str
    analytics_record_id: str
    source_type: str
    join_method: str
    content_id: str | None
    run_id: str | None
    upload_id: str | None
    channel_id: str | None
    snapshot_time: str
    metrics_version: str
    provenance: dict[str, Any]
    metrics: dict[str, dict[str, Any]]
    advisory_only: bool
    pipeline_output_changed: bool
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return validate_analytics_evidence_row(
            {
                "schema_version": self.schema_version,
                "analytics_record_id": self.analytics_record_id,
                "source_type": self.source_type,
                "join_method": self.join_method,
                "content_id": self.content_id,
                "run_id": self.run_id,
                "upload_id": self.upload_id,
                "channel_id": self.channel_id,
                "snapshot_time": self.snapshot_time,
                "metrics_version": self.metrics_version,
                "provenance": dict(self.provenance),
                "metrics": dict(self.metrics),
                "advisory_only": bool(self.advisory_only),
                "pipeline_output_changed": bool(self.pipeline_output_changed),
                "created_at": self.created_at,
            }
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _sha(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def _is_enabled(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def analytics_evidence_join_enabled() -> bool:
    return _is_enabled(os.getenv("ANALYTICS_EVIDENCE_JOIN_ENABLED", "false"))


def _parse_iso_or_now(value: Any) -> str:
    text = _safe_text(value)
    if not text:
        return _now_iso()
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
        return text
    except Exception:
        return _now_iso()


def _load_jsonl_rows(path: Path) -> tuple[list[dict[str, Any]], int]:
    if not path.exists():
        return [], 0
    rows: list[dict[str, Any]] = []
    malformed = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
            if isinstance(payload, dict):
                rows.append(payload)
            else:
                malformed += 1
        except Exception:
            malformed += 1
    return rows, malformed


def _load_runtime_rows(runtime_dir: Path, limit: int) -> tuple[list[dict[str, Any]], int]:
    if not runtime_dir.exists():
        return [], 0

    rows: list[dict[str, Any]] = []
    malformed = 0
    files = sorted(runtime_dir.glob("*.json"))
    if limit > 0:
        files = files[-limit:]

    for path in files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                payload["__runtime_path"] = str(path)
                rows.append(payload)
            else:
                malformed += 1
        except Exception:
            malformed += 1
    return rows, malformed


def _load_ownership_rows(ownership_dir: Path, limit: int) -> tuple[list[dict[str, Any]], int]:
    if not ownership_dir.exists():
        return [], 0

    rows: list[dict[str, Any]] = []
    malformed = 0
    files = sorted(ownership_dir.glob("*.json"))
    if limit > 0:
        files = files[-limit:]

    for path in files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                payload["__ownership_path"] = str(path)
                rows.append(payload)
            else:
                malformed += 1
        except Exception:
            malformed += 1
    return rows, malformed


def _metric_payload(*, present: bool, value: Any) -> dict[str, Any]:
    if present and value is not None:
        return {"state": MetricAvailability.OBSERVED.value, "value": value}
    if present:
        return {"state": MetricAvailability.UNAVAILABLE.value, "value": None}
    return {"state": MetricAvailability.UNKNOWN.value, "value": None}


def _extract_metrics(source_row: dict[str, Any]) -> dict[str, dict[str, Any]]:
    keys = [
        "impressions",
        "click_through_rate",
        "ctr",
        "average_view_duration_seconds",
        "average_view_duration",
        "average_view_percentage",
        "average_percentage_viewed",
        "watch_time_hours",
        "likes",
        "comments",
        "shares",
        "subscribers_gained",
        "suggested_video_traffic",
        "browse_traffic",
        "search_traffic",
        "end_screen_ctr",
        "card_ctr",
        "playlist_additions",
    ]
    metrics: dict[str, dict[str, Any]] = {}
    for key in keys:
        metrics[key] = _metric_payload(present=(key in source_row), value=source_row.get(key))
    metrics["traffic_sources"] = _metric_payload(
        present=("traffic_sources" in source_row),
        value=source_row.get("traffic_sources") if isinstance(source_row.get("traffic_sources"), dict) else None,
    )
    metrics["audience_retention"] = _metric_payload(
        present=("audience_retention" in source_row),
        value=source_row.get("audience_retention") if isinstance(source_row.get("audience_retention"), dict) else None,
    )
    return metrics


def build_analytics_source_inventory(
    *,
    channel_performance_path: Path | str = DEFAULT_CHANNEL_PERFORMANCE_PATH,
    analytics_feedback_path: Path | str = DEFAULT_ANALYTICS_FEEDBACK_PATH,
    runtime_evidence_dir: Path | str = DEFAULT_RUNTIME_EVIDENCE_DIR,
    ownership_dir: Path | str = DEFAULT_OWNERSHIP_DIR,
    limit: int = 0,
) -> dict[str, Any]:
    cp_rows, cp_malformed = _load_jsonl_rows(Path(channel_performance_path))
    af_rows, af_malformed = _load_jsonl_rows(Path(analytics_feedback_path))
    runtime_rows, runtime_malformed = _load_runtime_rows(Path(runtime_evidence_dir), limit=limit)
    ownership_rows, ownership_malformed = _load_ownership_rows(Path(ownership_dir), limit=limit)

    return {
        "channel_performance": {
            "path": str(channel_performance_path),
            "count": len(cp_rows),
            "malformed": cp_malformed,
            "available": Path(channel_performance_path).exists(),
        },
        "analytics_feedback": {
            "path": str(analytics_feedback_path),
            "count": len(af_rows),
            "malformed": af_malformed,
            "available": Path(analytics_feedback_path).exists(),
        },
        "runtime_evidence": {
            "path": str(runtime_evidence_dir),
            "count": len(runtime_rows),
            "malformed": runtime_malformed,
            "available": Path(runtime_evidence_dir).exists(),
        },
        "content_ownership": {
            "path": str(ownership_dir),
            "count": len(ownership_rows),
            "malformed": ownership_malformed,
            "available": Path(ownership_dir).exists(),
        },
    }


class _LineageIndex:
    def __init__(self):
        self.by_content_id: dict[str, list[AnalyticsLineageCandidate]] = {}
        self.by_upload_id: dict[str, list[AnalyticsLineageCandidate]] = {}
        self.by_run_id: dict[str, list[AnalyticsLineageCandidate]] = {}
        self.by_ownership_id: dict[str, list[AnalyticsLineageCandidate]] = {}

    def _add(self, mapping: dict[str, list[AnalyticsLineageCandidate]], key: str, candidate: AnalyticsLineageCandidate) -> None:
        bucket = mapping.setdefault(key, [])
        if candidate not in bucket:
            bucket.append(candidate)

    def add(self, candidate: AnalyticsLineageCandidate) -> None:
        if _safe_text(candidate.content_id):
            self._add(self.by_content_id, _safe_text(candidate.content_id), candidate)
        if _safe_text(candidate.upload_id):
            self._add(self.by_upload_id, _safe_text(candidate.upload_id), candidate)
        if _safe_text(candidate.run_id):
            self._add(self.by_run_id, _safe_text(candidate.run_id), candidate)
        if _safe_text(candidate.ownership_id):
            self._add(self.by_ownership_id, _safe_text(candidate.ownership_id), candidate)


def _build_lineage_index(*, runtime_rows: list[dict[str, Any]], ownership_rows: list[dict[str, Any]]) -> _LineageIndex:
    index = _LineageIndex()

    for row in ownership_rows:
        path = Path(str(row.get("__ownership_path") or ""))
        ownership_id = path.stem or None
        index.add(
            AnalyticsLineageCandidate(
                content_id=_safe_text(row.get("content_id")) or None,
                run_id=_safe_text(row.get("run_id")) or None,
                upload_id=None,
                channel_id=_safe_text(row.get("channel_id")) or None,
                ownership_id=ownership_id,
                provenance="ownership_manifest",
            )
        )

    for row in runtime_rows:
        upload_metadata = row.get("upload_metadata") if isinstance(row.get("upload_metadata"), dict) else {}
        upload_id = _safe_text(row.get("video_id")) or _safe_text(upload_metadata.get("video_id")) or None
        ownership_path = _safe_text(upload_metadata.get("ownership_manifest_path"))
        ownership_id = Path(ownership_path).stem if ownership_path else None

        index.add(
            AnalyticsLineageCandidate(
                content_id=_safe_text(row.get("content_id")) or None,
                run_id=_safe_text(row.get("run_id")) or None,
                upload_id=upload_id,
                channel_id=_safe_text(row.get("channel")) or None,
                ownership_id=ownership_id,
                provenance="runtime_evidence",
            )
        )

    try:
        from .forward_evidence_capture import reconstruct_forward_sessions

        sessions, _diagnostics = reconstruct_forward_sessions()
        for payload in sessions.values():
            latest = dict(payload.get("latest") or {})
            index.add(
                AnalyticsLineageCandidate(
                    content_id=_safe_text(payload.get("content_id")) or None,
                    run_id=_safe_text(payload.get("run_id")) or None,
                    upload_id=_safe_text(latest.get("upload_id")) or None,
                    channel_id=_safe_text(payload.get("channel_id")) or None,
                    ownership_id=_safe_text(latest.get("ownership_id")) or None,
                    provenance="forward_evidence",
                )
            )
    except Exception:
        pass

    return index


def _join_candidate(
    *,
    row: dict[str, Any],
    index: _LineageIndex,
) -> tuple[AnalyticsJoinMethod, AnalyticsLineageCandidate | None, list[AnalyticsLineageCandidate]]:
    content_id = _safe_text(row.get("content_id"))
    upload_id = _safe_text(row.get("upload_id") or row.get("video_id"))
    run_id = _safe_text(row.get("run_id"))
    ownership_id = _safe_text(row.get("ownership_id"))

    if content_id:
        matches = list(index.by_content_id.get(content_id, []))
        if len(matches) == 1:
            return AnalyticsJoinMethod.BY_CONTENT_ID, matches[0], matches
        if len(matches) > 1:
            return AnalyticsJoinMethod.AMBIGUOUS, None, matches

    if upload_id:
        matches = list(index.by_upload_id.get(upload_id, []))
        if len(matches) == 1:
            return AnalyticsJoinMethod.BY_UPLOAD_ID, matches[0], matches
        if len(matches) > 1:
            return AnalyticsJoinMethod.AMBIGUOUS, None, matches

    if run_id:
        matches = list(index.by_run_id.get(run_id, []))
        if len(matches) == 1:
            return AnalyticsJoinMethod.BY_RUN_ID, matches[0], matches
        if len(matches) > 1:
            return AnalyticsJoinMethod.AMBIGUOUS, None, matches

    if ownership_id:
        matches = list(index.by_ownership_id.get(ownership_id, []))
        if len(matches) == 1:
            return AnalyticsJoinMethod.BY_OWNERSHIP_LINKAGE, matches[0], matches
        if len(matches) > 1:
            return AnalyticsJoinMethod.AMBIGUOUS, None, matches

    return AnalyticsJoinMethod.UNRESOLVED, None, []


def _canonical_source_rows(
    *,
    channel_performance_path: Path,
    analytics_feedback_path: Path,
    limit: int,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    cp_rows, cp_malformed = _load_jsonl_rows(channel_performance_path)
    af_rows, af_malformed = _load_jsonl_rows(analytics_feedback_path)

    if limit > 0:
        cp_rows = cp_rows[-limit:]
        af_rows = af_rows[-limit:]

    source_rows: list[dict[str, Any]] = []
    for i, row in enumerate(cp_rows, start=1):
        payload = dict(row)
        payload["__source_type"] = "channel_performance"
        payload["__source_cursor"] = f"cp:{i}"
        source_rows.append(payload)

    for i, row in enumerate(af_rows, start=1):
        payload = dict(row)
        payload["__source_type"] = "analytics_feedback"
        payload["__source_cursor"] = f"af:{i}"
        payload.setdefault("upload_id", payload.get("video_id"))
        source_rows.append(payload)

    return source_rows, {"channel_performance": cp_malformed, "analytics_feedback": af_malformed}


def _build_analytics_record_id(
    *,
    source_type: str,
    source_cursor: str,
    snapshot_time: str,
    content_id: str | None,
    run_id: str | None,
    upload_id: str | None,
    channel_id: str | None,
) -> str:
    parts = [
        source_type,
        source_cursor,
        snapshot_time,
        _safe_text(content_id),
        _safe_text(run_id),
        _safe_text(upload_id),
        _safe_text(channel_id),
    ]
    return "aej_" + _sha("|".join(parts))[:24]


def compute_analytics_record_id(
    *,
    source_type: str,
    source_cursor: str,
    snapshot_time: str,
    content_id: str | None,
    run_id: str | None,
    upload_id: str | None,
    channel_id: str | None,
) -> str:
    return _build_analytics_record_id(
        source_type=source_type,
        source_cursor=source_cursor,
        snapshot_time=snapshot_time,
        content_id=content_id,
        run_id=run_id,
        upload_id=upload_id,
        channel_id=channel_id,
    )


def build_pipeline_analytics_evidence_row(
    *,
    source_cursor: str,
    content_id: str,
    run_id: str,
    upload_id: str | None,
    channel_id: str | None,
    snapshot_time: str,
    metrics_version: str,
    performance_snapshot: dict[str, Any] | None,
    youtube_analytics: dict[str, Any] | None,
) -> dict[str, Any]:
    source_type = "pipeline_snapshot"
    merged_source = {
        **dict(performance_snapshot or {}),
        **dict(youtube_analytics or {}),
    }
    resolved_content_id = _safe_text(content_id) or None
    resolved_run_id = _safe_text(run_id) or None
    resolved_upload_id = _safe_text(upload_id) or None
    resolved_channel_id = _safe_text(channel_id) or None
    resolved_snapshot_time = _parse_iso_or_now(snapshot_time)

    analytics_record_id = compute_analytics_record_id(
        source_type=source_type,
        source_cursor=source_cursor,
        snapshot_time=resolved_snapshot_time,
        content_id=resolved_content_id,
        run_id=resolved_run_id,
        upload_id=resolved_upload_id,
        channel_id=resolved_channel_id,
    )

    return AnalyticsEvidenceRecord(
        schema_version=ANALYTICS_EVIDENCE_JOIN_SCHEMA_VERSION,
        analytics_record_id=analytics_record_id,
        source_type=source_type,
        join_method=AnalyticsJoinMethod.BY_CONTENT_ID.value,
        content_id=resolved_content_id,
        run_id=resolved_run_id,
        upload_id=resolved_upload_id,
        channel_id=resolved_channel_id,
        snapshot_time=resolved_snapshot_time,
        metrics_version=_safe_text(metrics_version) or "unknown",
        provenance={
            "source_cursor": _safe_text(source_cursor) or "pipeline",
            "lineage_candidate_count": 1,
            "lineage_provenance": "pipeline_runtime",
        },
        metrics=_extract_metrics(merged_source),
        advisory_only=True,
        pipeline_output_changed=False,
        created_at=_now_iso(),
    ).to_dict()


def validate_analytics_evidence_row(row: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ValueError("invalid_payload")

    required = [
        "schema_version",
        "analytics_record_id",
        "source_type",
        "join_method",
        "content_id",
        "run_id",
        "upload_id",
        "channel_id",
        "snapshot_time",
        "metrics_version",
        "provenance",
        "metrics",
        "advisory_only",
        "pipeline_output_changed",
        "created_at",
    ]
    for key in required:
        if key not in row:
            raise ValueError(f"missing_field:{key}")

    if _safe_text(row.get("schema_version")) != ANALYTICS_EVIDENCE_JOIN_SCHEMA_VERSION:
        raise ValueError("invalid_field:schema_version")
    if not _safe_text(row.get("analytics_record_id")):
        raise ValueError("missing_field:analytics_record_id")

    AnalyticsJoinMethod(_safe_text(row.get("join_method")))

    if not isinstance(row.get("provenance"), dict):
        raise ValueError("invalid_field:provenance")
    if not isinstance(row.get("metrics"), dict):
        raise ValueError("invalid_field:metrics")

    for metric_name, metric_payload in dict(row.get("metrics") or {}).items():
        if not isinstance(metric_payload, dict):
            raise ValueError(f"invalid_field:metrics.{metric_name}")
        MetricAvailability(_safe_text(metric_payload.get("state")))

    snapshot_time = _safe_text(row.get("snapshot_time"))
    created_at = _safe_text(row.get("created_at"))
    try:
        datetime.fromisoformat(snapshot_time.replace("Z", "+00:00"))
    except Exception as exc:
        raise ValueError("invalid_field:snapshot_time") from exc

    try:
        datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except Exception as exc:
        raise ValueError("invalid_field:created_at") from exc

    if not bool(row.get("advisory_only")):
        raise ValueError("invalid_field:advisory_only")
    if bool(row.get("pipeline_output_changed")):
        raise ValueError("invalid_field:pipeline_output_changed")

    normalized = dict(row)
    normalized["content_id"] = _safe_text(row.get("content_id")) or None
    normalized["run_id"] = _safe_text(row.get("run_id")) or None
    normalized["upload_id"] = _safe_text(row.get("upload_id")) or None
    normalized["channel_id"] = _safe_text(row.get("channel_id")) or None
    normalized["source_type"] = _safe_text(row.get("source_type"))
    normalized["join_method"] = _safe_text(row.get("join_method"))
    normalized["snapshot_time"] = snapshot_time
    normalized["metrics_version"] = _safe_text(row.get("metrics_version")) or "unknown"
    normalized["advisory_only"] = bool(row.get("advisory_only"))
    normalized["pipeline_output_changed"] = bool(row.get("pipeline_output_changed"))
    normalized["created_at"] = created_at
    return normalized


def load_analytics_evidence_rows(
    *,
    input_path: Path | str = DEFAULT_ANALYTICS_EVIDENCE_JOIN_PATH,
    limit: int = 0,
) -> tuple[list[dict[str, Any]], int, list[str]]:
    path = Path(input_path)
    if not path.exists():
        return [], 0, []

    rows: list[dict[str, Any]] = []
    malformed = 0
    errors: list[str] = []

    for idx, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
            rows.append(validate_analytics_evidence_row(payload))
        except Exception as exc:
            malformed += 1
            errors.append(f"line={idx}:{exc}")

    if limit > 0:
        rows = rows[-limit:]
    return rows, malformed, errors


class AnalyticsEvidenceJoinStore:
    def __init__(self, *, output_path: Path | str = DEFAULT_ANALYTICS_EVIDENCE_JOIN_PATH):
        self.output_path = Path(output_path)
        self._known_ids: set[str] | None = None

    def _ensure_known_ids(self) -> set[str]:
        if self._known_ids is not None:
            return self._known_ids
        rows, _malformed, _errors = load_analytics_evidence_rows(input_path=self.output_path)
        self._known_ids = {_safe_text(row.get("analytics_record_id")) for row in rows if _safe_text(row.get("analytics_record_id"))}
        return self._known_ids

    def append(self, row: dict[str, Any]) -> AnalyticsEvidenceAppendResult:
        payload = validate_analytics_evidence_row(row)
        known = self._ensure_known_ids()
        record_id = _safe_text(payload.get("analytics_record_id"))
        if record_id in known:
            return AnalyticsEvidenceAppendResult(appended=False, duplicate=True, reason="duplicate_analytics_record_id")

        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        blob = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
        fd = os.open(self.output_path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
        try:
            os.write(fd, blob.encode("utf-8"))
        finally:
            os.close(fd)

        known.add(record_id)
        return AnalyticsEvidenceAppendResult(appended=True, duplicate=False, reason="appended")


class AnalyticsEvidenceJoinRecorder:
    def __init__(self, *, output_path: Path | str | None = None):
        self.store = AnalyticsEvidenceJoinStore(
            output_path=output_path or os.getenv("ANALYTICS_EVIDENCE_JOIN_PATH", str(DEFAULT_ANALYTICS_EVIDENCE_JOIN_PATH))
        )

    def append_joined_record(self, *, row: dict[str, Any]) -> AnalyticsEvidenceAppendResult:
        return self.store.append(row)


@dataclass(frozen=True)
class AnalyticsJoinBuildResult:
    joined_records: list[dict[str, Any]]
    unresolved_rows: list[dict[str, Any]]
    ambiguous_rows: list[dict[str, Any]]
    source_inventory: dict[str, Any]
    malformed_counts: dict[str, int]


def build_analytics_evidence_join_rows(
    *,
    channel_performance_path: Path | str = DEFAULT_CHANNEL_PERFORMANCE_PATH,
    analytics_feedback_path: Path | str = DEFAULT_ANALYTICS_FEEDBACK_PATH,
    runtime_evidence_dir: Path | str = DEFAULT_RUNTIME_EVIDENCE_DIR,
    ownership_dir: Path | str = DEFAULT_OWNERSHIP_DIR,
    limit: int = 0,
) -> AnalyticsJoinBuildResult:
    cp_path = Path(channel_performance_path)
    af_path = Path(analytics_feedback_path)
    runtime_dir = Path(runtime_evidence_dir)
    own_dir = Path(ownership_dir)

    source_rows, malformed_counts = _canonical_source_rows(
        channel_performance_path=cp_path,
        analytics_feedback_path=af_path,
        limit=limit,
    )
    runtime_rows, runtime_malformed = _load_runtime_rows(runtime_dir, limit=limit)
    ownership_rows, ownership_malformed = _load_ownership_rows(own_dir, limit=limit)

    malformed_counts = dict(malformed_counts)
    malformed_counts["runtime_evidence"] = runtime_malformed
    malformed_counts["content_ownership"] = ownership_malformed

    index = _build_lineage_index(runtime_rows=runtime_rows, ownership_rows=ownership_rows)

    joined_records: list[dict[str, Any]] = []
    unresolved_rows: list[dict[str, Any]] = []
    ambiguous_rows: list[dict[str, Any]] = []

    for row in source_rows:
        join_method, candidate, matches = _join_candidate(row=row, index=index)
        source_type = _safe_text(row.get("__source_type")) or "unknown_source"
        source_cursor = _safe_text(row.get("__source_cursor")) or "unknown_cursor"

        source_content_id = _safe_text(row.get("content_id")) or None
        source_run_id = _safe_text(row.get("run_id")) or None
        source_upload_id = _safe_text(row.get("upload_id") or row.get("video_id")) or None
        source_channel_id = _safe_text(row.get("channel_id")) or None

        if join_method == AnalyticsJoinMethod.AMBIGUOUS:
            ambiguous_rows.append(
                {
                    "source_type": source_type,
                    "source_cursor": source_cursor,
                    "match_count": len(matches),
                    "content_id": source_content_id,
                    "run_id": source_run_id,
                    "upload_id": source_upload_id,
                }
            )
            resolved_content_id = source_content_id
            resolved_run_id = source_run_id
            resolved_upload_id = source_upload_id
            resolved_channel_id = source_channel_id
        elif join_method == AnalyticsJoinMethod.UNRESOLVED:
            unresolved_rows.append(
                {
                    "source_type": source_type,
                    "source_cursor": source_cursor,
                    "content_id": source_content_id,
                    "run_id": source_run_id,
                    "upload_id": source_upload_id,
                }
            )
            resolved_content_id = source_content_id
            resolved_run_id = source_run_id
            resolved_upload_id = source_upload_id
            resolved_channel_id = source_channel_id
        else:
            resolved_content_id = source_content_id or (candidate.content_id if candidate else None)
            resolved_run_id = source_run_id or (candidate.run_id if candidate else None)
            resolved_upload_id = source_upload_id or (candidate.upload_id if candidate else None)
            resolved_channel_id = source_channel_id or (candidate.channel_id if candidate else None)

        snapshot_time = _parse_iso_or_now(
            row.get("snapshot_time")
            or row.get("recorded_at")
            or row.get("created_at")
            or row.get("upload_timestamp")
        )
        metrics_version = _safe_text(row.get("performance_schema_version") or row.get("schema_version") or "unknown") or "unknown"

        analytics_record_id = _build_analytics_record_id(
            source_type=source_type,
            source_cursor=source_cursor,
            snapshot_time=snapshot_time,
            content_id=resolved_content_id,
            run_id=resolved_run_id,
            upload_id=resolved_upload_id,
            channel_id=resolved_channel_id,
        )

        joined_records.append(
            AnalyticsEvidenceRecord(
                schema_version=ANALYTICS_EVIDENCE_JOIN_SCHEMA_VERSION,
                analytics_record_id=analytics_record_id,
                source_type=source_type,
                join_method=join_method.value,
                content_id=resolved_content_id,
                run_id=resolved_run_id,
                upload_id=resolved_upload_id,
                channel_id=resolved_channel_id,
                snapshot_time=snapshot_time,
                metrics_version=metrics_version,
                provenance={
                    "source_cursor": source_cursor,
                    "lineage_candidate_count": len(matches),
                    "lineage_provenance": candidate.provenance if candidate else None,
                },
                metrics=_extract_metrics(row),
                advisory_only=True,
                pipeline_output_changed=False,
                created_at=_now_iso(),
            ).to_dict()
        )

    inventory = build_analytics_source_inventory(
        channel_performance_path=cp_path,
        analytics_feedback_path=af_path,
        runtime_evidence_dir=runtime_dir,
        ownership_dir=own_dir,
        limit=limit,
    )

    return AnalyticsJoinBuildResult(
        joined_records=joined_records,
        unresolved_rows=unresolved_rows,
        ambiguous_rows=ambiguous_rows,
        source_inventory=inventory,
        malformed_counts=malformed_counts,
    )


def replay_analytics_evidence_join(
    *,
    rows: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], AnalyticsEvidenceReplayDiagnostics]:
    state: dict[str, dict[str, Any]] = {}
    errors: list[str] = []

    for row in rows:
        try:
            payload = validate_analytics_evidence_row(row)
            state[_safe_text(payload.get("analytics_record_id"))] = payload
        except Exception as exc:
            errors.append(str(exc))

    ordered = dict(sorted(state.items(), key=lambda item: (_safe_text(item[1].get("snapshot_time")), item[0])))
    return ordered, AnalyticsEvidenceReplayDiagnostics(malformed_rows=0, replay_errors=errors)


def compute_analytics_join_coverage(
    *,
    joined_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    total = len(joined_rows)
    joined = sum(1 for row in joined_rows if _safe_text(row.get("join_method")) in {
        AnalyticsJoinMethod.BY_CONTENT_ID.value,
        AnalyticsJoinMethod.BY_UPLOAD_ID.value,
        AnalyticsJoinMethod.BY_RUN_ID.value,
        AnalyticsJoinMethod.BY_OWNERSHIP_LINKAGE.value,
    })

    upload_linkage = sum(1 for row in joined_rows if _safe_text(row.get("upload_id")))
    ownership_linkage = sum(1 for row in joined_rows if _safe_text(row.get("join_method")) == AnalyticsJoinMethod.BY_OWNERSHIP_LINKAGE.value)
    unresolved = sum(1 for row in joined_rows if _safe_text(row.get("join_method")) == AnalyticsJoinMethod.UNRESOLVED.value)
    ambiguous = sum(1 for row in joined_rows if _safe_text(row.get("join_method")) == AnalyticsJoinMethod.AMBIGUOUS.value)
    orphan = sum(
        1
        for row in joined_rows
        if not _safe_text(row.get("content_id")) and not _safe_text(row.get("run_id")) and not _safe_text(row.get("upload_id"))
    )

    denom = max(1, total)
    return {
        "total_analytics_rows": total,
        "analytics_join_rate": round(100.0 * joined / denom, 2),
        "upload_linkage_rate": round(100.0 * upload_linkage / denom, 2),
        "ownership_linkage_rate": round(100.0 * ownership_linkage / denom, 2),
        "unresolved_analytics_rate": round(100.0 * unresolved / denom, 2),
        "orphan_analytics_rate": round(100.0 * orphan / denom, 2),
        "ambiguous_join_rate": round(100.0 * ambiguous / denom, 2),
        "joined_count": joined,
        "upload_linkage_count": upload_linkage,
        "ownership_linkage_count": ownership_linkage,
        "unresolved_count": unresolved,
        "orphan_count": orphan,
        "ambiguous_count": ambiguous,
        "advisory_only": True,
        "pipeline_output_changed": False,
    }


def estimate_cqga_impact(
    *,
    coverage: dict[str, Any],
) -> dict[str, Any]:
    join_rate = float(coverage.get("analytics_join_rate") or 0.0)
    upload_rate = float(coverage.get("upload_linkage_rate") or 0.0)

    hook = round(min(25.0, join_rate * 0.20), 2)
    retention = round(min(30.0, join_rate * 0.25), 2)
    ctr = round(min(30.0, upload_rate * 0.20), 2)
    root_cause = round(min(35.0, (join_rate * 0.20) + (upload_rate * 0.10)), 2)
    recommendation = round(min(35.0, (join_rate * 0.18) + (upload_rate * 0.12)), 2)

    return {
        "method": "coverage_weighted_estimate",
        "advisory_only": True,
        "pipeline_output_changed": False,
        "hook_validation_estimated_lift_pct": hook,
        "retention_analysis_estimated_lift_pct": retention,
        "ctr_reasoning_estimated_lift_pct": ctr,
        "root_cause_confidence_estimated_lift_pct": root_cause,
        "recommendation_confidence_estimated_lift_pct": recommendation,
        "inputs": {
            "analytics_join_rate": join_rate,
            "upload_linkage_rate": upload_rate,
        },
    }


def run_analytics_evidence_join_dry_run(
    *,
    output_path: Path | str,
    channel_performance_path: Path | str = DEFAULT_CHANNEL_PERFORMANCE_PATH,
    analytics_feedback_path: Path | str = DEFAULT_ANALYTICS_FEEDBACK_PATH,
    runtime_evidence_dir: Path | str = DEFAULT_RUNTIME_EVIDENCE_DIR,
    ownership_dir: Path | str = DEFAULT_OWNERSHIP_DIR,
    limit: int = 0,
) -> dict[str, Any]:
    result = build_analytics_evidence_join_rows(
        channel_performance_path=channel_performance_path,
        analytics_feedback_path=analytics_feedback_path,
        runtime_evidence_dir=runtime_evidence_dir,
        ownership_dir=ownership_dir,
        limit=limit,
    )

    replay_state, diagnostics = replay_analytics_evidence_join(rows=result.joined_records)
    coverage = compute_analytics_join_coverage(joined_rows=list(replay_state.values()))
    cqga_impact = estimate_cqga_impact(coverage=coverage)

    report = {
        "generated_at": _now_iso(),
        "source_inventory": result.source_inventory,
        "malformed_counts": result.malformed_counts,
        "counts": {
            "total_source_rows": len(result.joined_records),
            "unresolved": len(result.unresolved_rows),
            "ambiguous": len(result.ambiguous_rows),
        },
        "coverage": coverage,
        "cqga_impact_estimate": cqga_impact,
        "replay_diagnostics": {
            "malformed_rows": diagnostics.malformed_rows,
            "replay_errors": diagnostics.replay_errors,
            "replay_state_size": len(replay_state),
            "deterministic_ordering": True,
        },
        "unresolved_rows": result.unresolved_rows,
        "ambiguous_rows": result.ambiguous_rows,
        "advisory_only": True,
        "pipeline_output_changed": False,
    }

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2), encoding="utf-8")
    return report
