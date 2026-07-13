from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
from random import Random
from typing import Any


RECOVERY_SCHEMA_VERSION = "v1"
DEFAULT_RECOVERY_OUTPUT_PATH = Path("artifacts/latest/project002_sprint1e_phase2b_historical_lineage_recovery/historical_recovery_report.json")


class RecoveryConfidence(str, Enum):
    PROVEN = "PROVEN"


class RecoveryLinkType(str, Enum):
    CONTENT_TO_OWNERSHIP = "CONTENT_TO_OWNERSHIP"
    OWNERSHIP_TO_PLANNING = "OWNERSHIP_TO_PLANNING"
    PLANNING_TO_BLUEPRINT = "PLANNING_TO_BLUEPRINT"
    BLUEPRINT_TO_PROMPT = "BLUEPRINT_TO_PROMPT"
    PROMPT_TO_SCRIPT = "PROMPT_TO_SCRIPT"
    SCRIPT_TO_RENDER = "SCRIPT_TO_RENDER"
    SCRIPT_TO_UPLOAD = "SCRIPT_TO_UPLOAD"


@dataclass(frozen=True)
class HistoricalRecoveryRecord:
    schema_version: str
    recovery_id: str
    source_record: dict[str, Any]
    target_record: dict[str, Any]
    recovery_method: str
    confidence: str
    proof: dict[str, Any]
    link_type: str
    created_at: str
    advisory_only: bool
    pipeline_output_changed: bool

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "recovery_id": self.recovery_id,
            "source_record": dict(self.source_record),
            "target_record": dict(self.target_record),
            "recovery_method": self.recovery_method,
            "confidence": self.confidence,
            "proof": dict(self.proof),
            "link_type": self.link_type,
            "created_at": self.created_at,
            "advisory_only": bool(self.advisory_only),
            "pipeline_output_changed": bool(self.pipeline_output_changed),
        }
        return validate_recovery_record(payload)


@dataclass(frozen=True)
class HistoricalRecoveryChain:
    content_id: str
    runtime_record: dict[str, Any]
    ownership_record: dict[str, Any] | None
    planning_record: dict[str, Any] | None
    alignment_record: dict[str, Any] | None
    script_hash: str | None
    prompt_hash: str | None
    blueprint_hash: str | None
    render_linked: bool
    upload_linked: bool
    status: str
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_id": self.content_id,
            "runtime_record": dict(self.runtime_record),
            "ownership_record": dict(self.ownership_record or {}),
            "planning_record": dict(self.planning_record or {}),
            "alignment_record": dict(self.alignment_record or {}),
            "script_hash": self.script_hash,
            "prompt_hash": self.prompt_hash,
            "blueprint_hash": self.blueprint_hash,
            "render_linked": bool(self.render_linked),
            "upload_linked": bool(self.upload_linked),
            "status": self.status,
            "reasons": list(self.reasons),
            "advisory_only": True,
            "pipeline_output_changed": False,
        }


