from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .forward_evidence_capture import reconstruct_forward_sessions
from .planning_blueprint_lineage_evidence import load_planning_lineage_rows
from .script_lineage_evidence import load_script_lineage_rows


PHASE4C_SCHEMA_VERSION = "v1"
PHASE4B_ASSESSMENT_SUMMARY_PATH = Path("artifacts/latest/project002_sprint1e_phase4b_studio_export_learning/assessment_summary.json")
PHASE4B_CANONICAL_STORE_PATH = Path("logs/canonical_content_analytics.jsonl")
PHASE4B_SOURCE_PATH = Path("logs/channel_performance.jsonl")
PHASE4C_DEFAULT_OUTPUT_DIR = Path("artifacts/latest/project002_sprint1e_phase4c_unresolved_analytics_recovery")
UNRESOLVED_INPUT_MANIFEST_PATH = Path("logs/unresolved_analytics_input_manifest.jsonl")
UNRESOLVED_AUDIT_RESULTS_PATH = Path("logs/unresolved_analytics_audit_results.jsonl")
UNRESOLVED_RECOVERY_EVIDENCE_PATH = Path("logs/unresolved_analytics_recovery_evidence.jsonl")
UNRESOLVED_DUPLICATE_DISPOSITION_PATH = Path("logs/unresolved_analytics_duplicate_disposition.jsonl")

KNOWN_METRIC_FIELDS = (
    "impressions",
    "click_through_rate",
    "average_view_duration_seconds",
    "average_view_percentage",
    "watch_time_hours",
    "views",
    "likes",
    "comments",
    "shares",
    "subscribers_gained",
)


class TaxonomyCategory(str, Enum):
    MISSING_VIDEO_ID = "MISSING_VIDEO_ID"
    VIDEO_ID_NOT_IN_UPLOAD_MAP = "VIDEO_ID_NOT_IN_UPLOAD_MAP"
    MISSING_UPLOAD_ID = "MISSING_UPLOAD_ID"
    UPLOAD_ID_NOT_IN_EVIDENCE = "UPLOAD_ID_NOT_IN_EVIDENCE"
    MISSING_CONTENT_ID = "MISSING_CONTENT_ID"
    CONTENT_ID_NOT_IN_OWNERSHIP = "CONTENT_ID_NOT_IN_OWNERSHIP"
    MISSING_RUN_ID = "MISSING_RUN_ID"
    RUN_ID_NOT_IN_LINEAGE = "RUN_ID_NOT_IN_LINEAGE"
    MISSING_OWNERSHIP_RECORD = "MISSING_OWNERSHIP_RECORD"
    LEGACY_UPLOAD = "LEGACY_UPLOAD"
    LEGACY_ANALYTICS_ROW = "LEGACY_ANALYTICS_ROW"
    DELETED_VIDEO = "DELETED_VIDEO"
    PRIVATE_OR_UNLISTED_VIDEO = "PRIVATE_OR_UNLISTED_VIDEO"
    CHANNEL_MISMATCH = "CHANNEL_MISMATCH"
    PROVIDER_MISMATCH = "PROVIDER_MISMATCH"
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    DUPLICATE_SNAPSHOT = "DUPLICATE_SNAPSHOT"
    DUPLICATE_SOURCE_ROW = "DUPLICATE_SOURCE_ROW"
    AMBIGUOUS_IDENTITY = "AMBIGUOUS_IDENTITY"
    UNSUPPORTED_AGGREGATE_ROW = "UNSUPPORTED_AGGREGATE_ROW"
    UNSUPPORTED_METRIC_SHAPE = "UNSUPPORTED_METRIC_SHAPE"
    MALFORMED_ROW = "MALFORMED_ROW"
    INSUFFICIENT_IDENTITY_EVIDENCE = "INSUFFICIENT_IDENTITY_EVIDENCE"
    UNKNOWN = "UNKNOWN"


class RecoverabilityState(str, Enum):
    RECOVERABLE_NOW = "RECOVERABLE_NOW"
    RECOVERABLE_WITH_STUDIO_EXPORT = "RECOVERABLE_WITH_STUDIO_EXPORT"
    RECOVERABLE_WITH_OFFICIAL_API = "RECOVERABLE_WITH_OFFICIAL_API"
    RECOVERABLE_WITH_FUTURE_FORWARD_EVIDENCE = "RECOVERABLE_WITH_FUTURE_FORWARD_EVIDENCE"
    PERMANENTLY_UNRECOVERABLE = "PERMANENTLY_UNRECOVERABLE"
    AMBIGUOUS = "AMBIGUOUS"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"


class FinalDisposition(str, Enum):
    RECOVERED = "RECOVERED"
    STILL_UNRESOLVED = "STILL_UNRESOLVED"
    PERMANENTLY_UNRECOVERABLE = "PERMANENTLY_UNRECOVERABLE"
    AMBIGUOUS = "AMBIGUOUS"
    INVALID = "INVALID"


class RecoveryMethod(str, Enum):
    VIDEO_ID = "video_id"
    UPLOAD_ID = "upload_id"
    CONTENT_ID = "content_id"
    RUN_ID = "run_id"
    OWNERSHIP = "ownership"
    FORWARD_EVIDENCE = "forward_evidence"
    LINEAGE_HASH = "lineage_hash"


class PreventionStatus(str, Enum):
    PREVENTED = "PREVENTED"
    PARTIALLY_PREVENTED = "PARTIALLY_PREVENTED"
    NOT_PREVENTED = "NOT_PREVENTED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class BaselineState:
    repository_root: str
    source_file_hash: str
    imported_rows: int
    linked_rows: int
    unresolved_rows: int
    ambiguous_rows: int
    invalid_rows: int


@dataclass(frozen=True)
class EvidenceReference:
    source_type: str
    path: str | None
    identity_key: str
    identity_value: str
    proof_hash: str
    payload: dict[str, Any]


@dataclass
class EvidenceTarget:
    target_key: str
    content_id: str | None
    run_id: str | None
    channel_id: str | None
    youtube_video_id: str | None
    upload_id: str | None
    proof_records: list[EvidenceReference] = field(default_factory=list)

    def to_target_dict(self) -> dict[str, Any]:
        return {
            "target_key": self.target_key,
            "content_id": self.content_id,
            "run_id": self.run_id,
            "channel_id": self.channel_id,
            "youtube_video_id": self.youtube_video_id,
            "upload_id": self.upload_id,
        }


