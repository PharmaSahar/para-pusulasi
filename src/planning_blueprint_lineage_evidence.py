from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
from typing import Any


PLANNING_LINEAGE_SCHEMA_VERSION = "v1"
DEFAULT_PLANNING_LINEAGE_PATH = Path("logs/planning_blueprint_lineage_evidence.jsonl")


class PlanningLineageLinkStatus(str, Enum):
    LINKED = "LINKED"
    PARTIAL = "PARTIAL"
    MISSING = "MISSING"
    AMBIGUOUS = "AMBIGUOUS"
    INVALID = "INVALID"


class PlanningLineageSourceStage(str, Enum):
    INITIAL_GENERATION = "INITIAL_GENERATION"
    FACT_CHECK_REGENERATION = "FACT_CHECK_REGENERATION"
    QUALITY_REGENERATION = "QUALITY_REGENERATION"
    FINALIZED = "FINALIZED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class PlanningLineageRecord:
    schema_version: str
    evidence_id: str
    planning_context_id: str | None
    blueprint_id: str | None
    blueprint_hash: str | None
    prompt_metadata_hash: str | None
    experiment_id: str | None
    content_id: str
    run_id: str
    script_hash: str
    link_status: str
    source_stage: str
    generation_attempt: int
    created_at: str
    advisory_only: bool
    pipeline_output_changed: bool

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "evidence_id": self.evidence_id,
            "planning_context_id": self.planning_context_id,
            "blueprint_id": self.blueprint_id,
            "blueprint_hash": self.blueprint_hash,
            "prompt_metadata_hash": self.prompt_metadata_hash,
            "experiment_id": self.experiment_id,
            "content_id": self.content_id,
            "run_id": self.run_id,
            "script_hash": self.script_hash,
            "link_status": self.link_status,
            "source_stage": self.source_stage,
            "generation_attempt": int(self.generation_attempt),
            "created_at": self.created_at,
            "advisory_only": bool(self.advisory_only),
            "pipeline_output_changed": bool(self.pipeline_output_changed),
        }
        return validate_planning_lineage_row(payload)


@dataclass(frozen=True)
class PlanningLineageAppendResult:
    appended: bool
    duplicate: bool
    reason: str


@dataclass(frozen=True)
class PlanningLineageReplayDiagnostics:
    malformed_rows: int
    replay_errors: list[str]


@dataclass(frozen=True)
class PlanningIdentifierAudit:
    generated_at: str
    sample_count: int
    canonical_ids: dict[str, int]
    duplicate_ids: dict[str, int]
    missing_ids: dict[str, int]
    inferred_ids: dict[str, int]
    advisory_only: bool
    pipeline_output_changed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "sample_count": int(self.sample_count),
            "canonical_ids": dict(self.canonical_ids),
            "duplicate_ids": dict(self.duplicate_ids),
            "missing_ids": dict(self.missing_ids),
            "inferred_ids": dict(self.inferred_ids),
            "advisory_only": bool(self.advisory_only),
            "pipeline_output_changed": bool(self.pipeline_output_changed),
        }


