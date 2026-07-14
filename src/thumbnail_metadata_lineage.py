from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
from typing import Any


THUMBNAIL_METADATA_LINEAGE_SCHEMA_VERSION = "v1"
DEFAULT_THUMBNAIL_METADATA_LINEAGE_PATH = Path("logs/thumbnail_metadata_lineage.jsonl")
DEFAULT_THUMBNAIL_METADATA_LINEAGE_ENV = "THUMBNAIL_METADATA_LINEAGE_PATH"


@dataclass(frozen=True)
class ThumbnailMetadataLineageAppendResult:
    appended: bool
    duplicate: bool
    reason: str


@dataclass(frozen=True)
class ThumbnailMetadataLineageReplayDiagnostics:
    malformed_rows: int
    replay_errors: list[str]


@dataclass(frozen=True)
class ThumbnailMetadataLineageRecord:
    schema_version: str
    lineage_id: str
    thumbnail_generation_id: str
    content_id: str
    run_id: str
    blueprint_id: str | None
    planning_id: str | None
    thumbnail_prompt_hash: str | None
    image_hash: str | None
    metadata_version: str
    creation_timestamp: str
    content_type: str
    variant_id: str | None
    thumbnail_path: str | None
    completeness_score: float
    missing_fields: list[str]
    integrity_hash: str
    advisory_only: bool
    pipeline_output_changed: bool

    def to_dict(self) -> dict[str, Any]:
        return validate_thumbnail_metadata_lineage_row(
            {
                "schema_version": self.schema_version,
                "lineage_id": self.lineage_id,
                "thumbnail_generation_id": self.thumbnail_generation_id,
                "content_id": self.content_id,
                "run_id": self.run_id,
                "blueprint_id": self.blueprint_id,
                "planning_id": self.planning_id,
                "thumbnail_prompt_hash": self.thumbnail_prompt_hash,
                "image_hash": self.image_hash,
                "metadata_version": self.metadata_version,
                "creation_timestamp": self.creation_timestamp,
                "content_type": self.content_type,
                "variant_id": self.variant_id,
                "thumbnail_path": self.thumbnail_path,
                "completeness_score": self.completeness_score,
                "missing_fields": list(self.missing_fields),
                "integrity_hash": self.integrity_hash,
                "advisory_only": bool(self.advisory_only),
                "pipeline_output_changed": bool(self.pipeline_output_changed),
            }
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _sha(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _is_enabled(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def thumbnail_metadata_lineage_enabled() -> bool:
    return _is_enabled(os.getenv("THUMBNAIL_METADATA_LINEAGE_ENABLED", "false"))


def hash_file(path: str | None) -> str | None:
    p = Path(str(path or "").strip())
    if not p.exists() or not p.is_file():
        return None
    digest = hashlib.sha256()
    with p.open("rb") as fh:
        while True:
            chunk = fh.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def compute_thumbnail_generation_id(
    *,
    content_id: str,
    run_id: str,
    content_type: str,
    variant_id: str | None,
    thumbnail_prompt_hash: str | None,
    image_hash: str | None,
) -> str:
    raw = "|".join(
        [
            _safe_text(content_id),
            _safe_text(run_id),
            _safe_text(content_type),
            _safe_text(variant_id),
            _safe_text(thumbnail_prompt_hash),
            _safe_text(image_hash),
        ]
    )
    return "tml_gen_" + _sha(raw)[:24]


def compute_lineage_id(*, thumbnail_generation_id: str, creation_timestamp: str) -> str:
    return "tml_" + _sha(f"{_safe_text(thumbnail_generation_id)}|{_safe_text(creation_timestamp)}")[:24]


def compute_thumbnail_prompt_hash(*, thumbnail_prompt: str | None) -> str | None:
    text = _safe_text(thumbnail_prompt)
    if not text:
        return None
    return _sha(text)


def compute_lineage_completeness(payload: dict[str, Any]) -> tuple[float, list[str]]:
    required = [
        "content_id",
        "run_id",
        "thumbnail_generation_id",
        "thumbnail_prompt_hash",
        "image_hash",
        "metadata_version",
        "creation_timestamp",
    ]
    missing = [field for field in required if not _safe_text(payload.get(field))]
    score = (len(required) - len(missing)) / len(required)
    return round(score, 6), missing


def compute_integrity_hash(payload: dict[str, Any]) -> str:
    protected = {
        "thumbnail_generation_id": payload.get("thumbnail_generation_id"),
        "content_id": payload.get("content_id"),
        "run_id": payload.get("run_id"),
        "blueprint_id": payload.get("blueprint_id"),
        "planning_id": payload.get("planning_id"),
        "thumbnail_prompt_hash": payload.get("thumbnail_prompt_hash"),
        "image_hash": payload.get("image_hash"),
        "metadata_version": payload.get("metadata_version"),
        "creation_timestamp": payload.get("creation_timestamp"),
        "content_type": payload.get("content_type"),
        "variant_id": payload.get("variant_id"),
        "thumbnail_path": payload.get("thumbnail_path"),
    }
    return _sha(_stable_json(protected))


def validate_thumbnail_metadata_lineage_row(row: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ValueError("invalid_payload")

    required_fields = [
        "schema_version",
        "lineage_id",
        "thumbnail_generation_id",
        "content_id",
        "run_id",
        "metadata_version",
        "creation_timestamp",
        "content_type",
        "completeness_score",
        "missing_fields",
        "integrity_hash",
        "advisory_only",
        "pipeline_output_changed",
    ]
    for field in required_fields:
        if field not in row:
            raise ValueError(f"missing_field:{field}")

    if _safe_text(row.get("schema_version")) != THUMBNAIL_METADATA_LINEAGE_SCHEMA_VERSION:
        raise ValueError("invalid_field:schema_version")
    if not _safe_text(row.get("content_id")):
        raise ValueError("invalid_field:content_id")
    if not _safe_text(row.get("run_id")):
        raise ValueError("invalid_field:run_id")
    if not _safe_text(row.get("thumbnail_generation_id")):
        raise ValueError("invalid_field:thumbnail_generation_id")
    if not _safe_text(row.get("lineage_id")):
        raise ValueError("invalid_field:lineage_id")
    if not _safe_text(row.get("metadata_version")):
        raise ValueError("invalid_field:metadata_version")
    if not _safe_text(row.get("content_type")):
        raise ValueError("invalid_field:content_type")
    if not isinstance(row.get("missing_fields"), list):
        raise ValueError("invalid_field:missing_fields")
    if not bool(row.get("advisory_only")):
        raise ValueError("invalid_field:advisory_only")
    if bool(row.get("pipeline_output_changed")):
        raise ValueError("invalid_field:pipeline_output_changed")

    try:
        completeness_score = float(row.get("completeness_score"))
    except Exception as exc:
        raise ValueError("invalid_field:completeness_score") from exc
    if not (0.0 <= completeness_score <= 1.0):
        raise ValueError("invalid_field:completeness_score_range")

    created = _safe_text(row.get("creation_timestamp"))
    try:
        datetime.fromisoformat(created.replace("Z", "+00:00"))
    except Exception as exc:
        raise ValueError("invalid_field:creation_timestamp") from exc

    normalized = dict(row)
    normalized["blueprint_id"] = _safe_text(row.get("blueprint_id")) or None
    normalized["planning_id"] = _safe_text(row.get("planning_id")) or None
    normalized["thumbnail_prompt_hash"] = _safe_text(row.get("thumbnail_prompt_hash")) or None
    normalized["image_hash"] = _safe_text(row.get("image_hash")) or None
    normalized["variant_id"] = _safe_text(row.get("variant_id")) or None
    normalized["thumbnail_path"] = _safe_text(row.get("thumbnail_path")) or None
    normalized["completeness_score"] = completeness_score
    normalized["missing_fields"] = [str(x) for x in (row.get("missing_fields") or [])]
    normalized["advisory_only"] = bool(row.get("advisory_only"))
    normalized["pipeline_output_changed"] = bool(row.get("pipeline_output_changed"))

    expected_integrity = compute_integrity_hash(normalized)
    if _safe_text(normalized.get("integrity_hash")) != expected_integrity:
        raise ValueError("invalid_field:integrity_hash")

    return normalized


def load_thumbnail_metadata_lineage_rows(
    *,
    input_path: Path | str = DEFAULT_THUMBNAIL_METADATA_LINEAGE_PATH,
    limit: int = 0,
) -> tuple[list[dict[str, Any]], int, list[str]]:
    path = Path(input_path)
    if not path.exists():
        return [], 0, []

    rows: list[dict[str, Any]] = []
    malformed = 0
    errors: list[str] = []
    for index, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            decoded = json.loads(line)
            rows.append(validate_thumbnail_metadata_lineage_row(decoded))
        except Exception as exc:
            malformed += 1
            errors.append(f"line={index}:{exc}")
    if limit > 0:
        rows = rows[-limit:]
    return rows, malformed, errors


class ThumbnailMetadataLineageStore:
    def __init__(self, *, lineage_path: Path | str = DEFAULT_THUMBNAIL_METADATA_LINEAGE_PATH):
        self.lineage_path = Path(lineage_path)
        self._known_ids: set[str] | None = None

    def _ensure_known_ids(self) -> set[str]:
        if self._known_ids is not None:
            return self._known_ids
        rows, _malformed, _errors = load_thumbnail_metadata_lineage_rows(input_path=self.lineage_path, limit=0)
        self._known_ids = {_safe_text(row.get("lineage_id")) for row in rows if _safe_text(row.get("lineage_id"))}
        return self._known_ids

    def append(self, row: dict[str, Any]) -> ThumbnailMetadataLineageAppendResult:
        payload = validate_thumbnail_metadata_lineage_row(row)
        known = self._ensure_known_ids()
        lineage_id = _safe_text(payload.get("lineage_id"))
        if lineage_id in known:
            return ThumbnailMetadataLineageAppendResult(appended=False, duplicate=True, reason="duplicate_lineage_id")

        self.lineage_path.parent.mkdir(parents=True, exist_ok=True)
        blob = _stable_json(payload) + "\n"
        fd = os.open(self.lineage_path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
        try:
            os.write(fd, blob.encode("utf-8"))
        finally:
            os.close(fd)
        known.add(lineage_id)
        return ThumbnailMetadataLineageAppendResult(appended=True, duplicate=False, reason="appended")


class ThumbnailMetadataLineageRecorder:
    def __init__(self, *, lineage_path: Path | str | None = None):
        resolved = lineage_path or os.getenv(DEFAULT_THUMBNAIL_METADATA_LINEAGE_ENV, str(DEFAULT_THUMBNAIL_METADATA_LINEAGE_PATH))
        self.store = ThumbnailMetadataLineageStore(lineage_path=resolved)

    def append_thumbnail_metadata(self, row: dict[str, Any]) -> ThumbnailMetadataLineageAppendResult:
        return self.store.append(row)


def build_thumbnail_metadata_lineage_row(
    *,
    content_id: str,
    run_id: str,
    blueprint_id: str | None,
    planning_id: str | None,
    thumbnail_prompt: str | None,
    thumbnail_path: str | None,
    metadata_version: str,
    creation_timestamp: str | None,
    content_type: str,
    variant_id: str | None,
) -> dict[str, Any]:
    prompt_hash = compute_thumbnail_prompt_hash(thumbnail_prompt=thumbnail_prompt)
    image_hash = hash_file(thumbnail_path)
    created_at = _safe_text(creation_timestamp) or _now_iso()
    thumbnail_generation_id = compute_thumbnail_generation_id(
        content_id=content_id,
        run_id=run_id,
        content_type=content_type,
        variant_id=variant_id,
        thumbnail_prompt_hash=prompt_hash,
        image_hash=image_hash,
    )
    payload = {
        "schema_version": THUMBNAIL_METADATA_LINEAGE_SCHEMA_VERSION,
        "thumbnail_generation_id": thumbnail_generation_id,
        "content_id": _safe_text(content_id),
        "run_id": _safe_text(run_id),
        "blueprint_id": _safe_text(blueprint_id) or None,
        "planning_id": _safe_text(planning_id) or None,
        "thumbnail_prompt_hash": prompt_hash,
        "image_hash": image_hash,
        "metadata_version": _safe_text(metadata_version),
        "creation_timestamp": created_at,
        "content_type": _safe_text(content_type),
        "variant_id": _safe_text(variant_id) or None,
        "thumbnail_path": _safe_text(thumbnail_path) or None,
        "advisory_only": True,
        "pipeline_output_changed": False,
    }
    completeness_score, missing_fields = compute_lineage_completeness(payload)
    payload["completeness_score"] = completeness_score
    payload["missing_fields"] = missing_fields
    payload["integrity_hash"] = compute_integrity_hash(payload)
    payload["lineage_id"] = compute_lineage_id(
        thumbnail_generation_id=payload["thumbnail_generation_id"],
        creation_timestamp=payload["creation_timestamp"],
    )
    return validate_thumbnail_metadata_lineage_row(payload)


def replay_thumbnail_metadata_lineage_state(
    *,
    rows: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], ThumbnailMetadataLineageReplayDiagnostics]:
    state: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    malformed_rows = 0
    for row in rows:
        try:
            payload = validate_thumbnail_metadata_lineage_row(row)
            key = _safe_text(payload.get("thumbnail_generation_id"))
            entry = state.setdefault(
                key,
                {
                    "thumbnail_generation_id": key,
                    "content_id": payload.get("content_id"),
                    "run_id": payload.get("run_id"),
                    "lineage_ids": [],
                    "duplicate_count": 0,
                    "latest": {},
                    "completeness_score": 0.0,
                    "missing_fields": [],
                },
            )
            if _safe_text(payload.get("lineage_id")) in entry["lineage_ids"]:
                entry["duplicate_count"] += 1
                continue
            entry["lineage_ids"].append(_safe_text(payload.get("lineage_id")))
            entry["latest"] = dict(payload)
            entry["completeness_score"] = float(payload.get("completeness_score") or 0.0)
            entry["missing_fields"] = list(payload.get("missing_fields") or [])
        except Exception as exc:
            malformed_rows += 1
            errors.append(str(exc))
    return state, ThumbnailMetadataLineageReplayDiagnostics(malformed_rows=malformed_rows, replay_errors=errors)


def verify_thumbnail_metadata_lineage_integrity(
    *,
    lineage_path: Path | str = DEFAULT_THUMBNAIL_METADATA_LINEAGE_PATH,
) -> dict[str, Any]:
    rows, malformed, errors = load_thumbnail_metadata_lineage_rows(input_path=lineage_path, limit=0)
    state, replay_diagnostics = replay_thumbnail_metadata_lineage_state(rows=rows)
    duplicate_groups = sum(1 for entry in state.values() if len(entry.get("lineage_ids") or []) > 1)
    average_completeness = round(
        sum(float(entry.get("completeness_score") or 0.0) for entry in state.values()) / len(state),
        6,
    ) if state else 0.0
    return {
        "schema_version": THUMBNAIL_METADATA_LINEAGE_SCHEMA_VERSION,
        "rows": len(rows),
        "malformed_rows": malformed + replay_diagnostics.malformed_rows,
        "replay_errors": errors + replay_diagnostics.replay_errors,
        "thumbnail_generations": len(state),
        "duplicate_groups": duplicate_groups,
        "average_completeness_score": average_completeness,
        "advisory_only": True,
        "pipeline_output_changed": False,
    }