@dataclass
class EvidenceIndexes:
    targets: dict[str, EvidenceTarget] = field(default_factory=dict)
    by_video_id: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    by_upload_id: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    by_content_id: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    by_run_id: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    by_ownership_id: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    by_forward_session_id: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    by_script_evidence_id: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    by_blueprint_hash: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))

    def add_target(
        self,
        *,
        content_id: str | None,
        run_id: str | None,
        channel_id: str | None,
        youtube_video_id: str | None,
        upload_id: str | None,
        proof: EvidenceReference,
        forward_session_id: str | None = None,
        script_evidence_id: str | None = None,
        blueprint_hash: str | None = None,
        ownership_id: str | None = None,
    ) -> None:
        key = _target_key(content_id=content_id, run_id=run_id, channel_id=channel_id)
        target = self.targets.get(key)
        if target is None:
            target = EvidenceTarget(
                target_key=key,
                content_id=content_id,
                run_id=run_id,
                channel_id=channel_id,
                youtube_video_id=youtube_video_id,
                upload_id=upload_id,
            )
            self.targets[key] = target
        else:
            target.youtube_video_id = target.youtube_video_id or youtube_video_id
            target.upload_id = target.upload_id or upload_id

        if not any(existing.proof_hash == proof.proof_hash for existing in target.proof_records):
            target.proof_records.append(proof)

        _add_index(self.by_content_id, content_id, key)
        _add_index(self.by_run_id, run_id, key)
        _add_index(self.by_video_id, youtube_video_id, key)
        _add_index(self.by_upload_id, upload_id, key)
        _add_index(self.by_ownership_id, ownership_id, key)
        _add_index(self.by_forward_session_id, forward_session_id, key)
        _add_index(self.by_script_evidence_id, script_evidence_id, key)
        _add_index(self.by_blueprint_hash, blueprint_hash, key)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _sha_text(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def _json_hash(payload: Any) -> str:
    return _sha_text(_stable_json(payload))


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> tuple[list[dict[str, Any]], int]:
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


def _add_index(mapping: dict[str, list[str]], key: str | None, target_key: str) -> None:
    text = _safe_text(key)
    if not text:
        return
    bucket = mapping.setdefault(text, [])
    if target_key not in bucket:
        bucket.append(target_key)


def _target_key(*, content_id: str | None, run_id: str | None, channel_id: str | None) -> str:
    return "tgt_" + _sha_text("|".join([_safe_text(content_id), _safe_text(run_id), _safe_text(channel_id)]))[:24]


def _sanitize_source_row(row: dict[str, Any]) -> dict[str, Any]:
    safe = dict(row)
    for key in ["youtube_token", "oauth_token", "refresh_token", "access_token", "client_secret", "password"]:
        if key in safe:
            del safe[key]
    return safe


def load_phase4b_baseline(
    *,
    repository_root: Path,
    assessment_summary_path: Path | str = PHASE4B_ASSESSMENT_SUMMARY_PATH,
) -> BaselineState:
    summary = _load_json(repository_root / Path(assessment_summary_path))
    coverage = dict(summary.get("coverage") or {})
    imports = list(summary.get("imports") or [])
    local_import = next((item for item in imports if _safe_text(item.get("provider")) == "ExistingLocalAnalyticsProvider"), None)
    if not local_import:
        raise ValueError("missing_phase4b_local_import")
    source_hash = _safe_text(local_import.get("source_file_hash"))
    if not source_hash:
        raise ValueError("missing_phase4b_source_hash")
    return BaselineState(
        repository_root=str(repository_root),
        source_file_hash=source_hash,
        imported_rows=int(summary.get("canonical_rows") or 0),
        linked_rows=int(coverage.get("content_linked_rows") or 0),
        unresolved_rows=int(coverage.get("unresolved_rows") or 0),
        ambiguous_rows=int(coverage.get("ambiguous_rows") or 0),
        invalid_rows=int(coverage.get("invalid_rows") or 0),
    )


def reconstruct_authoritative_source_rows(
    *,
    repository_root: Path,
    baseline: BaselineState,
    source_path: Path | str = PHASE4B_SOURCE_PATH,
) -> list[dict[str, Any]]:
    path = repository_root / Path(source_path)
    lines = path.read_text(encoding="utf-8").splitlines(True)
    if len(lines) < baseline.imported_rows:
        raise ValueError("insufficient_source_rows")
    frozen_bytes = "".join(lines[: baseline.imported_rows])
    frozen_hash = hashlib.sha256(frozen_bytes.encode("utf-8")).hexdigest()
    if frozen_hash != baseline.source_file_hash:
        raise ValueError("phase4b_source_hash_mismatch")

    rows: list[dict[str, Any]] = []
    for index, raw in enumerate(lines[: baseline.imported_rows], start=1):
        line = raw.strip()
        if not line:
            raise ValueError(f"blank_frozen_line:{index}")
        decoded = json.loads(line)
        if not isinstance(decoded, dict):
            raise ValueError(f"invalid_frozen_line:{index}")
        rows.append(decoded)
    return rows


def load_authoritative_phase4b_canonical_rows(
    *,
    repository_root: Path,
    baseline: BaselineState,
    canonical_store_path: Path | str = PHASE4B_CANONICAL_STORE_PATH,
) -> list[dict[str, Any]]:
    rows, _malformed = _load_jsonl(repository_root / Path(canonical_store_path))
    filtered = [
        row
        for row in rows
        if _safe_text(row.get("provider")) == "ExistingLocalAnalyticsProvider"
        and _safe_text(row.get("source_file_hash")) == baseline.source_file_hash
    ]
    filtered = sorted(filtered, key=lambda item: int(item.get("source_row_number") or 0))
    if len(filtered) != baseline.imported_rows:
        raise ValueError("phase4b_canonical_row_count_mismatch")
    return filtered


def build_unresolved_input_manifest(
    *,
    source_rows: list[dict[str, Any]],
    canonical_rows: list[dict[str, Any]],
    baseline: BaselineState,
) -> list[dict[str, Any]]:
    manifest: list[dict[str, Any]] = []
    unresolved_rows = [row for row in canonical_rows if _safe_text(((row.get("provenance") or {}).get("join_outcome"))) == "UNRESOLVED"]
    source_by_number = {index: row for index, row in enumerate(source_rows, start=1)}

    for canonical_row in unresolved_rows:
        source_row_number = int(canonical_row.get("source_row_number") or 0)
        source_row = dict(source_by_number.get(source_row_number) or {})
        if not source_row:
            raise ValueError(f"missing_source_row:{source_row_number}")
        safe_row = _sanitize_source_row(source_row)
        row_hash = _json_hash(safe_row)
        unresolved_record_id = "uar_" + _sha_text(
            "|".join(
                [
                    baseline.source_file_hash,
                    str(source_row_number),
                    _safe_text(canonical_row.get("analytics_record_id")),
                    row_hash,
                ]
            )
        )[:24]
        join_details = dict((canonical_row.get("provenance") or {}).get("join_details") or {})
        manifest.append(
            {
                "schema_version": PHASE4C_SCHEMA_VERSION,
                "unresolved_record_id": unresolved_record_id,
                "canonical_analytics_record_id": canonical_row.get("analytics_record_id"),
                "provider": canonical_row.get("provider"),
                "source_file_hash": baseline.source_file_hash,
                "source_row_number": source_row_number,
                "channel_id": _safe_text(source_row.get("channel_id") or canonical_row.get("canonical_channel_id")) or None,
                "youtube_video_id": _safe_text(source_row.get("video_id") or canonical_row.get("youtube_video_id")) or None,
                "content_id": _safe_text(source_row.get("content_id") or canonical_row.get("content_id")) or None,
                "upload_id": _safe_text(source_row.get("upload_id")) or None,
                "run_id": _safe_text(source_row.get("run_id")) or None,
                "forward_session_id": _safe_text(source_row.get("forward_session_id")) or None,
                "script_lineage_evidence_id": _safe_text(source_row.get("script_lineage_evidence_id")) or None,
                "planning_blueprint_hash": _safe_text(source_row.get("planning_blueprint_hash")) or None,
                "snapshot_start": canonical_row.get("snapshot_start"),
                "snapshot_end": canonical_row.get("snapshot_end"),
                "metric_fields_present": sorted([key for key in KNOWN_METRIC_FIELDS if key in source_row]),
                "original_join_status": (canonical_row.get("provenance") or {}).get("join_outcome"),
                "original_join_reason": join_details.get("reason") or "deterministic_keys_missing",
                "row_hash": row_hash,
                "content_type": canonical_row.get("content_type"),
                "source_row": safe_row,
                "advisory_only": True,
                "pipeline_output_changed": False,
            }
        )
    manifest.sort(key=lambda item: (int(item.get("source_row_number") or 0), _safe_text(item.get("unresolved_record_id"))))
    if len(manifest) != baseline.unresolved_rows:
        raise ValueError("phase4b_unresolved_count_mismatch")
    return manifest


def determine_snapshot_dispositions(manifest_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    exact_row_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    identity_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in manifest_rows:
        exact_row_groups[_safe_text(row.get("row_hash"))].append(row)
        identity_key = "|".join([_safe_text(row.get("content_id")), _safe_text(row.get("youtube_video_id")), _safe_text(row.get("run_id"))])
        identity_groups[identity_key].append(row)

    dispositions: dict[str, dict[str, Any]] = {}
    for row in manifest_rows:
        record_id = _safe_text(row.get("unresolved_record_id"))
        duplicates = exact_row_groups.get(_safe_text(row.get("row_hash")), [])
        peers = identity_groups.get("|".join([_safe_text(row.get("content_id")), _safe_text(row.get("youtube_video_id")), _safe_text(row.get("run_id"))]), [])
        snapshot_duplicates = [peer for peer in peers if _safe_text(peer.get("snapshot_start")) == _safe_text(row.get("snapshot_start")) and _safe_text(peer.get("snapshot_end")) == _safe_text(row.get("snapshot_end"))]
        overlapping_snapshot = False
        later_valid_snapshot = False
        incompatible_snapshot_definition = False
        current_start = _safe_text(row.get("snapshot_start"))
        current_end = _safe_text(row.get("snapshot_end"))
        current_window = _window_type(current_start, current_end)
        for peer in peers:
            if peer is row:
                continue
            peer_start = _safe_text(peer.get("snapshot_start"))
            peer_end = _safe_text(peer.get("snapshot_end"))
            peer_window = _window_type(peer_start, peer_end)
            if current_window != peer_window:
                incompatible_snapshot_definition = True
            if _safe_text(peer.get("metric_definition_version")) and _safe_text(row.get("metric_definition_version")) and _safe_text(peer.get("metric_definition_version")) != _safe_text(row.get("metric_definition_version")):
                incompatible_snapshot_definition = True
            if current_end and peer_start and current_end < peer_start:
                later_valid_snapshot = True
            if _ranges_overlap(current_start, current_end, peer_start, peer_end) and not (current_start == peer_start and current_end == peer_end):
                overlapping_snapshot = True
        if len(duplicates) > 1:
            status = TaxonomyCategory.DUPLICATE_SOURCE_ROW.value
        elif len(snapshot_duplicates) > 1:
            status = TaxonomyCategory.DUPLICATE_SNAPSHOT.value
        else:
            status = "CONTENT_LEVEL_ROW"
        dispositions[record_id] = {
            "status": status,
            "exact_duplicate_count": len(duplicates),
            "snapshot_duplicate_count": len(snapshot_duplicates),
            "aggregate_row": _is_aggregate_manifest_row(row),
            "later_valid_snapshot": later_valid_snapshot,
            "overlapping_snapshot": overlapping_snapshot,
            "incompatible_snapshot_definition": incompatible_snapshot_definition,
        }
    return dispositions


def _window_type(snapshot_start: str | None, snapshot_end: str | None) -> str:
    start = _safe_text(snapshot_start)
    end = _safe_text(snapshot_end)
    if start and end and start == end:
        return "daily"
    if start and end:
        return "range"
    if start or end:
        return "point"
    return "unknown"


def _ranges_overlap(start_a: str, end_a: str, start_b: str, end_b: str) -> bool:
    if not start_a or not end_a or not start_b or not end_b:
        return False
    return not (end_a < start_b or end_b < start_a)


def _is_aggregate_manifest_row(row: dict[str, Any]) -> bool:
    source_row = dict(row.get("source_row") or {})
    title = _safe_text(source_row.get("title")).lower()
    if title in {"total", "toplam", "summary", "ozet", "özet", "all"}:
        return True
    if bool(source_row.get("aggregate_row")):
        return True
    return False


def _has_unsupported_metric_shape(source_row: dict[str, Any]) -> bool:
    for key in KNOWN_METRIC_FIELDS:
        if key not in source_row:
            continue
        value = source_row.get(key)
        if isinstance(value, (dict, list, tuple, set)):
            return True
    return False


def _runtime_video_ids(payload: dict[str, Any]) -> list[str]:
    values = [
        payload.get("video_id"),
        ((payload.get("upload_metadata") or {}) if isinstance(payload.get("upload_metadata"), dict) else {}).get("video_id"),
        ((payload.get("upload_result") or {}) if isinstance(payload.get("upload_result"), dict) else {}).get("video_id"),
    ]
    out: list[str] = []
    for value in values:
        text = _safe_text(value)
        if text and text not in out:
            out.append(text)
    return out


def _runtime_upload_id(payload: dict[str, Any]) -> str | None:
    values = [
        payload.get("upload_id"),
        ((payload.get("upload_metadata") or {}) if isinstance(payload.get("upload_metadata"), dict) else {}).get("upload_id"),
        ((payload.get("upload_result") or {}) if isinstance(payload.get("upload_result"), dict) else {}).get("video_id"),
    ]
    for value in values:
        text = _safe_text(value)
        if text:
            return text
    return None


def build_evidence_indexes(
    *,
    repository_root: Path,
    runtime_dir: Path = Path("output/runtime/evidence"),
    ownership_dir: Path = Path("output/state/content_ownership"),
) -> EvidenceIndexes:
    indexes = EvidenceIndexes()

    runtime_path = repository_root / runtime_dir
    for path in sorted(runtime_path.glob("*.json")):
        try:
            payload = _load_json(path)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        content_id = _safe_text(payload.get("content_id") or payload.get("generation_id")) or None
        run_id = _safe_text(payload.get("run_id")) or None
        channel_id = _safe_text(payload.get("channel")) or None
        upload_id = _runtime_upload_id(payload)
        video_ids = _runtime_video_ids(payload)
        proof = EvidenceReference(
            source_type="runtime_evidence",
            path=str(path),
            identity_key="content_id",
            identity_value=_safe_text(content_id),
            proof_hash=_json_hash(payload),
            payload={
                "content_id": content_id,
                "run_id": run_id,
                "channel_id": channel_id,
                "upload_id": upload_id,
                "video_ids": video_ids,
            },
        )
        indexes.add_target(
            content_id=content_id,
            run_id=run_id,
            channel_id=channel_id,
            youtube_video_id=video_ids[0] if video_ids else None,
            upload_id=upload_id,
            proof=proof,
        )
        target_key = _target_key(content_id=content_id, run_id=run_id, channel_id=channel_id)
        for video_id in video_ids:
            _add_index(indexes.by_video_id, video_id, target_key)
        _add_index(indexes.by_upload_id, upload_id, target_key)

    ownership_path = repository_root / ownership_dir
    for path in sorted(ownership_path.glob("*.json")):
        try:
            payload = _load_json(path)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        content_id = _safe_text(payload.get("content_id")) or None
        run_id = _safe_text(payload.get("run_id")) or None
        channel_id = _safe_text(payload.get("channel_id")) or None
        ownership_id = path.stem
        proof = EvidenceReference(
            source_type="ownership",
            path=str(path),
            identity_key="content_id",
            identity_value=_safe_text(content_id),
            proof_hash=_json_hash(payload),
            payload={
                "content_id": content_id,
                "run_id": run_id,
                "channel_id": channel_id,
                "ownership_id": ownership_id,
            },
        )
        indexes.add_target(
            content_id=content_id,
            run_id=run_id,
            channel_id=channel_id,
            youtube_video_id=None,
            upload_id=None,
            proof=proof,
            ownership_id=ownership_id,
        )

    try:
        sessions, _diagnostics = reconstruct_forward_sessions()
    except Exception:
        sessions = {}
    for session_id, payload in sorted(sessions.items()):
        latest = dict(payload.get("latest") or {})
        content_id = _safe_text(payload.get("content_id")) or None
        run_id = _safe_text(payload.get("run_id")) or None
        channel_id = _safe_text(payload.get("channel_id")) or None
        upload_id = _safe_text(latest.get("upload_id")) or None
        ownership_id = _safe_text(latest.get("ownership_id")) or None
        proof = EvidenceReference(
            source_type="forward_evidence",
            path="logs/forward_evidence_capture.jsonl",
            identity_key="session_id",
            identity_value=session_id,
            proof_hash=_json_hash({"session_id": session_id, "payload": payload}),
            payload={
                "content_id": content_id,
                "run_id": run_id,
                "channel_id": channel_id,
                "upload_id": upload_id,
                "ownership_id": ownership_id,
            },
        )
        indexes.add_target(
            content_id=content_id,
            run_id=run_id,
            channel_id=channel_id,
            youtube_video_id=upload_id,
            upload_id=upload_id,
            proof=proof,
            forward_session_id=session_id,
            ownership_id=ownership_id,
        )

    script_rows, _script_malformed, _script_errors = load_script_lineage_rows()
    for row in script_rows:
        content_id = _safe_text(row.get("content_id")) or None
        run_id = _safe_text(row.get("run_id")) or None
        channel_id = _safe_text(row.get("canonical_channel_id")) or None
        evidence_id = _safe_text(row.get("evidence_id")) or None
        proof = EvidenceReference(
            source_type="script_lineage",
            path="logs/script_lineage_evidence.jsonl",
            identity_key="evidence_id",
            identity_value=_safe_text(evidence_id),
            proof_hash=_json_hash(row),
            payload={
                "content_id": content_id,
                "run_id": run_id,
                "channel_id": channel_id,
                "evidence_id": evidence_id,
            },
        )
        indexes.add_target(
            content_id=content_id,
            run_id=run_id,
            channel_id=channel_id,
            youtube_video_id=None,
            upload_id=None,
            proof=proof,
            script_evidence_id=evidence_id,
        )

    planning_rows, _planning_malformed, _planning_errors = load_planning_lineage_rows()
    for row in planning_rows:
        content_id = _safe_text(row.get("content_id")) or None
        run_id = _safe_text(row.get("run_id")) or None
        blueprint_hash = _safe_text(row.get("blueprint_hash")) or None
        proof = EvidenceReference(
            source_type="planning_lineage",
            path="logs/planning_blueprint_lineage_evidence.jsonl",
            identity_key="blueprint_hash",
            identity_value=_safe_text(blueprint_hash),
            proof_hash=_json_hash(row),
            payload={
                "content_id": content_id,
                "run_id": run_id,
                "blueprint_hash": blueprint_hash,
            },
        )
        indexes.add_target(
            content_id=content_id,
            run_id=run_id,
            channel_id=None,
            youtube_video_id=None,
            upload_id=None,
            proof=proof,
            blueprint_hash=blueprint_hash,
        )

    return indexes


def _distinct_targets(indexes: EvidenceIndexes, target_keys: list[str]) -> list[EvidenceTarget]:
    seen: set[str] = set()
    out: list[EvidenceTarget] = []
    for key in target_keys:
        if key in seen:
            continue
        seen.add(key)
        target = indexes.targets.get(key)
        if target is not None:
            out.append(target)
    out.sort(key=lambda item: item.target_key)
    return out


def _candidate_lookup(row: dict[str, Any], indexes: EvidenceIndexes) -> list[tuple[RecoveryMethod, str, list[EvidenceTarget]]]:
    lookups: list[tuple[RecoveryMethod, str, list[EvidenceTarget]]] = []
    sources = [
        (RecoveryMethod.LINEAGE_HASH, _safe_text(row.get("script_lineage_evidence_id")), indexes.by_script_evidence_id),
        (RecoveryMethod.LINEAGE_HASH, _safe_text(row.get("planning_blueprint_hash")), indexes.by_blueprint_hash),
        (RecoveryMethod.FORWARD_EVIDENCE, _safe_text(row.get("forward_session_id")), indexes.by_forward_session_id),
        (RecoveryMethod.OWNERSHIP, _safe_text(row.get("ownership_id")), indexes.by_ownership_id),
        (RecoveryMethod.CONTENT_ID, _safe_text(row.get("content_id")), indexes.by_content_id),
        (RecoveryMethod.RUN_ID, _safe_text(row.get("run_id")), indexes.by_run_id),
        (RecoveryMethod.VIDEO_ID, _safe_text(row.get("youtube_video_id")), indexes.by_video_id),
        (RecoveryMethod.UPLOAD_ID, _safe_text(row.get("upload_id")), indexes.by_upload_id),
    ]
    for method, value, mapping in sources:
        if not value:
            continue
        lookups.append((method, value, _distinct_targets(indexes, list(mapping.get(value, [])))))
    return lookups


def _channel_conflict(row: dict[str, Any], target: EvidenceTarget) -> bool:
    row_channel = _safe_text(row.get("channel_id"))
    target_channel = _safe_text(target.channel_id)
    return bool(row_channel and target_channel and row_channel != target_channel)


def classify_unresolved_row(
    *,
    row: dict[str, Any],
    indexes: EvidenceIndexes,
    snapshot_disposition: dict[str, Any],
) -> dict[str, Any]:
    source_row = dict(row.get("source_row") or {})
    lookup_results = _candidate_lookup(row, indexes)
    ownership_matches = _distinct_targets(indexes, list(indexes.by_content_id.get(_safe_text(row.get("content_id")), []))) if _safe_text(row.get("content_id")) else []
    explicit_ownership_matches = _distinct_targets(indexes, list(indexes.by_ownership_id.get(_safe_text(row.get("ownership_id")), []))) if _safe_text(row.get("ownership_id")) else []
    if _safe_text(row.get("schema_version")) != PHASE4C_SCHEMA_VERSION:
        return _build_classification(row=row, category=TaxonomyCategory.SCHEMA_MISMATCH, secondary=[], recoverability=RecoverabilityState.INVALID, final_set=FinalDisposition.INVALID, evidence=[{"reason": "manifest_schema_version_mismatch"}], required_missing_proof=None, recovery=None)
    if _safe_text(row.get("provider")) not in {"ExistingLocalAnalyticsProvider", "StudioExportProvider", "FutureOfficialYouTubeProvider"}:
        return _build_classification(row=row, category=TaxonomyCategory.PROVIDER_MISMATCH, secondary=[], recoverability=RecoverabilityState.INVALID, final_set=FinalDisposition.INVALID, evidence=[{"reason": "unsupported_provider"}], required_missing_proof=None, recovery=None)
    if snapshot_disposition.get("status") == TaxonomyCategory.DUPLICATE_SOURCE_ROW.value:
        return _build_classification(row=row, category=TaxonomyCategory.DUPLICATE_SOURCE_ROW, secondary=[TaxonomyCategory.DUPLICATE_SNAPSHOT.value], recoverability=RecoverabilityState.INVALID, final_set=FinalDisposition.INVALID, evidence=[snapshot_disposition], required_missing_proof=None, recovery=None)
    if snapshot_disposition.get("status") == TaxonomyCategory.DUPLICATE_SNAPSHOT.value:
        return _build_classification(row=row, category=TaxonomyCategory.DUPLICATE_SNAPSHOT, secondary=[], recoverability=RecoverabilityState.UNKNOWN, final_set=FinalDisposition.STILL_UNRESOLVED, evidence=[snapshot_disposition], required_missing_proof="non-duplicate snapshot definition", recovery=None)

    if not isinstance(source_row, dict):
        return _build_classification(row=row, category=TaxonomyCategory.MALFORMED_ROW, secondary=[], recoverability=RecoverabilityState.INVALID, final_set=FinalDisposition.INVALID, evidence=[{"reason": "source_row_not_dict"}], required_missing_proof=None, recovery=None)
    if _is_aggregate_manifest_row(row):
        return _build_classification(row=row, category=TaxonomyCategory.UNSUPPORTED_AGGREGATE_ROW, secondary=[], recoverability=RecoverabilityState.INVALID, final_set=FinalDisposition.INVALID, evidence=[{"reason": "aggregate_row"}], required_missing_proof=None, recovery=None)
    if _has_unsupported_metric_shape(source_row):
        return _build_classification(row=row, category=TaxonomyCategory.UNSUPPORTED_METRIC_SHAPE, secondary=[], recoverability=RecoverabilityState.INVALID, final_set=FinalDisposition.INVALID, evidence=[{"reason": "unsupported_metric_shape"}], required_missing_proof=None, recovery=None)
    if bool(source_row.get("legacy_upload")):
        return _build_classification(row=row, category=TaxonomyCategory.LEGACY_UPLOAD, secondary=[], recoverability=RecoverabilityState.PERMANENTLY_UNRECOVERABLE, final_set=FinalDisposition.PERMANENTLY_UNRECOVERABLE, evidence=[{"reason": "legacy_upload_flag"}], required_missing_proof="retained upload identity", recovery=None)
    if bool(source_row.get("legacy_analytics_row")):
        return _build_classification(row=row, category=TaxonomyCategory.LEGACY_ANALYTICS_ROW, secondary=[], recoverability=RecoverabilityState.PERMANENTLY_UNRECOVERABLE, final_set=FinalDisposition.PERMANENTLY_UNRECOVERABLE, evidence=[{"reason": "legacy_analytics_flag"}], required_missing_proof="retained historical identity mapping", recovery=None)
    video_state = _safe_text(source_row.get("video_state")).lower()
    if video_state == "deleted":
        return _build_classification(row=row, category=TaxonomyCategory.DELETED_VIDEO, secondary=[], recoverability=RecoverabilityState.PERMANENTLY_UNRECOVERABLE, final_set=FinalDisposition.PERMANENTLY_UNRECOVERABLE, evidence=[{"reason": "explicit_deleted_video_state"}], required_missing_proof="retained deleted-video mapping", recovery=None)
    if video_state in {"private", "unlisted"}:
        return _build_classification(row=row, category=TaxonomyCategory.PRIVATE_OR_UNLISTED_VIDEO, secondary=[], recoverability=RecoverabilityState.RECOVERABLE_WITH_OFFICIAL_API, final_set=FinalDisposition.STILL_UNRESOLVED, evidence=[{"reason": f"explicit_video_state:{video_state}"}], required_missing_proof="authorized video metadata lookup", recovery=None)

    unique_recovery: dict[str, Any] | None = None
    ambiguous_methods: list[dict[str, Any]] = []
    for method, value, targets in lookup_results:
        if len(targets) == 1 and not _channel_conflict(row, targets[0]):
            unique_recovery = _build_recovery_payload(row=row, method=method, lookup_value=value, target=targets[0])
            break
        if len(targets) > 1:
            ambiguous_methods.append({
                "method": method.value,
                "lookup_value": value,
                "target_keys": [item.target_key for item in targets],
            })
        if len(targets) == 1 and _channel_conflict(row, targets[0]):
            ambiguous_methods.append({
                "method": method.value,
                "lookup_value": value,
                "target_keys": [targets[0].target_key],
                "reason": "channel_mismatch",
            })

    if unique_recovery is not None:
        category = TaxonomyCategory.CONTENT_ID_NOT_IN_OWNERSHIP
        secondary: list[str] = []
        if not _safe_text(row.get("content_id")):
            category = TaxonomyCategory.MISSING_CONTENT_ID
        elif not explicit_ownership_matches:
            category = TaxonomyCategory.MISSING_OWNERSHIP_RECORD
        elif unique_recovery["recovery_method"] == RecoveryMethod.RUN_ID.value:
            category = TaxonomyCategory.RUN_ID_NOT_IN_LINEAGE
        elif unique_recovery["recovery_method"] == RecoveryMethod.VIDEO_ID.value:
            category = TaxonomyCategory.VIDEO_ID_NOT_IN_UPLOAD_MAP
        elif unique_recovery["recovery_method"] == RecoveryMethod.UPLOAD_ID.value:
            category = TaxonomyCategory.UPLOAD_ID_NOT_IN_EVIDENCE
        if ambiguous_methods:
            secondary.extend([TaxonomyCategory.AMBIGUOUS_IDENTITY.value])
        return _build_classification(
            row=row,
            category=category,
            secondary=secondary,
            recoverability=RecoverabilityState.RECOVERABLE_NOW,
            final_set=FinalDisposition.RECOVERED,
            evidence=list(unique_recovery.get("target_proof_records") or []),
            required_missing_proof=None,
            recovery=unique_recovery,
        )

    if ambiguous_methods:
        if any(item.get("reason") == "channel_mismatch" for item in ambiguous_methods):
            return _build_classification(
                row=row,
                category=TaxonomyCategory.CHANNEL_MISMATCH,
                secondary=[TaxonomyCategory.AMBIGUOUS_IDENTITY.value],
                recoverability=RecoverabilityState.AMBIGUOUS,
                final_set=FinalDisposition.AMBIGUOUS,
                evidence=ambiguous_methods,
                required_missing_proof="single target with matching channel identity",
                recovery=None,
            )
        return _build_classification(
            row=row,
            category=TaxonomyCategory.AMBIGUOUS_IDENTITY,
            secondary=[],
            recoverability=RecoverabilityState.AMBIGUOUS,
            final_set=FinalDisposition.AMBIGUOUS,
            evidence=ambiguous_methods,
            required_missing_proof="single deterministic target proof",
            recovery=None,
        )

    if not _safe_text(row.get("content_id")) and not _safe_text(row.get("run_id")) and not _safe_text(row.get("youtube_video_id")):
        if _safe_text(row.get("upload_id")):
            return _build_classification(
                row=row,
                category=TaxonomyCategory.UPLOAD_ID_NOT_IN_EVIDENCE,
                secondary=[],
                recoverability=RecoverabilityState.RECOVERABLE_WITH_OFFICIAL_API,
                final_set=FinalDisposition.STILL_UNRESOLVED,
                evidence=[{"reason": "upload_id_present_but_no_local_match"}],
                required_missing_proof="exact upload-result mapping",
                recovery=None,
            )
        if row.get("upload_id") is None:
            return _build_classification(
                row=row,
                category=TaxonomyCategory.MISSING_UPLOAD_ID,
                secondary=[],
                recoverability=RecoverabilityState.PERMANENTLY_UNRECOVERABLE,
                final_set=FinalDisposition.PERMANENTLY_UNRECOVERABLE,
                evidence=[{"reason": "missing_upload_content_run_video_ids"}],
                required_missing_proof="upload id or any exact identity key",
                recovery=None,
            )
        return _build_classification(
            row=row,
            category=TaxonomyCategory.INSUFFICIENT_IDENTITY_EVIDENCE,
            secondary=[],
            recoverability=RecoverabilityState.PERMANENTLY_UNRECOVERABLE,
            final_set=FinalDisposition.PERMANENTLY_UNRECOVERABLE,
            evidence=[{"reason": "missing_content_id_run_id_video_id"}],
            required_missing_proof="any exact identity key",
            recovery=None,
        )

    if not _safe_text(row.get("content_id")):
        return _build_classification(
            row=row,
            category=TaxonomyCategory.MISSING_CONTENT_ID,
            secondary=[],
            recoverability=RecoverabilityState.RECOVERABLE_WITH_STUDIO_EXPORT,
            final_set=FinalDisposition.STILL_UNRESOLVED,
            evidence=[{"reason": "content_id_missing"}],
            required_missing_proof="exact video id or canonical content id",
            recovery=None,
        )

    if not _safe_text(row.get("run_id")):
        return _build_classification(
            row=row,
            category=TaxonomyCategory.MISSING_RUN_ID,
            secondary=[],
            recoverability=RecoverabilityState.RECOVERABLE_WITH_FUTURE_FORWARD_EVIDENCE,
            final_set=FinalDisposition.STILL_UNRESOLVED,
            evidence=[{"reason": "run_id_missing"}],
            required_missing_proof="exact run_id or forward session id",
            recovery=None,
        )

    if not _safe_text(row.get("youtube_video_id")):
        return _build_classification(
            row=row,
            category=TaxonomyCategory.MISSING_VIDEO_ID,
            secondary=[],
            recoverability=RecoverabilityState.RECOVERABLE_WITH_STUDIO_EXPORT,
            final_set=FinalDisposition.STILL_UNRESOLVED,
            evidence=[{"reason": "youtube_video_id_missing"}],
            required_missing_proof="exact video id",
            recovery=None,
        )

    if _safe_text(row.get("youtube_video_id")) and not indexes.by_video_id.get(_safe_text(row.get("youtube_video_id"))):
        return _build_classification(
            row=row,
            category=TaxonomyCategory.VIDEO_ID_NOT_IN_UPLOAD_MAP,
            secondary=[],
            recoverability=RecoverabilityState.RECOVERABLE_WITH_STUDIO_EXPORT,
            final_set=FinalDisposition.STILL_UNRESOLVED,
            evidence=[{"reason": "video_id_not_in_local_upload_map"}],
            required_missing_proof="exact upload-result video id mapping",
            recovery=None,
        )

    if _safe_text(row.get("run_id")) and not indexes.by_run_id.get(_safe_text(row.get("run_id"))):
        return _build_classification(
            row=row,
            category=TaxonomyCategory.RUN_ID_NOT_IN_LINEAGE,
            secondary=[],
            recoverability=RecoverabilityState.RECOVERABLE_WITH_FUTURE_FORWARD_EVIDENCE,
            final_set=FinalDisposition.STILL_UNRESOLVED,
            evidence=[{"reason": "run_id_not_in_lineage"}],
            required_missing_proof="exact run_id lineage proof",
            recovery=None,
        )

    if not ownership_matches:
        return _build_classification(
            row=row,
            category=TaxonomyCategory.MISSING_OWNERSHIP_RECORD,
            secondary=[TaxonomyCategory.CONTENT_ID_NOT_IN_OWNERSHIP.value],
            recoverability=RecoverabilityState.RECOVERABLE_WITH_OFFICIAL_API,
            final_set=FinalDisposition.STILL_UNRESOLVED,
            evidence=[{"reason": "no_exact_local_target"}],
            required_missing_proof="exact ownership or authoritative video identity evidence",
            recovery=None,
        )

    return _build_classification(
        row=row,
        category=TaxonomyCategory.UNKNOWN,
        secondary=[],
        recoverability=RecoverabilityState.UNKNOWN,
        final_set=FinalDisposition.STILL_UNRESOLVED,
        evidence=[{"reason": "no_matching_taxonomy"}],
        required_missing_proof="deterministic identity proof",
        recovery=None,
    )


def _build_recovery_payload(*, row: dict[str, Any], method: RecoveryMethod, lookup_value: str, target: EvidenceTarget) -> dict[str, Any]:
    proof_records = [
        {
            "source_type": proof.source_type,
            "path": proof.path,
            "identity_key": proof.identity_key,
            "identity_value": proof.identity_value,
            "proof_hash": proof.proof_hash,
            "payload": proof.payload,
        }
        for proof in target.proof_records
    ]
    recovery_evidence_id = "uar_recovery_" + _sha_text(
        "|".join(
            [
                _safe_text(row.get("unresolved_record_id")),
                method.value,
                target.target_key,
                "|".join(sorted(item["proof_hash"] for item in proof_records)),
            ]
        )
    )[:24]
    return {
        "recovery_evidence_id": recovery_evidence_id,
        "recovery_method": method.value,
        "confidence": "PROVEN",
        "lookup_value": lookup_value,
        "source_proof_records": [{"unresolved_record_id": row.get("unresolved_record_id"), "row_hash": row.get("row_hash")}],
        "target_proof_records": proof_records,
        "proof_hashes": sorted(item["proof_hash"] for item in proof_records),
        "deterministic_join_path": f"{method.value}:{lookup_value}->{target.target_key}",
        "target": target.to_target_dict(),
        "advisory_only": True,
        "pipeline_output_changed": False,
    }


def _build_classification(
    *,
    row: dict[str, Any],
    category: TaxonomyCategory,
    secondary: list[str],
    recoverability: RecoverabilityState,
    final_set: FinalDisposition,
    evidence: list[dict[str, Any]],
    required_missing_proof: str | None,
    recovery: dict[str, Any] | None,
) -> dict[str, Any]:
    classification_id = "uar_class_" + _sha_text(
        "|".join(
            [
                _safe_text(row.get("unresolved_record_id")),
                category.value,
                recoverability.value,
                final_set.value,
            ]
        )
    )[:24]
    return {
        "schema_version": PHASE4C_SCHEMA_VERSION,
        "classification_id": classification_id,
        "unresolved_record_id": row.get("unresolved_record_id"),
        "canonical_analytics_record_id": row.get("canonical_analytics_record_id"),
        "primary_category": category.value,
        "secondary_reasons": sorted(set(x for x in secondary if x and x != category.value)),
        "recoverability": recoverability.value,
        "final_set": final_set.value,
        "confidence": "PROVEN" if recovery is not None else ("HIGH" if final_set == FinalDisposition.AMBIGUOUS else "MEDIUM"),
        "required_missing_proof": required_missing_proof,
        "future_prevention_status": build_future_prevention_status(category),
        "evidence": evidence,
        "recovery": recovery,
        "advisory_only": True,
        "pipeline_output_changed": False,
    }


def build_future_prevention_status(category: TaxonomyCategory) -> str:
    if category in {TaxonomyCategory.MISSING_OWNERSHIP_RECORD, TaxonomyCategory.CONTENT_ID_NOT_IN_OWNERSHIP}:
        return PreventionStatus.PARTIALLY_PREVENTED.value
    if category in {TaxonomyCategory.DUPLICATE_SOURCE_ROW, TaxonomyCategory.DUPLICATE_SNAPSHOT}:
        return PreventionStatus.PREVENTED.value
    if category in {TaxonomyCategory.MISSING_VIDEO_ID, TaxonomyCategory.MISSING_RUN_ID, TaxonomyCategory.MISSING_CONTENT_ID}:
        return PreventionStatus.PARTIALLY_PREVENTED.value
    if category == TaxonomyCategory.AMBIGUOUS_IDENTITY:
        return PreventionStatus.NOT_PREVENTED.value
    if category in {TaxonomyCategory.MALFORMED_ROW, TaxonomyCategory.SCHEMA_MISMATCH}:
        return PreventionStatus.PARTIALLY_PREVENTED.value
    return PreventionStatus.UNKNOWN.value


def audit_unresolved_rows(
    *,
    manifest_rows: list[dict[str, Any]],
    indexes: EvidenceIndexes,
) -> list[dict[str, Any]]:
    snapshot_dispositions = determine_snapshot_dispositions(manifest_rows)
    results: list[dict[str, Any]] = []
    for row in manifest_rows:
        disposition = snapshot_dispositions[_safe_text(row.get("unresolved_record_id"))]
        results.append(classify_unresolved_row(row=row, indexes=indexes, snapshot_disposition=disposition))
    results.sort(key=lambda item: _safe_text(item.get("unresolved_record_id")))
    return results


def compute_coverage_delta(*, baseline: BaselineState, results: list[dict[str, Any]]) -> dict[str, Any]:
    final_counts = Counter(_safe_text(item.get("final_set")) for item in results)
    recovered = int(final_counts.get(FinalDisposition.RECOVERED.value, 0))
    ambiguous = int(final_counts.get(FinalDisposition.AMBIGUOUS.value, 0))
    invalid = int(final_counts.get(FinalDisposition.INVALID.value, 0))
    still_unresolved = int(final_counts.get(FinalDisposition.STILL_UNRESOLVED.value, 0))
    permanently_unrecoverable = int(final_counts.get(FinalDisposition.PERMANENTLY_UNRECOVERABLE.value, 0))
    linked_after = baseline.linked_rows + recovered
    total_rows = baseline.imported_rows
    return {
        "before": {
            "total_rows": total_rows,
            "linked": baseline.linked_rows,
            "unresolved": baseline.unresolved_rows,
            "ambiguous": baseline.ambiguous_rows,
            "invalid": baseline.invalid_rows,
            "join_rate": round((baseline.linked_rows / total_rows) if total_rows else 0.0, 6),
        },
        "after": {
            "recovered": recovered,
            "linked_total": linked_after,
            "still_unresolved": still_unresolved,
            "permanently_unrecoverable": permanently_unrecoverable,
            "ambiguous": ambiguous,
            "invalid": invalid,
            "join_rate": round((linked_after / total_rows) if total_rows else 0.0, 6),
        },
        "recovery_methods": dict(Counter(item.get("recovery", {}).get("recovery_method") for item in results if isinstance(item.get("recovery"), dict))),
    }


def summarize_classification_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in results:
        grouped[_safe_text(item.get("primary_category"))].append(item)
    summary: list[dict[str, Any]] = []
    for category, items in sorted(grouped.items()):
        recoverability = Counter(_safe_text(item.get("recoverability")) for item in items)
        required_proof = Counter(_safe_text(item.get("required_missing_proof")) or "NONE" for item in items)
        summary.append(
            {
                "category": category,
                "count": len(items),
                "recoverability": dict(sorted(recoverability.items())),
                "required_proof": dict(sorted(required_proof.items())),
            }
        )
    return summary


def build_root_cause_report(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in results:
        if _safe_text(item.get("final_set")) == FinalDisposition.RECOVERED.value:
            continue
        grouped[_safe_text(item.get("primary_category"))].append(item)

    report: list[dict[str, Any]] = []
    for category, items in sorted(grouped.items()):
        recoverability = Counter(_safe_text(item.get("recoverability")) for item in items)
        report.append(
            {
                "category": category,
                "count": len(items),
                "missing_evidence": sorted(set(_safe_text(item.get("required_missing_proof")) for item in items if _safe_text(item.get("required_missing_proof")))),
                "deterministic_failure_reason": sorted(set(_safe_text((item.get("evidence") or [{}])[0].get("reason")) for item in items if item.get("evidence"))),
                "studio_export_can_solve": any(_safe_text(item.get("recoverability")) == RecoverabilityState.RECOVERABLE_WITH_STUDIO_EXPORT.value for item in items),
                "official_api_can_solve": any(_safe_text(item.get("recoverability")) == RecoverabilityState.RECOVERABLE_WITH_OFFICIAL_API.value for item in items),
                "future_forward_prevents": any(_safe_text(item.get("future_prevention_status")) in {PreventionStatus.PREVENTED.value, PreventionStatus.PARTIALLY_PREVENTED.value} for item in items),
                "should_remain_permanently_unresolved": all(_safe_text(item.get("final_set")) == FinalDisposition.PERMANENTLY_UNRECOVERABLE.value for item in items),
                "recommended_operational_action": recommend_operational_action(category=category, recoverability=recoverability),
            }
        )
    return report


def recommend_operational_action(*, category: str, recoverability: Counter[str]) -> str:
    if recoverability.get(RecoverabilityState.RECOVERABLE_WITH_STUDIO_EXPORT.value):
        return "re-export Studio analytics with exact Video ID column preserved"
    if recoverability.get(RecoverabilityState.RECOVERABLE_WITH_OFFICIAL_API.value):
        return "restore official API permissions and query exact video dimension"
    if recoverability.get(RecoverabilityState.RECOVERABLE_WITH_FUTURE_FORWARD_EVIDENCE.value):
        return "preserve run/session lineage prospectively"
    if category == TaxonomyCategory.MISSING_OWNERSHIP_RECORD.value:
        return "retain ownership manifests for every uploaded content item"
    if category == TaxonomyCategory.PERMANENTLY_UNRECOVERABLE.value:
        return "no action; proof is irretrievably absent"
    return "no automatic action; retain unresolved classification"


def build_prevention_matrix(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    categories = sorted({_safe_text(item.get("primary_category")) for item in results})
    matrix: list[dict[str, Any]] = []
    for category in categories:
        cat = TaxonomyCategory(category)
        matrix.append(
            {
                "category": category,
                "Forward Evidence Capture": _component_prevention_status(cat, "forward_evidence"),
                "Analytics Evidence Join": _component_prevention_status(cat, "analytics_join"),
                "Studio Export Bridge": _component_prevention_status(cat, "studio_bridge"),
                "Script Lineage": _component_prevention_status(cat, "script_lineage"),
                "Planning/Blueprint Lineage": _component_prevention_status(cat, "planning_lineage"),
                "Upload-result persistence": _component_prevention_status(cat, "upload_persistence"),
                "Future official provider": _component_prevention_status(cat, "official_provider"),
            }
        )
    return matrix


def _component_prevention_status(category: TaxonomyCategory, component: str) -> str:
    if category in {TaxonomyCategory.DUPLICATE_SOURCE_ROW, TaxonomyCategory.DUPLICATE_SNAPSHOT}:
        if component in {"analytics_join", "upload_persistence"}:
            return PreventionStatus.PREVENTED.value
        return PreventionStatus.NOT_APPLICABLE.value
    if category in {TaxonomyCategory.MISSING_OWNERSHIP_RECORD, TaxonomyCategory.CONTENT_ID_NOT_IN_OWNERSHIP}:
        if component in {"forward_evidence", "script_lineage", "planning_lineage", "upload_persistence"}:
            return PreventionStatus.PARTIALLY_PREVENTED.value
        if component == "official_provider":
            return PreventionStatus.PARTIALLY_PREVENTED.value
        return PreventionStatus.NOT_PREVENTED.value
    if category in {TaxonomyCategory.MISSING_CONTENT_ID, TaxonomyCategory.MISSING_VIDEO_ID, TaxonomyCategory.MISSING_RUN_ID}:
        if component in {"forward_evidence", "script_lineage", "planning_lineage", "upload_persistence", "studio_bridge", "official_provider"}:
            return PreventionStatus.PARTIALLY_PREVENTED.value
        return PreventionStatus.NOT_PREVENTED.value
    if category == TaxonomyCategory.AMBIGUOUS_IDENTITY:
        if component in {"forward_evidence", "script_lineage", "planning_lineage"}:
            return PreventionStatus.PARTIALLY_PREVENTED.value
        return PreventionStatus.NOT_PREVENTED.value
    if category in {TaxonomyCategory.MALFORMED_ROW, TaxonomyCategory.SCHEMA_MISMATCH}:
        if component in {"studio_bridge", "analytics_join"}:
            return PreventionStatus.PARTIALLY_PREVENTED.value
        return PreventionStatus.UNKNOWN.value
    return PreventionStatus.UNKNOWN.value


def build_studio_export_request_spec() -> dict[str, Any]:
    return {
        "required_fields": [
            "Video ID",
            "Content title",
            "Channel ID",
            "Content type",
            "Date",
            "Views",
            "Impressions",
            "Impressions CTR",
            "Watch time",
            "Average view duration",
            "Average percentage viewed",
            "Shorts feed metrics",
            "Traffic source fields",
        ],
        "identity_rule": "Video ID remains the only Studio identity proof; title is descriptive only.",
        "operator_checklist": [
            "Export content-level rows, not aggregate channel totals.",
            "Keep the Video ID column intact.",
            "Preserve channel identifier and content type columns.",
            "Preserve the exact snapshot date or date range.",
            "Do not edit localized numeric formats before import.",
            "Do not scrape or automate Studio downloads.",
        ],
        "advisory_only": True,
        "pipeline_output_changed": False,
    }


def build_official_api_handoff(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    handoff: list[dict[str, Any]] = []
    for item in results:
        if _safe_text(item.get("recoverability")) != RecoverabilityState.RECOVERABLE_WITH_OFFICIAL_API.value:
            continue
        handoff.append(
            {
                "unresolved_record_id": item.get("unresolved_record_id"),
                "required_api": "YouTube Analytics API + YouTube Data API",
                "required_scopes": [
                    "https://www.googleapis.com/auth/yt-analytics.readonly",
                    "https://www.googleapis.com/auth/youtube.readonly",
                ],
                "required_identity_dimension": "video",
                "expected_deterministic_key": "video_id",
                "metrics_likely_available": [
                    "views",
                    "impressions",
                    "impressions_ctr",
                    "watch_time",
                    "average_view_duration",
                    "average_percentage_viewed",
                ],
                "metrics_not_guaranteed": [
                    "retention_curve_reference",
                    "all traffic-source breakdowns for every historical row",
                ],
                "advisory_only": True,
                "pipeline_output_changed": False,
            }
        )
    handoff.sort(key=lambda item: _safe_text(item.get("unresolved_record_id")))
    return handoff


def write_deterministic_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(_stable_json(row) + "\n" for row in rows)
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if existing == content:
            return
        raise ValueError(f"immutable_file_mismatch:{path}")
    path.write_text(content, encoding="utf-8")


def _append_unique_rows(path: Path, rows: list[dict[str, Any]], *, id_field: str) -> dict[str, int]:
    existing, _malformed = _load_jsonl(path)
    known = {_safe_text(row.get(id_field)) for row in existing if _safe_text(row.get(id_field))}
    appended = 0
    duplicates = 0
    for row in rows:
        row_id = _safe_text(row.get(id_field))
        if row_id in known:
            duplicates += 1
            continue
        blob = _stable_json(row) + "\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
        try:
            os.write(fd, blob.encode("utf-8"))
        finally:
            os.close(fd)
        known.add(row_id)
        appended += 1
    return {"appended": appended, "duplicates": duplicates}


def append_recovery_evidence(path: Path, results: list[dict[str, Any]]) -> dict[str, int]:
    rows: list[dict[str, Any]] = []
    for item in results:
        recovery = item.get("recovery")
        if not isinstance(recovery, dict):
            continue
        row = {
            "schema_version": PHASE4C_SCHEMA_VERSION,
            "recovery_evidence_id": recovery.get("recovery_evidence_id"),
            "unresolved_record_id": item.get("unresolved_record_id"),
            "canonical_analytics_record_id": item.get("canonical_analytics_record_id"),
            "final_set": item.get("final_set"),
            "recovery_method": recovery.get("recovery_method"),
            "confidence": recovery.get("confidence"),
            "proof_hashes": list(recovery.get("proof_hashes") or []),
            "deterministic_join_path": recovery.get("deterministic_join_path"),
            "target": dict(recovery.get("target") or {}),
            "advisory_only": True,
            "pipeline_output_changed": False,
            "created_at": _now_iso(),
        }
        rows.append(row)
    return _append_unique_rows(path, rows, id_field="recovery_evidence_id")


def append_audit_results(path: Path, results: list[dict[str, Any]]) -> dict[str, int]:
    rows = [
        {
            "schema_version": PHASE4C_SCHEMA_VERSION,
            "classification_id": item.get("classification_id"),
            "unresolved_record_id": item.get("unresolved_record_id"),
            "primary_category": item.get("primary_category"),
            "secondary_reasons": list(item.get("secondary_reasons") or []),
            "recoverability": item.get("recoverability"),
            "final_set": item.get("final_set"),
            "required_missing_proof": item.get("required_missing_proof"),
            "advisory_only": True,
            "pipeline_output_changed": False,
            "created_at": _now_iso(),
        }
        for item in results
    ]
    return _append_unique_rows(path, rows, id_field="classification_id")


def append_duplicate_dispositions(path: Path, manifest_rows: list[dict[str, Any]]) -> dict[str, int]:
    dispositions = determine_snapshot_dispositions(manifest_rows)
    rows = []
    for unresolved_record_id, payload in sorted(dispositions.items()):
        rows.append(
            {
                "schema_version": PHASE4C_SCHEMA_VERSION,
                "duplicate_disposition_id": "uar_dup_" + _sha_text(unresolved_record_id + "|" + _stable_json(payload))[:24],
                "unresolved_record_id": unresolved_record_id,
                **payload,
                "advisory_only": True,
                "pipeline_output_changed": False,
                "created_at": _now_iso(),
            }
        )
    return _append_unique_rows(path, rows, id_field="duplicate_disposition_id")


def run_phase4c_unresolved_analytics_recovery(
    *,
    repository_root: Path,
    output_dir: Path = PHASE4C_DEFAULT_OUTPUT_DIR,
    manifest_path: Path = UNRESOLVED_INPUT_MANIFEST_PATH,
    audit_results_path: Path = UNRESOLVED_AUDIT_RESULTS_PATH,
    recovery_evidence_path: Path = UNRESOLVED_RECOVERY_EVIDENCE_PATH,
    duplicate_disposition_path: Path = UNRESOLVED_DUPLICATE_DISPOSITION_PATH,
) -> dict[str, Any]:
    baseline = load_phase4b_baseline(repository_root=repository_root)
    source_rows = reconstruct_authoritative_source_rows(repository_root=repository_root, baseline=baseline)
    canonical_rows = load_authoritative_phase4b_canonical_rows(repository_root=repository_root, baseline=baseline)
    manifest_rows = build_unresolved_input_manifest(source_rows=source_rows, canonical_rows=canonical_rows, baseline=baseline)
    indexes = build_evidence_indexes(repository_root=repository_root)
    results = audit_unresolved_rows(manifest_rows=manifest_rows, indexes=indexes)
    coverage_delta = compute_coverage_delta(baseline=baseline, results=results)
    classification_summary = summarize_classification_results(results)
    root_causes = build_root_cause_report(results)
    prevention_matrix = build_prevention_matrix(results)
    studio_export_spec = build_studio_export_request_spec()
    official_api_handoff = build_official_api_handoff(results)

    write_deterministic_jsonl(repository_root / manifest_path, manifest_rows)
    manifest_audit = append_audit_results(repository_root / audit_results_path, results)
    recovery_audit = append_recovery_evidence(repository_root / recovery_evidence_path, results)
    duplicate_audit = append_duplicate_dispositions(repository_root / duplicate_disposition_path, manifest_rows)

    output_dir = repository_root / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "frozen_unresolved_input_manifest.jsonl").write_text("".join(_stable_json(row) + "\n" for row in manifest_rows), encoding="utf-8")
    (output_dir / "classification_results.json").write_text(_stable_json(results), encoding="utf-8")
    (output_dir / "coverage_delta.json").write_text(_stable_json(coverage_delta), encoding="utf-8")
    (output_dir / "root_cause_report.json").write_text(_stable_json(root_causes), encoding="utf-8")
    (output_dir / "prevention_matrix.json").write_text(_stable_json(prevention_matrix), encoding="utf-8")
    (output_dir / "studio_export_request_spec.json").write_text(_stable_json(studio_export_spec), encoding="utf-8")
    (output_dir / "official_api_handoff.json").write_text(_stable_json(official_api_handoff), encoding="utf-8")

    summary = {
        "generated_at": _now_iso(),
        "baseline": {
            "source_file_hash": baseline.source_file_hash,
            "imported_rows": baseline.imported_rows,
            "linked_rows": baseline.linked_rows,
            "unresolved_rows": baseline.unresolved_rows,
            "ambiguous_rows": baseline.ambiguous_rows,
            "invalid_rows": baseline.invalid_rows,
        },
        "manifest_count": len(manifest_rows),
        "classification_results": classification_summary,
        "coverage_delta": coverage_delta,
        "root_causes": root_causes,
        "prevention_matrix": prevention_matrix,
        "official_api_handoff_count": len(official_api_handoff),
        "append_only_audit": {
            "audit_results": manifest_audit,
            "recovery_evidence": recovery_audit,
            "duplicate_disposition": duplicate_audit,
        },
        "advisory_only": True,
        "pipeline_output_changed": False,
    }
    (output_dir / "assessment_summary.json").write_text(json.dumps(summary, ensure_ascii=True, sort_keys=True, indent=2), encoding="utf-8")
    return summary