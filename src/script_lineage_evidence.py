from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any


SCRIPT_LINEAGE_SCHEMA_VERSION = "v1"
DEFAULT_EVIDENCE_PATH = Path("logs/script_lineage_evidence.jsonl")

_SECRET_VALUE_PATTERN = re.compile(
    r"(api[_-]?key|token|secret|password|oauth|bearer|cookie|client[_-]?secret|refresh[_-]?token|access[_-]?token)",
    re.IGNORECASE,
)


class ScriptCompletenessState(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    PREVIEW_ONLY = "PREVIEW_ONLY"
    MISSING = "MISSING"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"


class ScriptSourceStage(str, Enum):
    INITIAL_GENERATION = "INITIAL_GENERATION"
    FACT_CHECK_REGENERATION = "FACT_CHECK_REGENERATION"
    QUALITY_REGENERATION = "QUALITY_REGENERATION"
    EDITOR_REWRITE = "EDITOR_REWRITE"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"
    LEGACY_IMPORT = "LEGACY_IMPORT"
    UNKNOWN = "UNKNOWN"


class LineageLinkStatus(str, Enum):
    LINKED = "LINKED"
    PARTIAL = "PARTIAL"
    MISSING = "MISSING"
    AMBIGUOUS = "AMBIGUOUS"
    INVALID = "INVALID"


class RetentionMode(str, Enum):
    HASH_ONLY = "HASH_ONLY"
    BOUNDED_EXCERPT = "BOUNDED_EXCERPT"
    FULL_LOCAL_SCRIPT = "FULL_LOCAL_SCRIPT"


class ScriptLineageEventType(str, Enum):
    SCRIPT_CREATED = "SCRIPT_CREATED"
    SCRIPT_FINALIZED = "SCRIPT_FINALIZED"
    SCRIPT_SUPERSEDED = "SCRIPT_SUPERSEDED"
    SCRIPT_CONSUMED_BY_RENDER = "SCRIPT_CONSUMED_BY_RENDER"
    SCRIPT_CONSUMED_BY_SHORTS = "SCRIPT_CONSUMED_BY_SHORTS"
    SCRIPT_LINKED_TO_UPLOAD = "SCRIPT_LINKED_TO_UPLOAD"
    LINEAGE_LINK_UPDATED = "LINEAGE_LINK_UPDATED"
    SCRIPT_INVALIDATED = "SCRIPT_INVALIDATED"


@dataclass(frozen=True)
class ScriptLineageRetentionPolicy:
    mode: RetentionMode
    excerpt_max_chars: int


@dataclass(frozen=True)
class ScriptLineageEvidenceRecord:
    schema_version: str
    event_type: str
    evidence_id: str
    content_id: str
    run_id: str
    canonical_channel_id: str
    content_type: str
    topic_hash: str
    script_hash: str
    normalized_script_hash: str
    script_length_chars: int
    script_word_count: int
    script_sentence_count: int
    script_completeness_state: str
    script_source_stage: str
    script_version: int
    parent_script_hash: str | None
    supersedes_script_hash: str | None
    generation_attempt: int
    regeneration_reason: str | None
    prompt_metadata_hash: str
    planning_context_id: str | None
    blueprint_id: str | None
    blueprint_hash: str | None
    experiment_id: str | None
    lineage_link_status: str
    created_at: str
    finalized_at: str | None
    render_consumed: bool
    shorts_consumed: bool
    upload_result_linked: bool
    advisory_only: bool
    pipeline_output_changed: bool
    retention_mode: str
    script_excerpt: str | None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "event_type": self.event_type,
            "evidence_id": self.evidence_id,
            "content_id": self.content_id,
            "run_id": self.run_id,
            "canonical_channel_id": self.canonical_channel_id,
            "content_type": self.content_type,
            "topic_hash": self.topic_hash,
            "script_hash": self.script_hash,
            "normalized_script_hash": self.normalized_script_hash,
            "script_length_chars": int(self.script_length_chars),
            "script_word_count": int(self.script_word_count),
            "script_sentence_count": int(self.script_sentence_count),
            "script_completeness_state": self.script_completeness_state,
            "script_source_stage": self.script_source_stage,
            "script_version": int(self.script_version),
            "parent_script_hash": self.parent_script_hash,
            "supersedes_script_hash": self.supersedes_script_hash,
            "generation_attempt": int(self.generation_attempt),
            "regeneration_reason": self.regeneration_reason,
            "prompt_metadata_hash": self.prompt_metadata_hash,
            "planning_context_id": self.planning_context_id,
            "blueprint_id": self.blueprint_id,
            "blueprint_hash": self.blueprint_hash,
            "experiment_id": self.experiment_id,
            "lineage_link_status": self.lineage_link_status,
            "created_at": self.created_at,
            "finalized_at": self.finalized_at,
            "render_consumed": bool(self.render_consumed),
            "shorts_consumed": bool(self.shorts_consumed),
            "upload_result_linked": bool(self.upload_result_linked),
            "advisory_only": bool(self.advisory_only),
            "pipeline_output_changed": bool(self.pipeline_output_changed),
            "retention_mode": self.retention_mode,
            "script_excerpt": self.script_excerpt,
        }
        return validate_script_lineage_row(payload)


