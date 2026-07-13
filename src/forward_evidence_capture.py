from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
from typing import Any


FORWARD_EVIDENCE_SCHEMA_VERSION = "v1"
DEFAULT_FORWARD_EVIDENCE_PATH = Path("logs/forward_evidence_capture.jsonl")


class ForwardEvidenceStage(str, Enum):
    PLANNING_COMPLETE = "PLANNING_COMPLETE"
    BLUEPRINT_FINALIZED = "BLUEPRINT_FINALIZED"
    PROMPT_FINALIZED = "PROMPT_FINALIZED"
    SCRIPT_FINALIZED = "SCRIPT_FINALIZED"
    THUMBNAIL_FINALIZED = "THUMBNAIL_FINALIZED"
    RENDER_COMPLETE = "RENDER_COMPLETE"
    OWNERSHIP_FINALIZED = "OWNERSHIP_FINALIZED"
    UPLOAD_COMPLETE = "UPLOAD_COMPLETE"


_STAGE_ORDER = {
    ForwardEvidenceStage.PLANNING_COMPLETE.value: 10,
    ForwardEvidenceStage.BLUEPRINT_FINALIZED.value: 20,
    ForwardEvidenceStage.PROMPT_FINALIZED.value: 30,
    ForwardEvidenceStage.SCRIPT_FINALIZED.value: 40,
    ForwardEvidenceStage.THUMBNAIL_FINALIZED.value: 50,
    ForwardEvidenceStage.RENDER_COMPLETE.value: 60,
    ForwardEvidenceStage.OWNERSHIP_FINALIZED.value: 70,
    ForwardEvidenceStage.UPLOAD_COMPLETE.value: 80,
}


@dataclass(frozen=True)
class ForwardEvidenceAppendResult:
    appended: bool
    duplicate: bool
    reason: str


@dataclass(frozen=True)
class ForwardEvidenceSessionEvent:
    schema_version: str
    event_id: str
    session_id: str
    stage: str
    stage_order: int
    run_id: str
    content_id: str
    channel_id: str
    planning_context_id: str | None
    blueprint_id: str | None
    prompt_metadata_hash: str | None
    script_hash: str | None
    thumbnail_hash: str | None
    render_hash: str | None
    upload_id: str | None
    ownership_id: str | None
    created_at: str
    advisory_only: bool
    pipeline_output_changed: bool

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "session_id": self.session_id,
            "stage": self.stage,
            "stage_order": int(self.stage_order),
            "run_id": self.run_id,
            "content_id": self.content_id,
            "channel_id": self.channel_id,
            "planning_context_id": self.planning_context_id,
            "blueprint_id": self.blueprint_id,
            "prompt_metadata_hash": self.prompt_metadata_hash,
            "script_hash": self.script_hash,
            "thumbnail_hash": self.thumbnail_hash,
            "render_hash": self.render_hash,
            "upload_id": self.upload_id,
            "ownership_id": self.ownership_id,
            "created_at": self.created_at,
            "advisory_only": bool(self.advisory_only),
            "pipeline_output_changed": bool(self.pipeline_output_changed),
        }
        return validate_forward_evidence_event(payload)


@dataclass(frozen=True)
class ForwardEvidenceReplayDiagnostics:
    malformed_rows: int
    replay_errors: list[str]


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


def forward_evidence_capture_enabled() -> bool:
    return _is_enabled(os.getenv("FORWARD_EVIDENCE_CAPTURE_ENABLED", "false"))


def compute_session_id(*, content_id: str, run_id: str) -> str:
    return "fes_" + _sha(f"{_safe_text(content_id)}|{_safe_text(run_id)}")[:24]


def compute_event_id(*, session_id: str, stage: ForwardEvidenceStage, stage_order: int, keys: list[str]) -> str:
    parts = [session_id, stage.value, str(int(stage_order))] + [str(x or "") for x in keys]
    return "fev_" + _sha("|".join(parts))[:24]