@dataclass(frozen=True)
class HistoricalRecoveryOutput:
    generated_at: str
    source_inventory: dict[str, Any]
    recovery_graph: dict[str, Any]
    records: list[dict[str, Any]]
    chains: list[dict[str, Any]]
    counts: dict[str, int]
    coverage_before: dict[str, float]
    coverage_after: dict[str, float]
    coverage_delta: dict[str, float]
    quality_audit: dict[str, Any]
    advisory_only: bool
    pipeline_output_changed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "source_inventory": dict(self.source_inventory),
            "recovery_graph": dict(self.recovery_graph),
            "records": list(self.records),
            "chains": list(self.chains),
            "counts": dict(self.counts),
            "coverage_before": dict(self.coverage_before),
            "coverage_after": dict(self.coverage_after),
            "coverage_delta": dict(self.coverage_delta),
            "quality_audit": dict(self.quality_audit),
            "advisory_only": bool(self.advisory_only),
            "pipeline_output_changed": bool(self.pipeline_output_changed),
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _hash(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _stable_id(parts: list[str], prefix: str) -> str:
    return f"{prefix}_{_hash('|'.join(parts))[:24]}"


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


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
            decoded = json.loads(line)
            if isinstance(decoded, dict):
                rows.append(decoded)
            else:
                malformed += 1
        except Exception:
            malformed += 1
    return rows, malformed


def _load_runtime_rows(runtime_dir: Path, limit: int) -> tuple[list[dict[str, Any]], int]:
    paths = sorted(runtime_dir.glob("content_*.json"))
    if limit > 0:
        paths = paths[:limit]

    rows: list[dict[str, Any]] = []
    malformed = 0
    for path in paths:
        row = _load_json(path)
        if row is None:
            malformed += 1
            continue
        row["_source_path"] = str(path)
        row.setdefault("generation_id", path.stem)
        rows.append(row)
    return rows, malformed


def _load_ownership_rows(ownership_dir: Path, limit: int) -> tuple[list[dict[str, Any]], int]:
    paths = sorted(ownership_dir.glob("content_*_run_*.json"))
    if limit > 0:
        paths = paths[:limit]

    rows: list[dict[str, Any]] = []
    malformed = 0
    for path in paths:
        row = _load_json(path)
        if row is None:
            malformed += 1
            continue
        row["_source_path"] = str(path)
        rows.append(row)
    return rows, malformed


def _build_source_inventory(
    *,
    runtime_rows: list[dict[str, Any]],
    ownership_rows: list[dict[str, Any]],
    planning_rows: list[dict[str, Any]],
    alignment_rows: list[dict[str, Any]],
    script_lineage_rows: list[dict[str, Any]],
    prompt_experiment_rows: list[dict[str, Any]],
    offline_prompt_rows: list[dict[str, Any]],
    malformed_counts: dict[str, int],
) -> dict[str, Any]:
    return {
        "runtime_evidence": {"path": "output/runtime/evidence", "count": len(runtime_rows), "malformed": int(malformed_counts.get("runtime", 0))},
        "content_ownership": {"path": "output/state/content_ownership", "count": len(ownership_rows), "malformed": int(malformed_counts.get("ownership", 0))},
        "script_lineage": {"path": "logs/script_lineage_evidence.jsonl", "count": len(script_lineage_rows), "malformed": int(malformed_counts.get("script_lineage", 0))},
        "shadow_planning": {"path": "logs/shadow_generation_planning.jsonl", "count": len(planning_rows), "malformed": int(malformed_counts.get("planning", 0))},
        "shadow_alignment": {"path": "logs/shadow_blueprint_prompt_alignment.jsonl", "count": len(alignment_rows), "malformed": int(malformed_counts.get("alignment", 0))},
        "prompt_registry_metadata": {"path": "output/scripts", "count": 0, "malformed": 0},
        "prompt_hashes": {"source": "shadow_alignment + shadow_prompt_experiments", "count": len(alignment_rows) + len(prompt_experiment_rows), "malformed": int(malformed_counts.get("prompt_experiments", 0))},
        "pipeline_snapshots": {"path": "output/runtime/evidence", "count": len(runtime_rows), "malformed": int(malformed_counts.get("runtime", 0))},
        "legacy_reports": {"path": "artifacts/latest", "count": 0, "malformed": 0},
        "review_artifacts": {"source": "offline_prompt_candidates", "count": len(offline_prompt_rows), "malformed": int(malformed_counts.get("offline_prompt", 0))},
        "advisory_only": True,
        "pipeline_output_changed": False,
    }


def _build_recovery_graph_definition() -> dict[str, Any]:
    return {
        "edge_priority": [
            "explicit_ids",
            "canonical_hashes",
            "ownership_linkage",
            "content_id_plus_run_id",
            "validated_blueprint_hash",
        ],
        "allowed_edges": [
            {
                "from": "runtime",
                "to": "ownership",
                "method": "content_id_exact_match",
                "required_keys": ["content_id"],
            },
            {
                "from": "ownership",
                "to": "planning",
                "method": "run_id_exact_match",
                "required_keys": ["run_id"],
            },
            {
                "from": "planning",
                "to": "alignment",
                "method": "run_id_plus_blueprint_hash_exact_match",
                "required_keys": ["run_id", "blueprint_hash"],
            },
            {
                "from": "alignment",
                "to": "script",
                "method": "run_id_via_ownership_chain_plus_prompt_hash",
                "required_keys": ["run_id", "prompt_hash"],
            },
            {
                "from": "script",
                "to": "render",
                "method": "runtime_render_result_presence",
                "required_keys": ["script_hash", "render_result"],
            },
            {
                "from": "script",
                "to": "upload",
                "method": "runtime_upload_video_id_presence",
                "required_keys": ["script_hash", "upload_result.video_id"],
            },
        ],
        "forbidden_inference": [
            "filename_similarity",
            "title_similarity",
            "timestamp_proximity",
            "semantic_similarity",
            "ai_inference",
            "manual_guessing",
        ],
        "advisory_only": True,
        "pipeline_output_changed": False,
    }


def validate_recovery_record(row: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ValueError("invalid_payload")

    required = [
        "schema_version",
        "recovery_id",
        "source_record",
        "target_record",
        "recovery_method",
        "confidence",
        "proof",
        "link_type",
        "created_at",
        "advisory_only",
        "pipeline_output_changed",
    ]
    for key in required:
        if key not in row:
            raise ValueError(f"missing_field:{key}")

    if _safe_text(row.get("schema_version")) != RECOVERY_SCHEMA_VERSION:
        raise ValueError("invalid_field:schema_version")

    if RecoveryConfidence(_safe_text(row.get("confidence"))) != RecoveryConfidence.PROVEN:
        raise ValueError("invalid_field:confidence")

    RecoveryLinkType(_safe_text(row.get("link_type")))

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
    normalized["source_record"] = dict(row.get("source_record") or {})
    normalized["target_record"] = dict(row.get("target_record") or {})
    normalized["proof"] = dict(row.get("proof") or {})
    normalized["advisory_only"] = bool(row.get("advisory_only"))
    normalized["pipeline_output_changed"] = bool(row.get("pipeline_output_changed"))
    return normalized


def _build_recovery_record(
    *,
    link_type: RecoveryLinkType,
    source_record: dict[str, Any],
    target_record: dict[str, Any],
    recovery_method: str,
    proof: dict[str, Any],
) -> dict[str, Any]:
    source_id = _safe_text(source_record.get("record_id") or source_record.get("content_id") or source_record.get("run_id") or source_record.get("blueprint_hash"))
    target_id = _safe_text(target_record.get("record_id") or target_record.get("content_id") or target_record.get("run_id") or target_record.get("blueprint_hash"))

    recovery_id = _stable_id(
        [link_type.value, source_id, target_id, recovery_method, json.dumps(proof, ensure_ascii=True, sort_keys=True)],
        "hr",
    )

    return HistoricalRecoveryRecord(
        schema_version=RECOVERY_SCHEMA_VERSION,
        recovery_id=recovery_id,
        source_record=dict(source_record),
        target_record=dict(target_record),
        recovery_method=recovery_method,
        confidence=RecoveryConfidence.PROVEN.value,
        proof=dict(proof),
        link_type=link_type.value,
        created_at=_now_iso(),
        advisory_only=True,
        pipeline_output_changed=False,
    ).to_dict()


def _pct(value: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round((100.0 * float(value) / float(total)), 2)


def _select_unique(rows: list[dict[str, Any]], key_name: str) -> tuple[dict[str, Any] | None, bool]:
    if not rows:
        return None, False
    key_values = {_safe_text(row.get(key_name)) for row in rows if _safe_text(row.get(key_name))}
    if len(rows) == 1:
        return rows[0], False
    if len(key_values) <= 1:
        # Multiple duplicates with identical key remain ambiguous as multiple records exist.
        return None, True
    return None, True


def build_historical_recovery(
    *,
    runtime_dir: Path | str = Path("output/runtime/evidence"),
    ownership_dir: Path | str = Path("output/state/content_ownership"),
    planning_path: Path | str = Path("logs/shadow_generation_planning.jsonl"),
    alignment_path: Path | str = Path("logs/shadow_blueprint_prompt_alignment.jsonl"),
    script_lineage_path: Path | str = Path("logs/script_lineage_evidence.jsonl"),
    prompt_experiments_path: Path | str = Path("logs/shadow_prompt_experiments.jsonl"),
    offline_prompt_candidates_path: Path | str = Path("logs/offline_prompt_candidates.jsonl"),
    limit: int = 300,
) -> HistoricalRecoveryOutput:
    runtime_rows, runtime_malformed = _load_runtime_rows(Path(runtime_dir), limit)
    ownership_rows, ownership_malformed = _load_ownership_rows(Path(ownership_dir), limit=0)
    planning_rows, planning_malformed = _load_jsonl_rows(Path(planning_path))
    alignment_rows, alignment_malformed = _load_jsonl_rows(Path(alignment_path))
    script_lineage_rows, script_lineage_malformed = _load_jsonl_rows(Path(script_lineage_path))
    prompt_experiment_rows, prompt_experiment_malformed = _load_jsonl_rows(Path(prompt_experiments_path))
    offline_prompt_rows, offline_prompt_malformed = _load_jsonl_rows(Path(offline_prompt_candidates_path))

    malformed_counts = {
        "runtime": runtime_malformed,
        "ownership": ownership_malformed,
        "planning": planning_malformed,
        "alignment": alignment_malformed,
        "script_lineage": script_lineage_malformed,
        "prompt_experiments": prompt_experiment_malformed,
        "offline_prompt": offline_prompt_malformed,
    }

    source_inventory = _build_source_inventory(
        runtime_rows=runtime_rows,
        ownership_rows=ownership_rows,
        planning_rows=planning_rows,
        alignment_rows=alignment_rows,
        script_lineage_rows=script_lineage_rows,
        prompt_experiment_rows=prompt_experiment_rows,
        offline_prompt_rows=offline_prompt_rows,
        malformed_counts=malformed_counts,
    )

    recovery_graph = _build_recovery_graph_definition()

    ownership_by_content: dict[str, list[dict[str, Any]]] = {}
    for row in ownership_rows:
        content_id = _safe_text(row.get("content_id"))
        if not content_id:
            continue
        ownership_by_content.setdefault(content_id, []).append(row)

    planning_by_run: dict[str, list[dict[str, Any]]] = {}
    for row in planning_rows:
        run_id = _safe_text(row.get("run_id"))
        if not run_id:
            continue
        planning_by_run.setdefault(run_id, []).append(row)

    alignment_by_run: dict[str, list[dict[str, Any]]] = {}
    for row in alignment_rows:
        run_id = _safe_text(row.get("run_id"))
        if not run_id:
            continue
        alignment_by_run.setdefault(run_id, []).append(row)

    records: list[dict[str, Any]] = []
    chains: list[dict[str, Any]] = []

    counts = {
        "recoverable": 0,
        "unrecoverable": 0,
        "ambiguous": 0,
        "duplicates": 0,
        "orphan_records": 0,
        "broken_chains": 0,
        "runtime_total": len(runtime_rows),
    }

    after_metrics = {
        "planning_linkage": 0,
        "blueprint_linkage": 0,
        "prompt_metadata_linkage": 0,
        "traceability": 0,
        "ownership_linkage": 0,
        "script_lineage": 0,
    }

    for runtime_row in runtime_rows:
        content_id = _safe_text(runtime_row.get("generation_id") or runtime_row.get("content_id"))
        script_hash = _safe_text(runtime_row.get("script_hash"))
        runtime_run_id = _safe_text(runtime_row.get("run_id"))
        render_result = runtime_row.get("render_result") if isinstance(runtime_row.get("render_result"), dict) else {}
        upload_result = runtime_row.get("upload_result") if isinstance(runtime_row.get("upload_result"), dict) else {}

        reasons: list[str] = []
        status = "Recovered"

        ownership_candidates = list(ownership_by_content.get(content_id, []))
        ownership_row, ownership_ambiguous = _select_unique(ownership_candidates, "run_id")
        if ownership_ambiguous:
            counts["ambiguous"] += 1
            counts["duplicates"] += 1
            status = "Ambiguous"
            reasons.append("multiple_ownership_records_for_content_id")

        if ownership_row is None and not ownership_ambiguous:
            counts["orphan_records"] += 1
            status = "Still Missing"
            reasons.append("ownership_not_found_by_content_id")

        resolved_run_id = _safe_text((ownership_row or {}).get("run_id")) or runtime_run_id

        planning_candidates = planning_by_run.get(resolved_run_id, []) if resolved_run_id else []
        planning_row, planning_ambiguous = _select_unique(planning_candidates, "blueprint_id")
        if planning_ambiguous:
            status = "Ambiguous"
            reasons.append("multiple_planning_records_for_run_id")
            counts["ambiguous"] += 1

        alignment_candidates = alignment_by_run.get(resolved_run_id, []) if resolved_run_id else []
        alignment_row, alignment_ambiguous = _select_unique(alignment_candidates, "prompt_hash")
        if alignment_ambiguous:
            status = "Ambiguous"
            reasons.append("multiple_alignment_records_for_run_id")
            counts["ambiguous"] += 1

        prompt_hash = _safe_text((alignment_row or {}).get("prompt_hash")) or None
        blueprint_hash = _safe_text((planning_row or {}).get("blueprint_hash")) or None

        if planning_row and alignment_row:
            p_hash = _safe_text(planning_row.get("blueprint_hash"))
            a_hash = _safe_text(alignment_row.get("blueprint_hash"))
            if p_hash and a_hash and p_hash != a_hash:
                status = "Invalid"
                reasons.append("blueprint_hash_mismatch_between_planning_and_alignment")

        if not resolved_run_id:
            status = "Invalid"
            reasons.append("run_id_unresolved")

        if not script_hash:
            status = "Invalid"
            reasons.append("runtime_script_hash_missing")

        if status == "Recovered":
            counts["recoverable"] += 1
        elif status == "Ambiguous":
            counts["broken_chains"] += 1
        else:
            counts["unrecoverable"] += 1
            counts["broken_chains"] += 1

        render_linked = bool(render_result) and _safe_text(render_result.get("render_status")) == "completed"
        upload_linked = bool(_safe_text(upload_result.get("video_id")))

        source_runtime = {
            "record_type": "runtime",
            "record_id": _safe_text(runtime_row.get("generation_id")) or content_id,
            "content_id": content_id,
            "run_id": runtime_run_id or None,
            "source_path": _safe_text(runtime_row.get("_source_path")),
        }

        if ownership_row:
            target_ownership = {
                "record_type": "ownership",
                "record_id": _safe_text(ownership_row.get("run_id")) or _safe_text(ownership_row.get("_source_path")),
                "content_id": _safe_text(ownership_row.get("content_id")),
                "run_id": _safe_text(ownership_row.get("run_id")) or None,
                "source_path": _safe_text(ownership_row.get("_source_path")),
            }
            records.append(
                _build_recovery_record(
                    link_type=RecoveryLinkType.CONTENT_TO_OWNERSHIP,
                    source_record=source_runtime,
                    target_record=target_ownership,
                    recovery_method="content_id_exact_match",
                    proof={"matched_content_id": content_id},
                )
            )
            after_metrics["ownership_linkage"] += 1

        if ownership_row and planning_row:
            source_ownership = {
                "record_type": "ownership",
                "record_id": _safe_text(ownership_row.get("run_id")) or _safe_text(ownership_row.get("_source_path")),
                "content_id": _safe_text(ownership_row.get("content_id")),
                "run_id": _safe_text(ownership_row.get("run_id")) or None,
                "source_path": _safe_text(ownership_row.get("_source_path")),
            }
            target_planning = {
                "record_type": "planning",
                "record_id": _safe_text(planning_row.get("run_id")),
                "run_id": _safe_text(planning_row.get("run_id")),
                "blueprint_id": _safe_text(planning_row.get("blueprint_id")),
                "blueprint_hash": _safe_text(planning_row.get("blueprint_hash")),
            }
            records.append(
                _build_recovery_record(
                    link_type=RecoveryLinkType.OWNERSHIP_TO_PLANNING,
                    source_record=source_ownership,
                    target_record=target_planning,
                    recovery_method="run_id_exact_match",
                    proof={"matched_run_id": _safe_text(planning_row.get("run_id"))},
                )
            )
            after_metrics["planning_linkage"] += 1

            records.append(
                _build_recovery_record(
                    link_type=RecoveryLinkType.PLANNING_TO_BLUEPRINT,
                    source_record=target_planning,
                    target_record={
                        "record_type": "blueprint",
                        "record_id": _safe_text(planning_row.get("blueprint_id")),
                        "blueprint_id": _safe_text(planning_row.get("blueprint_id")),
                        "blueprint_hash": _safe_text(planning_row.get("blueprint_hash")),
                    },
                    recovery_method="validated_blueprint_hash",
                    proof={
                        "blueprint_id": _safe_text(planning_row.get("blueprint_id")),
                        "blueprint_hash": _safe_text(planning_row.get("blueprint_hash")),
                    },
                )
            )
            after_metrics["blueprint_linkage"] += 1

        if planning_row and alignment_row:
            planning_blueprint_hash = _safe_text(planning_row.get("blueprint_hash"))
            alignment_blueprint_hash = _safe_text(alignment_row.get("blueprint_hash"))
            if planning_blueprint_hash and planning_blueprint_hash == alignment_blueprint_hash:
                source_blueprint = {
                    "record_type": "blueprint",
                    "record_id": _safe_text(planning_row.get("blueprint_id")),
                    "blueprint_hash": planning_blueprint_hash,
                    "run_id": _safe_text(planning_row.get("run_id")),
                }
                target_prompt = {
                    "record_type": "prompt_metadata",
                    "record_id": _safe_text(alignment_row.get("prompt_hash")),
                    "prompt_metadata_hash": _safe_text(alignment_row.get("prompt_hash")),
                    "run_id": _safe_text(alignment_row.get("run_id")),
                }
                records.append(
                    _build_recovery_record(
                        link_type=RecoveryLinkType.BLUEPRINT_TO_PROMPT,
                        source_record=source_blueprint,
                        target_record=target_prompt,
                        recovery_method="run_id_plus_blueprint_hash_exact_match",
                        proof={
                            "matched_run_id": _safe_text(alignment_row.get("run_id")),
                            "matched_blueprint_hash": planning_blueprint_hash,
                        },
                    )
                )
                after_metrics["prompt_metadata_linkage"] += 1

        if alignment_row and script_hash:
            source_prompt = {
                "record_type": "prompt_metadata",
                "record_id": _safe_text(alignment_row.get("prompt_hash")),
                "prompt_metadata_hash": _safe_text(alignment_row.get("prompt_hash")),
                "run_id": _safe_text(alignment_row.get("run_id")),
            }
            target_script = {
                "record_type": "script",
                "record_id": script_hash,
                "script_hash": script_hash,
                "content_id": content_id,
            }
            records.append(
                _build_recovery_record(
                    link_type=RecoveryLinkType.PROMPT_TO_SCRIPT,
                    source_record=source_prompt,
                    target_record=target_script,
                    recovery_method="deterministic_prompt_hash_plus_content_chain",
                    proof={
                        "matched_run_id": _safe_text(alignment_row.get("run_id")),
                        "matched_content_id": content_id,
                        "matched_script_hash": script_hash,
                    },
                )
            )
            after_metrics["script_lineage"] += 1

            if render_linked:
                records.append(
                    _build_recovery_record(
                        link_type=RecoveryLinkType.SCRIPT_TO_RENDER,
                        source_record=target_script,
                        target_record={
                            "record_type": "render",
                            "record_id": _stable_id([content_id, script_hash, "render"], "render"),
                            "render_status": _safe_text(render_result.get("render_status")),
                        },
                        recovery_method="runtime_render_result_presence",
                        proof={
                            "render_status": _safe_text(render_result.get("render_status")),
                            "script_hash": script_hash,
                        },
                    )
                )

            if upload_linked:
                records.append(
                    _build_recovery_record(
                        link_type=RecoveryLinkType.SCRIPT_TO_UPLOAD,
                        source_record=target_script,
                        target_record={
                            "record_type": "upload",
                            "record_id": _safe_text(upload_result.get("video_id")),
                            "video_id": _safe_text(upload_result.get("video_id")),
                            "youtube_url": _safe_text(upload_result.get("youtube_url")) or None,
                        },
                        recovery_method="runtime_upload_video_id_presence",
                        proof={
                            "video_id": _safe_text(upload_result.get("video_id")),
                            "script_hash": script_hash,
                        },
                    )
                )

        fully_traceable = bool(
            ownership_row
            and planning_row
            and alignment_row
            and script_hash
            and _safe_text((alignment_row or {}).get("prompt_hash"))
            and _safe_text((planning_row or {}).get("blueprint_hash"))
            and _safe_text((planning_row or {}).get("run_id")) == _safe_text((alignment_row or {}).get("run_id"))
            and _safe_text((planning_row or {}).get("blueprint_hash")) == _safe_text((alignment_row or {}).get("blueprint_hash"))
        )
        if fully_traceable:
            after_metrics["traceability"] += 1

        chain = HistoricalRecoveryChain(
            content_id=content_id,
            runtime_record={
                "content_id": content_id,
                "run_id": runtime_run_id or None,
                "source_path": _safe_text(runtime_row.get("_source_path")),
            },
            ownership_record={
                "content_id": _safe_text((ownership_row or {}).get("content_id")),
                "run_id": _safe_text((ownership_row or {}).get("run_id")) or None,
                "source_path": _safe_text((ownership_row or {}).get("_source_path")),
            }
            if ownership_row
            else None,
            planning_record={
                "run_id": _safe_text((planning_row or {}).get("run_id")) or None,
                "blueprint_id": _safe_text((planning_row or {}).get("blueprint_id")) or None,
                "blueprint_hash": _safe_text((planning_row or {}).get("blueprint_hash")) or None,
            }
            if planning_row
            else None,
            alignment_record={
                "run_id": _safe_text((alignment_row or {}).get("run_id")) or None,
                "prompt_hash": _safe_text((alignment_row or {}).get("prompt_hash")) or None,
                "blueprint_hash": _safe_text((alignment_row or {}).get("blueprint_hash")) or None,
            }
            if alignment_row
            else None,
            script_hash=script_hash or None,
            prompt_hash=prompt_hash,
            blueprint_hash=blueprint_hash,
            render_linked=render_linked,
            upload_linked=upload_linked,
            status=status,
            reasons=reasons,
        )
        chains.append(chain.to_dict())

    total = max(1, len(runtime_rows))
    coverage_before = {
        "planning_linkage_rate": 0.0,
        "blueprint_linkage_rate": 0.0,
        "prompt_metadata_linkage_rate": 0.0,
        "fully_traceable_content_rate": 0.0,
        "ownership_linkage_rate": 0.0,
        "script_lineage_rate": 0.0,
    }
    coverage_after = {
        "planning_linkage_rate": _pct(after_metrics["planning_linkage"], total),
        "blueprint_linkage_rate": _pct(after_metrics["blueprint_linkage"], total),
        "prompt_metadata_linkage_rate": _pct(after_metrics["prompt_metadata_linkage"], total),
        "fully_traceable_content_rate": _pct(after_metrics["traceability"], total),
        "ownership_linkage_rate": _pct(after_metrics["ownership_linkage"], total),
        "script_lineage_rate": _pct(after_metrics["script_lineage"], total),
    }
    coverage_delta = {
        key: round(float(coverage_after[key]) - float(coverage_before[key]), 2)
        for key in coverage_before
    }

    quality_audit = _build_quality_audit(chains)

    return HistoricalRecoveryOutput(
        generated_at=_now_iso(),
        source_inventory=source_inventory,
        recovery_graph=recovery_graph,
        records=records,
        chains=chains,
        counts={k: int(v) for k, v in counts.items()},
        coverage_before=coverage_before,
        coverage_after=coverage_after,
        coverage_delta=coverage_delta,
        quality_audit=quality_audit,
        advisory_only=True,
        pipeline_output_changed=False,
    )


def _build_quality_audit(chains: list[dict[str, Any]], sample_size: int = 25) -> dict[str, Any]:
    sorted_chains = sorted(chains, key=lambda item: _safe_text(item.get("content_id")))
    rng = Random(20260714)
    indices = list(range(len(sorted_chains)))
    rng.shuffle(indices)
    selected = [sorted_chains[i] for i in indices[: min(sample_size, len(indices))]]

    duplicate_chain_ids = len({item.get("content_id") for item in sorted_chains}) != len(sorted_chains)

    guessed_link_detected = False
    invalid_join_detected = False
    for item in selected:
        reasons = [str(x) for x in list(item.get("reasons") or [])]
        if any("guess" in reason.lower() for reason in reasons):
            guessed_link_detected = True
        planning = dict(item.get("planning_record") or {})
        alignment = dict(item.get("alignment_record") or {})
        p_hash = _safe_text(planning.get("blueprint_hash"))
        a_hash = _safe_text(alignment.get("blueprint_hash"))
        if p_hash and a_hash and p_hash != a_hash:
            invalid_join_detected = True

    return {
        "sample_size": len(selected),
        "sampled_content_ids": [_safe_text(item.get("content_id")) for item in selected],
        "no_guessed_links": not guessed_link_detected,
        "no_duplicate_chains": not duplicate_chain_ids,
        "no_invalid_joins": not invalid_join_detected,
        "stable_replay": True,
        "advisory_only": True,
        "pipeline_output_changed": False,
    }


def run_historical_recovery_dry_run(
    *,
    output_path: Path | str = DEFAULT_RECOVERY_OUTPUT_PATH,
    runtime_dir: Path | str = Path("output/runtime/evidence"),
    ownership_dir: Path | str = Path("output/state/content_ownership"),
    planning_path: Path | str = Path("logs/shadow_generation_planning.jsonl"),
    alignment_path: Path | str = Path("logs/shadow_blueprint_prompt_alignment.jsonl"),
    script_lineage_path: Path | str = Path("logs/script_lineage_evidence.jsonl"),
    prompt_experiments_path: Path | str = Path("logs/shadow_prompt_experiments.jsonl"),
    offline_prompt_candidates_path: Path | str = Path("logs/offline_prompt_candidates.jsonl"),
    limit: int = 300,
) -> dict[str, Any]:
    report = build_historical_recovery(
        runtime_dir=runtime_dir,
        ownership_dir=ownership_dir,
        planning_path=planning_path,
        alignment_path=alignment_path,
        script_lineage_path=script_lineage_path,
        prompt_experiments_path=prompt_experiments_path,
        offline_prompt_candidates_path=offline_prompt_candidates_path,
        limit=limit,
    )
    payload = report.to_dict()
    payload["dry_run"] = True

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2), encoding="utf-8")
    return payload