@dataclass(frozen=True)
class PlanningHistoricalAssessment:
    sample_count: int
    linked: int
    partial: int
    missing: int
    ambiguous: int
    invalid: int
    planning_linked: int
    blueprint_linked: int
    prompt_metadata_linked: int
    fully_traceable: int
    advisory_only: bool
    pipeline_output_changed: bool
    records: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_count": int(self.sample_count),
            "linked": int(self.linked),
            "partial": int(self.partial),
            "missing": int(self.missing),
            "ambiguous": int(self.ambiguous),
            "invalid": int(self.invalid),
            "planning_linked": int(self.planning_linked),
            "blueprint_linked": int(self.blueprint_linked),
            "prompt_metadata_linked": int(self.prompt_metadata_linked),
            "fully_traceable": int(self.fully_traceable),
            "advisory_only": bool(self.advisory_only),
            "pipeline_output_changed": bool(self.pipeline_output_changed),
            "records": list(self.records),
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _is_enabled(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def planning_blueprint_lineage_evidence_enabled() -> bool:
    return _is_enabled(os.getenv("PLANNING_BLUEPRINT_LINEAGE_EVIDENCE_ENABLED", "false"))


def hash_text(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def extract_prompt_metadata_hash(prompt_metadata: dict[str, Any] | None) -> tuple[str | None, bool]:
    payload = dict(prompt_metadata or {})
    prompt_hash = _safe_text(payload.get("prompt_hash"))
    safe_prompt = payload.get("safe_prompt")
    safe_prompt_hash = _safe_text((safe_prompt or {}).get("prompt_hash")) if isinstance(safe_prompt, dict) else ""

    if prompt_hash and safe_prompt_hash and prompt_hash != safe_prompt_hash:
        return None, True
    if prompt_hash:
        return prompt_hash, False
    if safe_prompt_hash:
        return safe_prompt_hash, False
    return None, False


def compute_planning_lineage_evidence_id(
    *,
    planning_context_id: str | None,
    blueprint_id: str | None,
    blueprint_hash: str | None,
    prompt_metadata_hash: str | None,
    experiment_id: str | None,
    content_id: str,
    run_id: str,
    script_hash: str,
    source_stage: PlanningLineageSourceStage,
    generation_attempt: int,
) -> str:
    raw = "|".join(
        [
            _safe_text(planning_context_id),
            _safe_text(blueprint_id),
            _safe_text(blueprint_hash),
            _safe_text(prompt_metadata_hash),
            _safe_text(experiment_id),
            _safe_text(content_id),
            _safe_text(run_id),
            _safe_text(script_hash),
            source_stage.value,
            str(int(generation_attempt)),
        ]
    )
    return "pble_" + hash_text(raw)[:24]


def resolve_planning_link_status(
    *,
    planning_context_id: str | None,
    blueprint_id: str | None,
    blueprint_hash: str | None,
    prompt_metadata_hash: str | None,
    content_id: str,
    run_id: str,
    script_hash: str,
    prompt_hash_conflict: bool = False,
) -> PlanningLineageLinkStatus:
    cid = _safe_text(content_id)
    rid = _safe_text(run_id)
    shash = _safe_text(script_hash)
    planning = _safe_text(planning_context_id)
    bp_id = _safe_text(blueprint_id)
    bp_hash = _safe_text(blueprint_hash)
    prompt_hash = _safe_text(prompt_metadata_hash)

    if not cid or not rid or not shash:
        return PlanningLineageLinkStatus.INVALID
    if prompt_hash_conflict:
        return PlanningLineageLinkStatus.AMBIGUOUS
    if planning and planning != rid:
        return PlanningLineageLinkStatus.AMBIGUOUS

    present = [bool(planning), bool(bp_id), bool(bp_hash), bool(prompt_hash)]
    if all(present):
        return PlanningLineageLinkStatus.LINKED
    if any(present):
        return PlanningLineageLinkStatus.PARTIAL
    return PlanningLineageLinkStatus.MISSING


def validate_planning_lineage_row(row: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ValueError("invalid_payload")

    required = [
        "schema_version",
        "evidence_id",
        "planning_context_id",
        "blueprint_id",
        "blueprint_hash",
        "prompt_metadata_hash",
        "experiment_id",
        "content_id",
        "run_id",
        "script_hash",
        "link_status",
        "source_stage",
        "generation_attempt",
        "created_at",
        "advisory_only",
        "pipeline_output_changed",
    ]
    for key in required:
        if key not in row:
            raise ValueError(f"missing_field:{key}")

    if _safe_text(row.get("schema_version")) != PLANNING_LINEAGE_SCHEMA_VERSION:
        raise ValueError("invalid_field:schema_version")

    try:
        PlanningLineageLinkStatus(_safe_text(row.get("link_status")))
        PlanningLineageSourceStage(_safe_text(row.get("source_stage")))
    except Exception as exc:
        raise ValueError("invalid_enum") from exc

    if not _safe_text(row.get("evidence_id")):
        raise ValueError("missing_field:evidence_id")
    if not _safe_text(row.get("content_id")):
        raise ValueError("missing_field:content_id")
    if not _safe_text(row.get("run_id")):
        raise ValueError("missing_field:run_id")
    if not _safe_text(row.get("script_hash")):
        raise ValueError("missing_field:script_hash")

    created_at = _safe_text(row.get("created_at"))
    try:
        datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except Exception as exc:
        raise ValueError("invalid_field:created_at") from exc

    if not bool(row.get("advisory_only")):
        raise ValueError("invalid_field:advisory_only")
    if bool(row.get("pipeline_output_changed")):
        raise ValueError("invalid_field:pipeline_output_changed")

    normalized = dict(row)
    normalized["generation_attempt"] = int(row.get("generation_attempt") or 0)
    normalized["advisory_only"] = bool(row.get("advisory_only"))
    normalized["pipeline_output_changed"] = bool(row.get("pipeline_output_changed"))
    for key in [
        "planning_context_id",
        "blueprint_id",
        "blueprint_hash",
        "prompt_metadata_hash",
        "experiment_id",
    ]:
        value = _safe_text(normalized.get(key))
        normalized[key] = value or None
    return normalized


def load_planning_lineage_rows(
    *,
    input_path: Path | str = DEFAULT_PLANNING_LINEAGE_PATH,
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
            rows.append(validate_planning_lineage_row(decoded))
        except Exception as exc:
            malformed += 1
            errors.append(f"line={index}:{exc}")

    if limit > 0:
        rows = rows[-limit:]
    return rows, malformed, errors


class PlanningLineageEvidenceStore:
    def __init__(self, *, evidence_path: Path | str = DEFAULT_PLANNING_LINEAGE_PATH):
        self.evidence_path = Path(evidence_path)
        self._known_ids: set[str] | None = None

    def _ensure_known_ids(self) -> set[str]:
        if self._known_ids is not None:
            return self._known_ids
        rows, _malformed, _errors = load_planning_lineage_rows(input_path=self.evidence_path, limit=0)
        self._known_ids = {_safe_text(row.get("evidence_id")) for row in rows if _safe_text(row.get("evidence_id"))}
        return self._known_ids

    def append(self, row: dict[str, Any]) -> PlanningLineageAppendResult:
        payload = validate_planning_lineage_row(row)
        known = self._ensure_known_ids()
        evidence_id = _safe_text(payload.get("evidence_id"))
        if evidence_id in known:
            return PlanningLineageAppendResult(appended=False, duplicate=True, reason="duplicate_evidence_id")

        self.evidence_path.parent.mkdir(parents=True, exist_ok=True)
        blob = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
        fd = os.open(self.evidence_path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
        try:
            os.write(fd, blob.encode("utf-8"))
        finally:
            os.close(fd)

        known.add(evidence_id)
        return PlanningLineageAppendResult(appended=True, duplicate=False, reason="appended")


class PlanningLineageRecorder:
    def __init__(
        self,
        *,
        content_id: str,
        run_id: str,
        experiment_id: str | None,
        evidence_path: Path | str | None = None,
    ):
        self.content_id = _safe_text(content_id)
        self.run_id = _safe_text(run_id)
        self.experiment_id = _safe_text(experiment_id) or None
        self.store = PlanningLineageEvidenceStore(
            evidence_path=evidence_path or os.getenv("PLANNING_BLUEPRINT_LINEAGE_EVIDENCE_PATH", str(DEFAULT_PLANNING_LINEAGE_PATH))
        )

    def record_linkage(
        self,
        *,
        planning_context_id: str | None,
        blueprint_id: str | None,
        blueprint_hash: str | None,
        prompt_metadata: dict[str, Any] | None,
        script_text: str,
        source_stage: PlanningLineageSourceStage,
        generation_attempt: int,
    ) -> PlanningLineageAppendResult:
        prompt_hash, prompt_hash_conflict = extract_prompt_metadata_hash(prompt_metadata)
        script_hash = hash_text(str(script_text or ""))
        status = resolve_planning_link_status(
            planning_context_id=planning_context_id,
            blueprint_id=blueprint_id,
            blueprint_hash=blueprint_hash,
            prompt_metadata_hash=prompt_hash,
            content_id=self.content_id,
            run_id=self.run_id,
            script_hash=script_hash,
            prompt_hash_conflict=prompt_hash_conflict,
        )
        evidence_id = compute_planning_lineage_evidence_id(
            planning_context_id=planning_context_id,
            blueprint_id=blueprint_id,
            blueprint_hash=blueprint_hash,
            prompt_metadata_hash=prompt_hash,
            experiment_id=self.experiment_id,
            content_id=self.content_id,
            run_id=self.run_id,
            script_hash=script_hash,
            source_stage=source_stage,
            generation_attempt=generation_attempt,
        )
        row = PlanningLineageRecord(
            schema_version=PLANNING_LINEAGE_SCHEMA_VERSION,
            evidence_id=evidence_id,
            planning_context_id=_safe_text(planning_context_id) or None,
            blueprint_id=_safe_text(blueprint_id) or None,
            blueprint_hash=_safe_text(blueprint_hash) or None,
            prompt_metadata_hash=prompt_hash,
            experiment_id=self.experiment_id,
            content_id=self.content_id,
            run_id=self.run_id,
            script_hash=script_hash,
            link_status=status.value,
            source_stage=source_stage.value,
            generation_attempt=max(0, int(generation_attempt)),
            created_at=_now_iso(),
            advisory_only=True,
            pipeline_output_changed=False,
        ).to_dict()
        return self.store.append(row)


def replay_planning_lineage_state(
    *,
    events: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], PlanningLineageReplayDiagnostics]:
    state: dict[str, dict[str, Any]] = {}
    errors: list[str] = []

    for event in events:
        try:
            row = validate_planning_lineage_row(event)
            key = f"{row['content_id']}::{row['run_id']}"
            entry = state.setdefault(
                key,
                {
                    "content_id": row["content_id"],
                    "run_id": row["run_id"],
                    "latest_created_at": "",
                    "latest_link_status": PlanningLineageLinkStatus.MISSING.value,
                    "planning_context_id": None,
                    "blueprint_id": None,
                    "blueprint_hash": None,
                    "prompt_metadata_hash": None,
                    "script_hashes": [],
                    "fully_traceable": False,
                },
            )

            created_at = _safe_text(row.get("created_at"))
            script_hashes = set(str(x) for x in list(entry.get("script_hashes") or []))
            script_hashes.add(_safe_text(row.get("script_hash")))
            entry["script_hashes"] = sorted(h for h in script_hashes if h)

            if created_at >= _safe_text(entry.get("latest_created_at")):
                entry["latest_created_at"] = created_at
                entry["latest_link_status"] = _safe_text(row.get("link_status"))
                entry["planning_context_id"] = row.get("planning_context_id")
                entry["blueprint_id"] = row.get("blueprint_id")
                entry["blueprint_hash"] = row.get("blueprint_hash")
                entry["prompt_metadata_hash"] = row.get("prompt_metadata_hash")

            entry["fully_traceable"] = bool(
                entry.get("planning_context_id")
                and entry.get("blueprint_id")
                and entry.get("blueprint_hash")
                and entry.get("prompt_metadata_hash")
                and entry.get("script_hashes")
                and entry.get("latest_link_status") == PlanningLineageLinkStatus.LINKED.value
            )
        except Exception as exc:
            errors.append(str(exc))

    return state, PlanningLineageReplayDiagnostics(malformed_rows=0, replay_errors=errors)


def reconstruct_planning_lineage_state(
    *,
    evidence_path: Path | str = DEFAULT_PLANNING_LINEAGE_PATH,
) -> tuple[dict[str, dict[str, Any]], PlanningLineageReplayDiagnostics]:
    rows, malformed, _errors = load_planning_lineage_rows(input_path=evidence_path, limit=0)
    state, diagnostics = replay_planning_lineage_state(events=rows)
    return state, PlanningLineageReplayDiagnostics(malformed_rows=malformed, replay_errors=list(diagnostics.replay_errors))


def _safe_load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def build_identifier_audit(
    *,
    planning_path: Path | str = Path("logs/shadow_generation_planning.jsonl"),
    alignment_path: Path | str = Path("logs/shadow_blueprint_prompt_alignment.jsonl"),
    script_lineage_path: Path | str = Path("logs/script_lineage_evidence.jsonl"),
    runtime_evidence_dir: Path | str = Path("output/runtime/evidence"),
    ownership_dir: Path | str = Path("output/state/content_ownership"),
    limit: int = 300,
) -> PlanningIdentifierAudit:
    planning_rows, _planning_malformed = _load_jsonl(Path(planning_path), limit=limit)
    alignment_rows, _alignment_malformed = _load_jsonl(Path(alignment_path), limit=limit)
    script_rows, _script_malformed = _load_jsonl(Path(script_lineage_path), limit=limit)

    runtime_paths = sorted(Path(runtime_evidence_dir).glob("content_*.json"))[: max(0, int(limit))]
    ownership_paths = sorted(Path(ownership_dir).glob("content_*_run_*.json"))[: max(0, int(limit))]

    canonical = {
        "planning_context_id": 0,
        "blueprint_id": 0,
        "blueprint_hash": 0,
        "prompt_metadata_hash": 0,
        "experiment_id": 0,
        "content_id": 0,
        "run_id": 0,
        "ownership_id": 0,
    }
    missing = {
        "planning_context_id": 0,
        "blueprint_id": 0,
        "blueprint_hash": 0,
        "prompt_metadata_hash": 0,
        "experiment_id": 0,
        "content_id": 0,
        "run_id": 0,
        "ownership_id": 0,
    }
    inferred = {
        "planning_context_id": 0,
        "blueprint_id": 0,
        "blueprint_hash": 0,
        "prompt_metadata_hash": 0,
        "experiment_id": 0,
        "content_id": 0,
        "run_id": 0,
        "ownership_id": 0,
    }

    planning_by_run: dict[str, set[str]] = {}
    prompt_by_run: dict[str, set[str]] = {}
    script_by_content_run: dict[str, set[str]] = {}

    for row in planning_rows:
        run_id = _safe_text(row.get("run_id"))
        blueprint_id = _safe_text(row.get("blueprint_id"))
        blueprint_hash = _safe_text(row.get("blueprint_hash"))
        if run_id:
            canonical["planning_context_id"] += 1
            canonical["run_id"] += 1
        else:
            missing["planning_context_id"] += 1
            missing["run_id"] += 1
        if blueprint_id:
            canonical["blueprint_id"] += 1
        else:
            missing["blueprint_id"] += 1
        if blueprint_hash:
            canonical["blueprint_hash"] += 1
        else:
            missing["blueprint_hash"] += 1

        if run_id and blueprint_id:
            planning_by_run.setdefault(run_id, set()).add(blueprint_id)

    for row in alignment_rows:
        run_id = _safe_text(row.get("run_id"))
        prompt_hash = _safe_text(row.get("prompt_hash"))
        if prompt_hash:
            canonical["prompt_metadata_hash"] += 1
        else:
            missing["prompt_metadata_hash"] += 1
        if run_id and prompt_hash:
            prompt_by_run.setdefault(run_id, set()).add(prompt_hash)

    for row in script_rows:
        content_id = _safe_text(row.get("content_id"))
        run_id = _safe_text(row.get("run_id"))
        script_hash = _safe_text(row.get("script_hash"))
        experiment_id = _safe_text(row.get("experiment_id"))
        planning_context_id = _safe_text(row.get("planning_context_id"))
        blueprint_id = _safe_text(row.get("blueprint_id"))
        blueprint_hash = _safe_text(row.get("blueprint_hash"))
        prompt_hash = _safe_text(row.get("prompt_metadata_hash"))

        if content_id:
            canonical["content_id"] += 1
        else:
            missing["content_id"] += 1
        if run_id:
            canonical["run_id"] += 1
        else:
            missing["run_id"] += 1
        if experiment_id:
            canonical["experiment_id"] += 1
        else:
            missing["experiment_id"] += 1
        if prompt_hash:
            canonical["prompt_metadata_hash"] += 1
        else:
            missing["prompt_metadata_hash"] += 1

        if planning_context_id == run_id and not blueprint_id and not blueprint_hash:
            inferred["planning_context_id"] += 1

        if content_id and run_id and script_hash:
            key = f"{content_id}::{run_id}"
            script_by_content_run.setdefault(key, set()).add(script_hash)

    for path in runtime_paths:
        row = _safe_load_json(path)
        content_id = _safe_text(row.get("generation_id") or row.get("content_id"))
        run_id = _safe_text(row.get("run_id"))
        if content_id:
            canonical["content_id"] += 1
        else:
            missing["content_id"] += 1
        if run_id:
            canonical["run_id"] += 1
        else:
            missing["run_id"] += 1

    for path in ownership_paths:
        row = _safe_load_json(path)
        content_id = _safe_text(row.get("content_id"))
        run_id = _safe_text(row.get("run_id"))
        if content_id and run_id:
            canonical["ownership_id"] += 1
        else:
            missing["ownership_id"] += 1

    duplicate = {
        "planning_context_id": 0,
        "blueprint_id": sum(1 for values in planning_by_run.values() if len(values) > 1),
        "blueprint_hash": 0,
        "prompt_metadata_hash": sum(1 for values in prompt_by_run.values() if len(values) > 1),
        "experiment_id": 0,
        "content_id": 0,
        "run_id": 0,
        "ownership_id": 0,
    }
    duplicate["content_id"] = sum(1 for values in script_by_content_run.values() if len(values) > 1)

    sample_count = max(
        len(runtime_paths),
        len(script_rows),
        len(planning_rows),
        len(alignment_rows),
    )

    return PlanningIdentifierAudit(
        generated_at=_now_iso(),
        sample_count=int(sample_count),
        canonical_ids=canonical,
        duplicate_ids=duplicate,
        missing_ids=missing,
        inferred_ids=inferred,
        advisory_only=True,
        pipeline_output_changed=False,
    )


def _load_jsonl(path: Path, *, limit: int) -> tuple[list[dict[str, Any]], int]:
    if not path.exists():
        return [], 0
    rows: list[dict[str, Any]] = []
    malformed = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            decoded = json.loads(line)
            if isinstance(decoded, dict):
                rows.append(decoded)
        except Exception:
            malformed += 1
    if limit > 0:
        rows = rows[-limit:]
    return rows, malformed


def build_historical_planning_lineage_assessment(
    *,
    runtime_evidence_dir: Path | str = Path("output/runtime/evidence"),
    planning_path: Path | str = Path("logs/shadow_generation_planning.jsonl"),
    alignment_path: Path | str = Path("logs/shadow_blueprint_prompt_alignment.jsonl"),
    script_lineage_path: Path | str = Path("logs/script_lineage_evidence.jsonl"),
    limit: int = 300,
) -> PlanningHistoricalAssessment:
    planning_rows, _ = _load_jsonl(Path(planning_path), limit=0)
    alignment_rows, _ = _load_jsonl(Path(alignment_path), limit=0)
    script_rows, _ = _load_jsonl(Path(script_lineage_path), limit=0)

    planning_by_run: dict[str, list[dict[str, Any]]] = {}
    for row in planning_rows:
        run_id = _safe_text(row.get("run_id"))
        if run_id:
            planning_by_run.setdefault(run_id, []).append(row)

    alignment_by_run: dict[str, list[dict[str, Any]]] = {}
    for row in alignment_rows:
        run_id = _safe_text(row.get("run_id"))
        if run_id:
            alignment_by_run.setdefault(run_id, []).append(row)

    script_by_content_run: dict[str, list[dict[str, Any]]] = {}
    for row in script_rows:
        key = f"{_safe_text(row.get('content_id'))}::{_safe_text(row.get('run_id'))}"
        if key != "::":
            script_by_content_run.setdefault(key, []).append(row)

    runtime_paths = sorted(Path(runtime_evidence_dir).glob("content_*.json"))[: max(0, int(limit))]

    counts = {
        "linked": 0,
        "partial": 0,
        "missing": 0,
        "ambiguous": 0,
        "invalid": 0,
    }
    planning_linked = 0
    blueprint_linked = 0
    prompt_linked = 0
    fully_traceable = 0
    records: list[dict[str, Any]] = []

    for path in runtime_paths:
        runtime_row = _safe_load_json(path)
        content_id = _safe_text(runtime_row.get("generation_id") or runtime_row.get("content_id"))
        run_id = _safe_text(runtime_row.get("run_id"))
        script_hash = _safe_text(runtime_row.get("script_hash"))
        if not content_id:
            content_id = path.stem

        planning_candidates = planning_by_run.get(run_id, []) if run_id else []
        alignment_candidates = alignment_by_run.get(run_id, []) if run_id else []
        script_candidates = script_by_content_run.get(f"{content_id}::{run_id}", []) if (content_id and run_id) else []

        planning_context_candidates = {_safe_text(item.get("run_id")) for item in planning_candidates if _safe_text(item.get("run_id"))}
        blueprint_id_candidates = {_safe_text(item.get("blueprint_id")) for item in planning_candidates if _safe_text(item.get("blueprint_id"))}
        blueprint_hash_candidates = {_safe_text(item.get("blueprint_hash")) for item in planning_candidates if _safe_text(item.get("blueprint_hash"))}
        prompt_hash_candidates = {_safe_text(item.get("prompt_hash")) for item in alignment_candidates if _safe_text(item.get("prompt_hash"))}

        script_prompt_candidates = {_safe_text(item.get("prompt_metadata_hash")) for item in script_candidates if _safe_text(item.get("prompt_metadata_hash"))}
        if not prompt_hash_candidates and script_prompt_candidates:
            prompt_hash_candidates = set(script_prompt_candidates)
        elif prompt_hash_candidates and script_prompt_candidates and prompt_hash_candidates != script_prompt_candidates:
            prompt_hash_candidates = prompt_hash_candidates | script_prompt_candidates

        if not script_hash and script_candidates:
            script_hashes = {_safe_text(item.get("script_hash")) for item in script_candidates if _safe_text(item.get("script_hash"))}
            if len(script_hashes) == 1:
                script_hash = next(iter(script_hashes))

        planning_context_id = next(iter(planning_context_candidates)) if len(planning_context_candidates) == 1 else None
        blueprint_id = next(iter(blueprint_id_candidates)) if len(blueprint_id_candidates) == 1 else None
        blueprint_hash = next(iter(blueprint_hash_candidates)) if len(blueprint_hash_candidates) == 1 else None
        prompt_hash = next(iter(prompt_hash_candidates)) if len(prompt_hash_candidates) == 1 else None

        ambiguous = any(
            len(candidates) > 1
            for candidates in [
                planning_context_candidates,
                blueprint_id_candidates,
                blueprint_hash_candidates,
                prompt_hash_candidates,
            ]
        )

        status = resolve_planning_link_status(
            planning_context_id=planning_context_id,
            blueprint_id=blueprint_id,
            blueprint_hash=blueprint_hash,
            prompt_metadata_hash=prompt_hash,
            content_id=content_id,
            run_id=run_id,
            script_hash=script_hash,
            prompt_hash_conflict=ambiguous,
        )
        counts[status.value.lower()] += 1

        if planning_context_id:
            planning_linked += 1
        if blueprint_id and blueprint_hash:
            blueprint_linked += 1
        if prompt_hash:
            prompt_linked += 1
        if status == PlanningLineageLinkStatus.LINKED:
            fully_traceable += 1

        records.append(
            {
                "content_id": content_id,
                "run_id": run_id or None,
                "script_hash": script_hash or None,
                "planning_context_id": planning_context_id,
                "blueprint_id": blueprint_id,
                "blueprint_hash": blueprint_hash,
                "prompt_metadata_hash": prompt_hash,
                "link_status": status.value,
                "advisory_only": True,
                "pipeline_output_changed": False,
            }
        )

    return PlanningHistoricalAssessment(
        sample_count=len(runtime_paths),
        linked=counts["linked"],
        partial=counts["partial"],
        missing=counts["missing"],
        ambiguous=counts["ambiguous"],
        invalid=counts["invalid"],
        planning_linked=planning_linked,
        blueprint_linked=blueprint_linked,
        prompt_metadata_linked=prompt_linked,
        fully_traceable=fully_traceable,
        advisory_only=True,
        pipeline_output_changed=False,
        records=records,
    )


def run_historical_planning_lineage_dry_run(
    *,
    output_path: Path | str,
    runtime_evidence_dir: Path | str = Path("output/runtime/evidence"),
    planning_path: Path | str = Path("logs/shadow_generation_planning.jsonl"),
    alignment_path: Path | str = Path("logs/shadow_blueprint_prompt_alignment.jsonl"),
    script_lineage_path: Path | str = Path("logs/script_lineage_evidence.jsonl"),
    limit: int = 300,
) -> dict[str, Any]:
    assessment = build_historical_planning_lineage_assessment(
        runtime_evidence_dir=runtime_evidence_dir,
        planning_path=planning_path,
        alignment_path=alignment_path,
        script_lineage_path=script_lineage_path,
        limit=limit,
    )
    payload = assessment.to_dict()
    payload["dry_run"] = True

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2), encoding="utf-8")
    return payload