def hash_file(path: str | None) -> str | None:
    p = Path(str(path or "").strip())
    if not p.exists() or not p.is_file():
        return None
    digest = hashlib.sha256()
    with p.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 64)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def build_render_hash(*, render_metrics: dict[str, Any] | None, video_path: str | None) -> str | None:
    metrics = dict(render_metrics or {})
    payload = {
        "render_status": _safe_text(metrics.get("render_status")),
        "render_started_at": _safe_text(metrics.get("render_started_at")),
        "render_finished_at": _safe_text(metrics.get("render_finished_at")),
        "output_resolution": _safe_text(metrics.get("output_resolution")),
        "output_fps": metrics.get("output_fps"),
        "video_hash": hash_file(video_path),
    }
    if not any(bool(v) for v in payload.values()):
        return None
    return _sha(json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")))


def extract_prompt_metadata_hash(prompt_metadata: dict[str, Any] | None) -> str | None:
    payload = dict(prompt_metadata or {})
    direct = _safe_text(payload.get("prompt_hash"))
    safe = payload.get("safe_prompt") if isinstance(payload.get("safe_prompt"), dict) else {}
    safe_hash = _safe_text(safe.get("prompt_hash"))
    if direct and safe_hash and direct != safe_hash:
        return None
    if direct:
        return direct
    if safe_hash:
        return safe_hash
    return None


def validate_forward_evidence_event(row: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ValueError("invalid_payload")

    required = [
        "schema_version",
        "event_id",
        "session_id",
        "stage",
        "stage_order",
        "run_id",
        "content_id",
        "channel_id",
        "planning_context_id",
        "blueprint_id",
        "prompt_metadata_hash",
        "script_hash",
        "thumbnail_hash",
        "render_hash",
        "upload_id",
        "ownership_id",
        "created_at",
        "advisory_only",
        "pipeline_output_changed",
    ]
    for key in required:
        if key not in row:
            raise ValueError(f"missing_field:{key}")

    if _safe_text(row.get("schema_version")) != FORWARD_EVIDENCE_SCHEMA_VERSION:
        raise ValueError("invalid_field:schema_version")

    stage = ForwardEvidenceStage(_safe_text(row.get("stage")))
    if int(row.get("stage_order") or 0) != _STAGE_ORDER[stage.value]:
        raise ValueError("invalid_field:stage_order")

    if not _safe_text(row.get("event_id")):
        raise ValueError("missing_field:event_id")
    if not _safe_text(row.get("session_id")):
        raise ValueError("missing_field:session_id")
    if not _safe_text(row.get("run_id")):
        raise ValueError("missing_field:run_id")
    if not _safe_text(row.get("content_id")):
        raise ValueError("missing_field:content_id")
    if not _safe_text(row.get("channel_id")):
        raise ValueError("missing_field:channel_id")

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
    normalized["stage_order"] = int(row.get("stage_order") or 0)
    normalized["advisory_only"] = bool(row.get("advisory_only"))
    normalized["pipeline_output_changed"] = bool(row.get("pipeline_output_changed"))

    for key in [
        "planning_context_id",
        "blueprint_id",
        "prompt_metadata_hash",
        "script_hash",
        "thumbnail_hash",
        "render_hash",
        "upload_id",
        "ownership_id",
    ]:
        value = _safe_text(normalized.get(key))
        normalized[key] = value or None

    return normalized


def load_forward_evidence_rows(
    *,
    input_path: Path | str = DEFAULT_FORWARD_EVIDENCE_PATH,
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
            decoded = json.loads(line)
            rows.append(validate_forward_evidence_event(decoded))
        except Exception as exc:
            malformed += 1
            errors.append(f"line={idx}:{exc}")

    if limit > 0:
        rows = rows[-limit:]
    return rows, malformed, errors


class ForwardEvidenceStore:
    def __init__(self, *, evidence_path: Path | str = DEFAULT_FORWARD_EVIDENCE_PATH):
        self.evidence_path = Path(evidence_path)
        self._known_ids: set[str] | None = None

    def _ensure_known_ids(self) -> set[str]:
        if self._known_ids is not None:
            return self._known_ids
        rows, _malformed, _errors = load_forward_evidence_rows(input_path=self.evidence_path, limit=0)
        self._known_ids = {_safe_text(row.get("event_id")) for row in rows if _safe_text(row.get("event_id"))}
        return self._known_ids

    def append(self, row: dict[str, Any]) -> ForwardEvidenceAppendResult:
        payload = validate_forward_evidence_event(row)
        known = self._ensure_known_ids()
        event_id = _safe_text(payload.get("event_id"))
        if event_id in known:
            return ForwardEvidenceAppendResult(appended=False, duplicate=True, reason="duplicate_event_id")

        self.evidence_path.parent.mkdir(parents=True, exist_ok=True)
        blob = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
        fd = os.open(self.evidence_path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
        try:
            os.write(fd, blob.encode("utf-8"))
        finally:
            os.close(fd)

        known.add(event_id)
        return ForwardEvidenceAppendResult(appended=True, duplicate=False, reason="appended")


class ForwardEvidenceRecorder:
    def __init__(
        self,
        *,
        content_id: str,
        run_id: str,
        channel_id: str,
        evidence_path: Path | str | None = None,
    ):
        self.content_id = _safe_text(content_id)
        self.run_id = _safe_text(run_id)
        self.channel_id = _safe_text(channel_id)
        self.session_id = compute_session_id(content_id=self.content_id, run_id=self.run_id)
        self.store = ForwardEvidenceStore(
            evidence_path=evidence_path or os.getenv("FORWARD_EVIDENCE_CAPTURE_PATH", str(DEFAULT_FORWARD_EVIDENCE_PATH))
        )

    def record_stage(
        self,
        *,
        stage: ForwardEvidenceStage,
        planning_context_id: str | None,
        blueprint_id: str | None,
        prompt_metadata_hash: str | None,
        script_hash: str | None,
        thumbnail_hash: str | None,
        render_hash: str | None,
        upload_id: str | None,
        ownership_id: str | None,
    ) -> ForwardEvidenceAppendResult:
        event_id = compute_event_id(
            session_id=self.session_id,
            stage=stage,
            stage_order=_STAGE_ORDER[stage.value],
            keys=[
                self.content_id,
                self.run_id,
                _safe_text(planning_context_id),
                _safe_text(blueprint_id),
                _safe_text(prompt_metadata_hash),
                _safe_text(script_hash),
                _safe_text(thumbnail_hash),
                _safe_text(render_hash),
                _safe_text(upload_id),
                _safe_text(ownership_id),
            ],
        )

        row = ForwardEvidenceSessionEvent(
            schema_version=FORWARD_EVIDENCE_SCHEMA_VERSION,
            event_id=event_id,
            session_id=self.session_id,
            stage=stage.value,
            stage_order=_STAGE_ORDER[stage.value],
            run_id=self.run_id,
            content_id=self.content_id,
            channel_id=self.channel_id,
            planning_context_id=_safe_text(planning_context_id) or None,
            blueprint_id=_safe_text(blueprint_id) or None,
            prompt_metadata_hash=_safe_text(prompt_metadata_hash) or None,
            script_hash=_safe_text(script_hash) or None,
            thumbnail_hash=_safe_text(thumbnail_hash) or None,
            render_hash=_safe_text(render_hash) or None,
            upload_id=_safe_text(upload_id) or None,
            ownership_id=_safe_text(ownership_id) or None,
            created_at=_now_iso(),
            advisory_only=True,
            pipeline_output_changed=False,
        ).to_dict()
        return self.store.append(row)


def replay_forward_evidence_sessions(
    *,
    events: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], ForwardEvidenceReplayDiagnostics]:
    state: dict[str, dict[str, Any]] = {}
    errors: list[str] = []

    for event in events:
        try:
            row = validate_forward_evidence_event(event)
            session_id = _safe_text(row.get("session_id"))
            entry = state.setdefault(
                session_id,
                {
                    "session_id": session_id,
                    "run_id": _safe_text(row.get("run_id")),
                    "content_id": _safe_text(row.get("content_id")),
                    "channel_id": _safe_text(row.get("channel_id")),
                    "events": [],
                    "latest": {},
                },
            )
            entry["events"].append(dict(row))
            entry["latest"] = {
                "planning_context_id": row.get("planning_context_id"),
                "blueprint_id": row.get("blueprint_id"),
                "prompt_metadata_hash": row.get("prompt_metadata_hash"),
                "script_hash": row.get("script_hash"),
                "thumbnail_hash": row.get("thumbnail_hash"),
                "render_hash": row.get("render_hash"),
                "upload_id": row.get("upload_id"),
                "ownership_id": row.get("ownership_id"),
                "stage": row.get("stage"),
                "created_at": row.get("created_at"),
            }
        except Exception as exc:
            errors.append(str(exc))

    for session in state.values():
        session["events"] = sorted(session.get("events") or [], key=lambda item: (int(item.get("stage_order") or 0), _safe_text(item.get("created_at"))))

    return state, ForwardEvidenceReplayDiagnostics(malformed_rows=0, replay_errors=errors)


def verify_forward_evidence_integrity(
    *,
    sessions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    mandatory_stages = [
        ForwardEvidenceStage.PLANNING_COMPLETE.value,
        ForwardEvidenceStage.BLUEPRINT_FINALIZED.value,
        ForwardEvidenceStage.PROMPT_FINALIZED.value,
        ForwardEvidenceStage.SCRIPT_FINALIZED.value,
        ForwardEvidenceStage.THUMBNAIL_FINALIZED.value,
        ForwardEvidenceStage.RENDER_COMPLETE.value,
        ForwardEvidenceStage.UPLOAD_COMPLETE.value,
    ]

    issues: list[dict[str, Any]] = []
    summary = {
        "total_sessions": len(sessions),
        "missing_stage": 0,
        "duplicate_stage": 0,
        "broken_lineage": 0,
        "unexpected_ordering": 0,
        "orphan_evidence": 0,
        "advisory_only": True,
        "pipeline_output_changed": False,
    }

    for session_id, payload in sessions.items():
        events = list(payload.get("events") or [])
        stage_counts: dict[str, int] = {}
        stage_orders: list[int] = []
        for event in events:
            stage = _safe_text(event.get("stage"))
            stage_counts[stage] = int(stage_counts.get(stage, 0)) + 1
            stage_orders.append(int(event.get("stage_order") or 0))

        missing = [stage for stage in mandatory_stages if stage_counts.get(stage, 0) == 0]
        duplicates = [stage for stage, count in stage_counts.items() if count > 1]

        latest = dict(payload.get("latest") or {})
        broken = []
        if not _safe_text(payload.get("run_id")) or not _safe_text(payload.get("content_id")):
            broken.append("missing_session_identity")
        if not _safe_text(latest.get("script_hash")) and ForwardEvidenceStage.SCRIPT_FINALIZED.value in stage_counts:
            broken.append("script_stage_missing_hash")
        if not _safe_text(latest.get("render_hash")) and ForwardEvidenceStage.RENDER_COMPLETE.value in stage_counts:
            broken.append("render_stage_missing_hash")
        if not _safe_text(latest.get("upload_id")) and ForwardEvidenceStage.UPLOAD_COMPLETE.value in stage_counts:
            broken.append("upload_stage_missing_upload_id")

        unexpected_ordering = stage_orders != sorted(stage_orders)
        orphan = bool(events) and not _safe_text(payload.get("run_id"))

        if missing:
            summary["missing_stage"] += 1
        if duplicates:
            summary["duplicate_stage"] += 1
        if broken:
            summary["broken_lineage"] += 1
        if unexpected_ordering:
            summary["unexpected_ordering"] += 1
        if orphan:
            summary["orphan_evidence"] += 1

        if missing or duplicates or broken or unexpected_ordering or orphan:
            issues.append(
                {
                    "session_id": session_id,
                    "missing_stage": missing,
                    "duplicate_stage": duplicates,
                    "broken_lineage": broken,
                    "unexpected_ordering": unexpected_ordering,
                    "orphan_evidence": orphan,
                    "advisory_only": True,
                    "pipeline_output_changed": False,
                }
            )

    return {
        "summary": summary,
        "issues": issues,
        "advisory_only": True,
        "pipeline_output_changed": False,
    }


def compute_forward_completeness_scores(
    *,
    sessions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    def _score(value: bool) -> float:
        return 100.0 if value else 0.0

    session_scores: list[dict[str, Any]] = []
    totals = {
        "planning": 0,
        "blueprint": 0,
        "prompt": 0,
        "script": 0,
        "thumbnail": 0,
        "render": 0,
        "upload": 0,
        "lineage": 0,
        "traceability": 0,
    }

    for session_id, payload in sessions.items():
        events = list(payload.get("events") or [])
        stages = {_safe_text(event.get("stage")) for event in events}
        latest = dict(payload.get("latest") or {})

        planning_ok = ForwardEvidenceStage.PLANNING_COMPLETE.value in stages and bool(_safe_text(latest.get("planning_context_id")))
        blueprint_ok = ForwardEvidenceStage.BLUEPRINT_FINALIZED.value in stages and bool(_safe_text(latest.get("blueprint_id")))
        prompt_ok = ForwardEvidenceStage.PROMPT_FINALIZED.value in stages and bool(_safe_text(latest.get("prompt_metadata_hash")))
        script_ok = ForwardEvidenceStage.SCRIPT_FINALIZED.value in stages and bool(_safe_text(latest.get("script_hash")))
        thumbnail_ok = ForwardEvidenceStage.THUMBNAIL_FINALIZED.value in stages and bool(_safe_text(latest.get("thumbnail_hash")))
        render_ok = ForwardEvidenceStage.RENDER_COMPLETE.value in stages and bool(_safe_text(latest.get("render_hash")))
        upload_ok = ForwardEvidenceStage.UPLOAD_COMPLETE.value in stages and bool(_safe_text(latest.get("upload_id")))

        lineage_ok = planning_ok and blueprint_ok and prompt_ok and script_ok and thumbnail_ok and render_ok and upload_ok
        traceability_ok = lineage_ok and bool(_safe_text(payload.get("run_id"))) and bool(_safe_text(payload.get("content_id")))

        totals["planning"] += int(planning_ok)
        totals["blueprint"] += int(blueprint_ok)
        totals["prompt"] += int(prompt_ok)
        totals["script"] += int(script_ok)
        totals["thumbnail"] += int(thumbnail_ok)
        totals["render"] += int(render_ok)
        totals["upload"] += int(upload_ok)
        totals["lineage"] += int(lineage_ok)
        totals["traceability"] += int(traceability_ok)

        session_scores.append(
            {
                "session_id": session_id,
                "planning_coverage": _score(planning_ok),
                "blueprint_coverage": _score(blueprint_ok),
                "prompt_coverage": _score(prompt_ok),
                "script_coverage": _score(script_ok),
                "thumbnail_coverage": _score(thumbnail_ok),
                "render_coverage": _score(render_ok),
                "upload_coverage": _score(upload_ok),
                "lineage_completeness": _score(lineage_ok),
                "overall_traceability": _score(traceability_ok),
                "advisory_only": True,
                "pipeline_output_changed": False,
            }
        )

    count = max(1, len(sessions))
    aggregate = {
        "planning_coverage": round(100.0 * totals["planning"] / count, 2),
        "blueprint_coverage": round(100.0 * totals["blueprint"] / count, 2),
        "prompt_coverage": round(100.0 * totals["prompt"] / count, 2),
        "script_coverage": round(100.0 * totals["script"] / count, 2),
        "thumbnail_coverage": round(100.0 * totals["thumbnail"] / count, 2),
        "render_coverage": round(100.0 * totals["render"] / count, 2),
        "upload_coverage": round(100.0 * totals["upload"] / count, 2),
        "lineage_completeness": round(100.0 * totals["lineage"] / count, 2),
        "overall_traceability": round(100.0 * totals["traceability"] / count, 2),
        "session_count": len(sessions),
        "advisory_only": True,
        "pipeline_output_changed": False,
    }
    return {
        "aggregate": aggregate,
        "sessions": session_scores,
        "advisory_only": True,
        "pipeline_output_changed": False,
    }


def reconstruct_forward_sessions(
    *,
    evidence_path: Path | str = DEFAULT_FORWARD_EVIDENCE_PATH,
) -> tuple[dict[str, dict[str, Any]], ForwardEvidenceReplayDiagnostics]:
    rows, malformed, _errors = load_forward_evidence_rows(input_path=evidence_path, limit=0)
    sessions, diagnostics = replay_forward_evidence_sessions(events=rows)
    return sessions, ForwardEvidenceReplayDiagnostics(malformed_rows=malformed, replay_errors=list(diagnostics.replay_errors))