@dataclass(frozen=True)
class LegacyImportAssessment:
    sample_count: int
    full_script_recoverable: int
    preview_only: int
    hash_only_recoverable: int
    ambiguous: int
    unrecoverable: int
    records: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_count": int(self.sample_count),
            "full_script_recoverable": int(self.full_script_recoverable),
            "preview_only": int(self.preview_only),
            "hash_only_recoverable": int(self.hash_only_recoverable),
            "ambiguous": int(self.ambiguous),
            "unrecoverable": int(self.unrecoverable),
            "records": list(self.records),
            "advisory_only": True,
            "pipeline_output_changed": False,
        }


@dataclass
class ScriptLineageReplayDiagnostics:
    malformed_rows: int
    replay_errors: list[str]


@dataclass
class ScriptLineageAppendResult:
    appended: bool
    duplicate: bool
    reason: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_enabled(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def script_lineage_evidence_enabled() -> bool:
    return _is_enabled(os.getenv("SCRIPT_LINEAGE_EVIDENCE_ENABLED", "false"))


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _safe_json_hash(payload: Any) -> str:
    blob = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _has_secret_like_content(value: str) -> bool:
    return bool(_SECRET_VALUE_PATTERN.search(str(value or "")))


def normalize_script_text(script: str) -> str:
    text = str(script or "")
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def hash_text(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def count_sentences(text: str) -> int:
    cleaned = str(text or "").strip()
    if not cleaned:
        return 0
    parts = [p for p in re.split(r"[.!?]+", cleaned) if p.strip()]
    return len(parts)


def count_words(text: str) -> int:
    cleaned = str(text or "").strip()
    if not cleaned:
        return 0
    return len([w for w in re.split(r"\s+", cleaned) if w])


def build_retention_policy_from_env() -> ScriptLineageRetentionPolicy:
    raw_mode = str(os.getenv("SCRIPT_LINEAGE_RETENTION_MODE", RetentionMode.HASH_ONLY.value) or "").strip().upper()
    try:
        mode = RetentionMode(raw_mode)
    except Exception:
        mode = RetentionMode.HASH_ONLY

    raw_limit = str(os.getenv("SCRIPT_LINEAGE_EXCERPT_MAX_CHARS", "240") or "240").strip()
    try:
        limit = int(raw_limit)
    except Exception:
        limit = 240
    limit = max(32, min(limit, 1000))
    return ScriptLineageRetentionPolicy(mode=mode, excerpt_max_chars=limit)


def classify_script_completeness(
    *,
    script_text: str,
    has_full_script: bool,
    has_preview: bool,
    invalid: bool = False,
) -> ScriptCompletenessState:
    if invalid:
        return ScriptCompletenessState.INVALID
    text = str(script_text or "").strip()
    if has_full_script and text:
        if len(text) >= 120:
            return ScriptCompletenessState.COMPLETE
        return ScriptCompletenessState.PARTIAL
    if has_preview and text:
        return ScriptCompletenessState.PREVIEW_ONLY
    if not text:
        return ScriptCompletenessState.MISSING
    return ScriptCompletenessState.UNKNOWN


def build_lineage_link_status(
    *,
    content_id: str,
    run_id: str,
    planning_context_id: str | None,
    blueprint_id: str | None,
) -> LineageLinkStatus:
    cid = _safe_text(content_id)
    rid = _safe_text(run_id)
    planning = _safe_text(planning_context_id)
    blueprint = _safe_text(blueprint_id)

    if not cid or not rid:
        return LineageLinkStatus.INVALID
    if planning and blueprint:
        return LineageLinkStatus.LINKED
    if planning or blueprint:
        return LineageLinkStatus.PARTIAL
    return LineageLinkStatus.MISSING


def redact_script_excerpt(script: str, *, policy: ScriptLineageRetentionPolicy) -> str | None:
    text = str(script or "").strip()
    if policy.mode == RetentionMode.HASH_ONLY:
        return None
    if not text:
        return ""

    if _has_secret_like_content(text):
        raise ValueError("secret_like_content_detected")

    if policy.mode == RetentionMode.FULL_LOCAL_SCRIPT:
        return text

    bounded = text[: policy.excerpt_max_chars]
    return bounded


def compute_evidence_id(
    *,
    event_type: ScriptLineageEventType,
    content_id: str,
    run_id: str,
    script_hash: str,
    script_version: int,
    generation_attempt: int,
) -> str:
    raw = "|".join(
        [
            str(event_type.value),
            _safe_text(content_id),
            _safe_text(run_id),
            _safe_text(script_hash),
            str(int(script_version)),
            str(int(generation_attempt)),
        ]
    )
    return "sle_" + hash_text(raw)[:24]


def validate_script_lineage_row(row: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ValueError("invalid_payload")

    required_fields = [
        "schema_version",
        "event_type",
        "evidence_id",
        "content_id",
        "run_id",
        "canonical_channel_id",
        "content_type",
        "topic_hash",
        "script_hash",
        "normalized_script_hash",
        "script_length_chars",
        "script_word_count",
        "script_sentence_count",
        "script_completeness_state",
        "script_source_stage",
        "script_version",
        "generation_attempt",
        "prompt_metadata_hash",
        "lineage_link_status",
        "created_at",
        "render_consumed",
        "shorts_consumed",
        "upload_result_linked",
        "advisory_only",
        "pipeline_output_changed",
        "retention_mode",
    ]
    for field in required_fields:
        if field not in row:
            raise ValueError(f"missing_field:{field}")

    if str(row.get("schema_version") or "") != SCRIPT_LINEAGE_SCHEMA_VERSION:
        raise ValueError("invalid_field:schema_version")

    try:
        ScriptLineageEventType(str(row.get("event_type") or ""))
        ScriptCompletenessState(str(row.get("script_completeness_state") or ""))
        ScriptSourceStage(str(row.get("script_source_stage") or ""))
        LineageLinkStatus(str(row.get("lineage_link_status") or ""))
        RetentionMode(str(row.get("retention_mode") or ""))
    except Exception as exc:
        raise ValueError("invalid_enum") from exc

    if not bool(row.get("advisory_only")):
        raise ValueError("invalid_field:advisory_only")
    if bool(row.get("pipeline_output_changed")):
        raise ValueError("invalid_field:pipeline_output_changed")

    created_at = _safe_text(row.get("created_at"))
    if not created_at:
        raise ValueError("missing_field:created_at")
    try:
        datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except Exception as exc:
        raise ValueError("invalid_field:created_at") from exc

    normalized = dict(row)
    normalized["script_length_chars"] = int(row.get("script_length_chars") or 0)
    normalized["script_word_count"] = int(row.get("script_word_count") or 0)
    normalized["script_sentence_count"] = int(row.get("script_sentence_count") or 0)
    normalized["script_version"] = int(row.get("script_version") or 0)
    normalized["generation_attempt"] = int(row.get("generation_attempt") or 0)
    normalized["render_consumed"] = bool(row.get("render_consumed"))
    normalized["shorts_consumed"] = bool(row.get("shorts_consumed"))
    normalized["upload_result_linked"] = bool(row.get("upload_result_linked"))
    normalized["advisory_only"] = bool(row.get("advisory_only"))
    normalized["pipeline_output_changed"] = bool(row.get("pipeline_output_changed"))

    excerpt = normalized.get("script_excerpt")
    if excerpt is not None and _has_secret_like_content(str(excerpt)):
        raise ValueError("secret_like_excerpt")

    return normalized


def load_script_lineage_rows(
    *,
    input_path: Path | str = DEFAULT_EVIDENCE_PATH,
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
            rows.append(validate_script_lineage_row(decoded))
        except Exception as exc:
            malformed += 1
            errors.append(f"line={index}:{exc}")

    if limit > 0:
        rows = rows[-limit:]
    return rows, malformed, errors


class ScriptLineageEvidenceStore:
    def __init__(self, *, evidence_path: Path | str = DEFAULT_EVIDENCE_PATH):
        self.evidence_path = Path(evidence_path)
        self._known_ids: set[str] | None = None

    def _ensure_known_ids(self) -> set[str]:
        if self._known_ids is not None:
            return self._known_ids
        rows, _malformed, _errors = load_script_lineage_rows(input_path=self.evidence_path, limit=0)
        self._known_ids = {str(row.get("evidence_id") or "") for row in rows if str(row.get("evidence_id") or "")}
        return self._known_ids

    def append(self, row: dict[str, Any]) -> ScriptLineageAppendResult:
        payload = validate_script_lineage_row(row)
        known = self._ensure_known_ids()
        evidence_id = str(payload.get("evidence_id") or "")
        if evidence_id in known:
            return ScriptLineageAppendResult(appended=False, duplicate=True, reason="duplicate_evidence_id")

        self.evidence_path.parent.mkdir(parents=True, exist_ok=True)
        blob = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
        fd = os.open(self.evidence_path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
        try:
            os.write(fd, blob.encode("utf-8"))
        finally:
            os.close(fd)

        known.add(evidence_id)
        return ScriptLineageAppendResult(appended=True, duplicate=False, reason="appended")


class ScriptLineageRecorder:
    def __init__(
        self,
        *,
        content_id: str,
        run_id: str,
        canonical_channel_id: str,
        content_type: str,
        topic: str,
        experiment_id: str | None,
        evidence_path: Path | str | None = None,
        retention_policy: ScriptLineageRetentionPolicy | None = None,
    ):
        self.content_id = _safe_text(content_id)
        self.run_id = _safe_text(run_id)
        self.canonical_channel_id = _safe_text(canonical_channel_id)
        self.content_type = _safe_text(content_type) or "mixed"
        self.topic_hash = hash_text(normalize_script_text(topic))
        self.experiment_id = _safe_text(experiment_id) or None
        self.retention_policy = retention_policy or build_retention_policy_from_env()
        self.store = ScriptLineageEvidenceStore(
            evidence_path=evidence_path or os.getenv("SCRIPT_LINEAGE_EVIDENCE_PATH", str(DEFAULT_EVIDENCE_PATH))
        )
        self._current_script_hash: str | None = None
        self._current_version = 0
        self._hash_to_version: dict[str, int] = {}
        self._finalized_hash: str | None = None
        self._render_consumed = False
        self._shorts_consumed = False
        self._upload_linked = False

    def _build_record(
        self,
        *,
        event_type: ScriptLineageEventType,
        script_text: str,
        source_stage: ScriptSourceStage,
        script_version: int,
        generation_attempt: int,
        regeneration_reason: str | None,
        prompt_metadata: dict[str, Any] | None,
        planning_context_id: str | None,
        blueprint_id: str | None,
        blueprint_hash: str | None,
        parent_script_hash: str | None,
        supersedes_script_hash: str | None,
        finalized_at: str | None,
    ) -> dict[str, Any]:
        script_value = str(script_text or "")
        invalid = _has_secret_like_content(script_value)
        completeness = classify_script_completeness(
            script_text=script_value,
            has_full_script=bool(script_value),
            has_preview=False,
            invalid=invalid,
        )

        normalized_script = normalize_script_text(script_value)
        script_hash = hash_text(script_value)
        normalized_script_hash = hash_text(normalized_script)
        prompt_hash = _safe_json_hash(prompt_metadata or {})
        link_status = build_lineage_link_status(
            content_id=self.content_id,
            run_id=self.run_id,
            planning_context_id=planning_context_id,
            blueprint_id=blueprint_id,
        )

        excerpt: str | None
        try:
            excerpt = redact_script_excerpt(script_value, policy=self.retention_policy)
        except Exception:
            excerpt = None
            completeness = ScriptCompletenessState.INVALID

        evidence_id = compute_evidence_id(
            event_type=event_type,
            content_id=self.content_id,
            run_id=self.run_id,
            script_hash=script_hash,
            script_version=script_version,
            generation_attempt=generation_attempt,
        )

        record = ScriptLineageEvidenceRecord(
            schema_version=SCRIPT_LINEAGE_SCHEMA_VERSION,
            event_type=event_type.value,
            evidence_id=evidence_id,
            content_id=self.content_id,
            run_id=self.run_id,
            canonical_channel_id=self.canonical_channel_id,
            content_type=self.content_type,
            topic_hash=self.topic_hash,
            script_hash=script_hash,
            normalized_script_hash=normalized_script_hash,
            script_length_chars=len(script_value),
            script_word_count=count_words(script_value),
            script_sentence_count=count_sentences(script_value),
            script_completeness_state=completeness.value,
            script_source_stage=source_stage.value,
            script_version=script_version,
            parent_script_hash=parent_script_hash,
            supersedes_script_hash=supersedes_script_hash,
            generation_attempt=max(0, int(generation_attempt)),
            regeneration_reason=_safe_text(regeneration_reason) or None,
            prompt_metadata_hash=prompt_hash,
            planning_context_id=_safe_text(planning_context_id) or None,
            blueprint_id=_safe_text(blueprint_id) or None,
            blueprint_hash=_safe_text(blueprint_hash) or None,
            experiment_id=self.experiment_id,
            lineage_link_status=link_status.value,
            created_at=_now_iso(),
            finalized_at=finalized_at,
            render_consumed=bool(self._render_consumed),
            shorts_consumed=bool(self._shorts_consumed),
            upload_result_linked=bool(self._upload_linked),
            advisory_only=True,
            pipeline_output_changed=False,
            retention_mode=self.retention_policy.mode.value,
            script_excerpt=excerpt,
        )
        return record.to_dict()

    def record_script_created(
        self,
        script_text: str,
        source_stage: ScriptSourceStage,
        generation_attempt: int,
        regeneration_reason: str | None,
        prompt_metadata: dict[str, Any] | None,
        planning_context_id: str | None,
        blueprint_id: str | None,
        blueprint_hash: str | None,
    ) -> ScriptLineageAppendResult:
        script_hash = hash_text(str(script_text or ""))
        existing_version = self._hash_to_version.get(script_hash)
        if existing_version is not None:
            self._current_script_hash = script_hash
            self._current_version = existing_version
            row = self._build_record(
                event_type=ScriptLineageEventType.LINEAGE_LINK_UPDATED,
                script_text=script_text,
                source_stage=source_stage,
                script_version=existing_version,
                generation_attempt=generation_attempt,
                regeneration_reason="identical_retry",
                prompt_metadata=prompt_metadata,
                planning_context_id=planning_context_id,
                blueprint_id=blueprint_id,
                blueprint_hash=blueprint_hash,
                parent_script_hash=self._current_script_hash,
                supersedes_script_hash=None,
                finalized_at=None,
            )
            return self.store.append(row)

        parent = self._current_script_hash
        supersedes = self._current_script_hash if self._current_script_hash else None
        next_version = int(self._current_version) + 1

        row = self._build_record(
            event_type=ScriptLineageEventType.SCRIPT_CREATED,
            script_text=script_text,
            source_stage=source_stage,
            script_version=next_version,
            generation_attempt=generation_attempt,
            regeneration_reason=regeneration_reason,
            prompt_metadata=prompt_metadata,
            planning_context_id=planning_context_id,
            blueprint_id=blueprint_id,
            blueprint_hash=blueprint_hash,
            parent_script_hash=parent,
            supersedes_script_hash=supersedes,
            finalized_at=None,
        )
        append_result = self.store.append(row)
        if append_result.appended:
            if supersedes:
                superseded_row = self._build_record(
                    event_type=ScriptLineageEventType.SCRIPT_SUPERSEDED,
                    script_text=script_text,
                    source_stage=source_stage,
                    script_version=next_version,
                    generation_attempt=generation_attempt,
                    regeneration_reason=regeneration_reason,
                    prompt_metadata=prompt_metadata,
                    planning_context_id=planning_context_id,
                    blueprint_id=blueprint_id,
                    blueprint_hash=blueprint_hash,
                    parent_script_hash=parent,
                    supersedes_script_hash=supersedes,
                    finalized_at=None,
                )
                self.store.append(superseded_row)
            self._current_script_hash = script_hash
            self._current_version = next_version
            self._hash_to_version[script_hash] = next_version
        return append_result

    def record_script_finalized(
        self,
        script_text: str,
        source_stage: ScriptSourceStage,
        generation_attempt: int,
        prompt_metadata: dict[str, Any] | None,
        planning_context_id: str | None,
        blueprint_id: str | None,
        blueprint_hash: str | None,
    ) -> ScriptLineageAppendResult:
        finalized_at = _now_iso()
        row = self._build_record(
            event_type=ScriptLineageEventType.SCRIPT_FINALIZED,
            script_text=script_text,
            source_stage=source_stage,
            script_version=max(1, int(self._current_version or 1)),
            generation_attempt=generation_attempt,
            regeneration_reason=None,
            prompt_metadata=prompt_metadata,
            planning_context_id=planning_context_id,
            blueprint_id=blueprint_id,
            blueprint_hash=blueprint_hash,
            parent_script_hash=self._current_script_hash,
            supersedes_script_hash=None,
            finalized_at=finalized_at,
        )
        result = self.store.append(row)
        if result.appended:
            self._finalized_hash = hash_text(str(script_text or ""))
        return result

    def record_consumed_by_render(self, script_text: str) -> ScriptLineageAppendResult:
        self._render_consumed = True
        row = self._build_record(
            event_type=ScriptLineageEventType.SCRIPT_CONSUMED_BY_RENDER,
            script_text=script_text,
            source_stage=ScriptSourceStage.UNKNOWN,
            script_version=max(1, int(self._current_version or 1)),
            generation_attempt=max(0, int(self._current_version or 0)),
            regeneration_reason=None,
            prompt_metadata={},
            planning_context_id=None,
            blueprint_id=None,
            blueprint_hash=None,
            parent_script_hash=self._current_script_hash,
            supersedes_script_hash=None,
            finalized_at=None,
        )
        return self.store.append(row)

    def record_consumed_by_shorts(self, script_text: str) -> ScriptLineageAppendResult:
        self._shorts_consumed = True
        row = self._build_record(
            event_type=ScriptLineageEventType.SCRIPT_CONSUMED_BY_SHORTS,
            script_text=script_text,
            source_stage=ScriptSourceStage.UNKNOWN,
            script_version=max(1, int(self._current_version or 1)),
            generation_attempt=max(0, int(self._current_version or 0)),
            regeneration_reason=None,
            prompt_metadata={},
            planning_context_id=None,
            blueprint_id=None,
            blueprint_hash=None,
            parent_script_hash=self._current_script_hash,
            supersedes_script_hash=None,
            finalized_at=None,
        )
        return self.store.append(row)

    def record_linked_to_upload(self, script_text: str) -> ScriptLineageAppendResult:
        self._upload_linked = True
        row = self._build_record(
            event_type=ScriptLineageEventType.SCRIPT_LINKED_TO_UPLOAD,
            script_text=script_text,
            source_stage=ScriptSourceStage.UNKNOWN,
            script_version=max(1, int(self._current_version or 1)),
            generation_attempt=max(0, int(self._current_version or 0)),
            regeneration_reason=None,
            prompt_metadata={},
            planning_context_id=None,
            blueprint_id=None,
            blueprint_hash=None,
            parent_script_hash=self._current_script_hash,
            supersedes_script_hash=None,
            finalized_at=None,
        )
        return self.store.append(row)

    def record_invalidated(self, script_text: str, *, reason: str | None = None) -> ScriptLineageAppendResult:
        row = self._build_record(
            event_type=ScriptLineageEventType.SCRIPT_INVALIDATED,
            script_text=script_text,
            source_stage=ScriptSourceStage.UNKNOWN,
            script_version=max(1, int(self._current_version or 1)),
            generation_attempt=max(0, int(self._current_version or 0)),
            regeneration_reason=_safe_text(reason) or "invalidated",
            prompt_metadata={},
            planning_context_id=None,
            blueprint_id=None,
            blueprint_hash=None,
            parent_script_hash=self._current_script_hash,
            supersedes_script_hash=None,
            finalized_at=None,
        )
        return self.store.append(row)


def replay_script_lineage_state(
    *,
    events: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], ScriptLineageReplayDiagnostics]:
    state: dict[str, dict[str, Any]] = {}
    errors: list[str] = []

    for event in events:
        try:
            row = validate_script_lineage_row(event)
            key = f"{row['content_id']}::{row['run_id']}"
            entity = state.setdefault(
                key,
                {
                    "content_id": row["content_id"],
                    "run_id": row["run_id"],
                    "versions": {},
                    "final_script_hash": None,
                    "render_consumed": False,
                    "shorts_consumed": False,
                    "upload_result_linked": False,
                },
            )
            script_hash = str(row.get("script_hash") or "")
            version = int(row.get("script_version") or 0)

            versions = dict(entity.get("versions") or {})
            if script_hash:
                versions[script_hash] = {
                    "script_hash": script_hash,
                    "script_version": version,
                    "completeness": row.get("script_completeness_state"),
                    "source_stage": row.get("script_source_stage"),
                    "supersedes": row.get("supersedes_script_hash"),
                    "invalidated": False,
                }
            entity["versions"] = versions

            event_type = ScriptLineageEventType(str(row.get("event_type") or ""))
            if event_type == ScriptLineageEventType.SCRIPT_FINALIZED:
                entity["final_script_hash"] = script_hash
            elif event_type == ScriptLineageEventType.SCRIPT_CONSUMED_BY_RENDER:
                entity["render_consumed"] = True
            elif event_type == ScriptLineageEventType.SCRIPT_CONSUMED_BY_SHORTS:
                entity["shorts_consumed"] = True
            elif event_type == ScriptLineageEventType.SCRIPT_LINKED_TO_UPLOAD:
                entity["upload_result_linked"] = True
            elif event_type == ScriptLineageEventType.SCRIPT_INVALIDATED and script_hash in versions:
                versions[script_hash]["invalidated"] = True
        except Exception as exc:
            errors.append(str(exc))

    return state, ScriptLineageReplayDiagnostics(malformed_rows=0, replay_errors=errors)


def reconstruct_current_final_scripts(*, evidence_path: Path | str = DEFAULT_EVIDENCE_PATH) -> tuple[dict[str, dict[str, Any]], ScriptLineageReplayDiagnostics]:
    events, malformed, _errors = load_script_lineage_rows(input_path=evidence_path, limit=0)
    state, diagnostics = replay_script_lineage_state(events=events)
    diagnostics.malformed_rows = malformed
    return state, diagnostics


def classify_legacy_sample(
    *,
    runtime_row: dict[str, Any] | None,
    ownership_row: dict[str, Any] | None,
) -> str:
    runtime = dict(runtime_row or {})
    ownership = dict(ownership_row or {})

    script = _safe_text(runtime.get("script") or ((runtime.get("metadata") or {}).get("script")))
    preview = _safe_text(ownership.get("script_preview"))

    content_id_runtime = _safe_text(runtime.get("generation_id") or runtime.get("content_id"))
    content_id_ownership = _safe_text(ownership.get("content_id"))

    if script and len(script) >= 120 and content_id_runtime and content_id_ownership and content_id_runtime == content_id_ownership:
        return "full_script_recoverable"
    if preview and len(preview) >= 20 and not script:
        if content_id_runtime and content_id_ownership and content_id_runtime != content_id_ownership:
            return "ambiguous"
        return "preview_only"
    if content_id_runtime and (runtime.get("script_hash") or runtime.get("generation_id")):
        return "hash_only_recoverable"
    if (content_id_runtime and content_id_ownership and content_id_runtime != content_id_ownership) or (preview and content_id_ownership and not content_id_runtime):
        return "ambiguous"
    return "unrecoverable"


def build_legacy_import_assessment(
    *,
    runtime_evidence_dir: Path | str = Path("output/runtime/evidence"),
    ownership_dir: Path | str = Path("output/state/content_ownership"),
    limit: int = 300,
) -> LegacyImportAssessment:
    runtime_dir = Path(runtime_evidence_dir)
    ownership_root = Path(ownership_dir)

    runtime_paths = sorted(runtime_dir.glob("content_*.json"))[: max(0, int(limit))]

    ownership_by_content: dict[str, dict[str, Any]] = {}
    for path in ownership_root.glob("content_*_run_*.json"):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        content_id = _safe_text(row.get("content_id"))
        if not content_id:
            continue
        current = ownership_by_content.get(content_id)
        preview = _safe_text(row.get("script_preview"))
        if current is None or len(preview) > len(_safe_text(current.get("script_preview"))):
            ownership_by_content[content_id] = row

    counts = {
        "full_script_recoverable": 0,
        "preview_only": 0,
        "hash_only_recoverable": 0,
        "ambiguous": 0,
        "unrecoverable": 0,
    }
    records: list[dict[str, Any]] = []

    for path in runtime_paths:
        runtime_row: dict[str, Any] = {}
        try:
            runtime_row = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            runtime_row = {}
        runtime_row.setdefault("content_id", path.stem)
        content_id = _safe_text(runtime_row.get("generation_id") or runtime_row.get("content_id") or path.stem)
        ownership_row = ownership_by_content.get(content_id)
        classification = classify_legacy_sample(runtime_row=runtime_row, ownership_row=ownership_row)
        counts[classification] += 1

        records.append(
            {
                "content_id": content_id,
                "classification": classification,
                "runtime_available": bool(runtime_row),
                "ownership_available": bool(ownership_row),
                "script_preview_length": len(_safe_text((ownership_row or {}).get("script_preview"))),
                "advisory_only": True,
                "pipeline_output_changed": False,
            }
        )

    return LegacyImportAssessment(
        sample_count=len(runtime_paths),
        full_script_recoverable=counts["full_script_recoverable"],
        preview_only=counts["preview_only"],
        hash_only_recoverable=counts["hash_only_recoverable"],
        ambiguous=counts["ambiguous"],
        unrecoverable=counts["unrecoverable"],
        records=records,
    )


def run_legacy_import_dry_run(
    *,
    output_path: Path | str,
    runtime_evidence_dir: Path | str = Path("output/runtime/evidence"),
    ownership_dir: Path | str = Path("output/state/content_ownership"),
    limit: int = 300,
    dry_run: bool = True,
) -> dict[str, Any]:
    assessment = build_legacy_import_assessment(
        runtime_evidence_dir=runtime_evidence_dir,
        ownership_dir=ownership_dir,
        limit=limit,
    )
    payload = assessment.to_dict()
    payload["dry_run"] = bool(dry_run)

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2), encoding="utf-8")
    return payload
