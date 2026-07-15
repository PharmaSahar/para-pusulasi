from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

from .experiment_lifecycle_contract import (
    EXPERIMENT_LIFECYCLE_SCHEMA_VERSION,
    LifecycleEventType,
    build_experiment_lifecycle_event,
    validate_experiment_lifecycle_event_row,
)
from .experiment_lifecycle_projection import build_experiment_projection_from_rows


DEFAULT_EXPERIMENT_LIFECYCLE_PATH = Path("logs/experiment_lifecycle.jsonl")


class ExperimentLifecycleError(RuntimeError):
    pass


class ExperimentLifecycleCorruptionError(ExperimentLifecycleError):
    pass


class ExperimentLifecycleConflictError(ExperimentLifecycleError):
    pass


@dataclass(frozen=True, slots=True)
class ExperimentLifecycleAppendResult:
    appended: bool
    duplicate: bool
    conflict: bool
    assignment_id: str
    lifecycle_event_id: str
    record_hash: str
    reason: str


@dataclass(frozen=True, slots=True)
class ExperimentLifecycleReplayDiagnostics:
    malformed_rows: int
    partial_trailing_rows: int
    duplicate_rows: int
    unsupported_schema_rows: int
    broken_hash_links: int
    replay_errors: list[str]


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _dedupe_signature(record: dict[str, Any]) -> str:
    def _strip(value: Any) -> Any:
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for key, item in value.items():
                if key in {"record_hash", "lifecycle_event_id", "created_at", "previous_record_hash"}:
                    continue
                out[key] = _strip(item)
            return out
        if isinstance(value, list):
            return [_strip(item) for item in value]
        return value

    return _stable_json(_strip(dict(record)))


def _load_raw_rows(path: Path) -> tuple[list[dict[str, Any]], ExperimentLifecycleReplayDiagnostics]:
    if not path.exists():
        return [], ExperimentLifecycleReplayDiagnostics(0, 0, 0, 0, 0, [])

    rows: list[dict[str, Any]] = []
    malformed = 0
    partial = 0
    duplicate = 0
    unsupported = 0
    broken = 0
    errors: list[str] = []
    seen: set[str] = set()

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    ends_with_newline = text.endswith("\n")

    for index, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            decoded = json.loads(line)
            validated = validate_experiment_lifecycle_event_row(decoded)
            signature = _dedupe_signature(validated)
            if signature in seen:
                duplicate += 1
            else:
                seen.add(signature)
            rows.append(validated)
        except Exception as exc:
            malformed += 1
            if "schema_version" in str(exc):
                unsupported += 1
            if index == len(lines) and not ends_with_newline:
                partial += 1
            errors.append(f"line={index}:{exc}")

    if rows:
        ok, issues, _last = _verify_hash_chain(rows)
        if not ok:
            broken = len(issues)

    return rows, ExperimentLifecycleReplayDiagnostics(malformed, partial, duplicate, unsupported, broken, errors)


def _verify_hash_chain(rows: list[dict[str, Any]]) -> tuple[bool, list[str], str | None]:
    issues: list[str] = []
    previous_hash: str | None = None

    for index, row in enumerate(rows, start=1):
        row_previous = _safe_text(row.get("previous_record_hash")) or None
        if row_previous != previous_hash:
            issues.append(f"chain_break_at={index}")

        expected = build_experiment_lifecycle_event(
            dict(row),
            created_by=_safe_text(row.get("created_by")),
            source_module=_safe_text(row.get("source_module")),
            source_version=_safe_text(row.get("source_version")),
            created_at=_safe_text(row.get("created_at")),
            previous_record_hash=row_previous,
            event_type=_safe_text(row.get("event_type")),
        )
        if _safe_text(expected.get("record_hash")) != _safe_text(row.get("record_hash")):
            issues.append(f"record_hash_mismatch_at={index}")

        previous_hash = _safe_text(row.get("record_hash")) or None

    return len(issues) == 0, issues, previous_hash


class ExperimentLifecycleStore:
    def __init__(self, *, lifecycle_path: Path | str = DEFAULT_EXPERIMENT_LIFECYCLE_PATH):
        self.lifecycle_path = Path(lifecycle_path)
        self._cache_rows: list[dict[str, Any]] | None = None
        self._cache_diagnostics: ExperimentLifecycleReplayDiagnostics | None = None

    def _load(self) -> tuple[list[dict[str, Any]], ExperimentLifecycleReplayDiagnostics]:
        if self._cache_rows is not None and self._cache_diagnostics is not None:
            return self._cache_rows, self._cache_diagnostics
        rows, diagnostics = _load_raw_rows(self.lifecycle_path)
        self._cache_rows = rows
        self._cache_diagnostics = diagnostics
        return rows, diagnostics

    def _require_clean_history(self) -> list[dict[str, Any]]:
        rows, diagnostics = self._load()
        if (
            diagnostics.malformed_rows
            or diagnostics.partial_trailing_rows
            or diagnostics.duplicate_rows
            or diagnostics.unsupported_schema_rows
            or diagnostics.broken_hash_links
        ):
            raise ExperimentLifecycleCorruptionError(
                "corrupt_experiment_lifecycle: "
                f"malformed_rows={diagnostics.malformed_rows} "
                f"partial_trailing_rows={diagnostics.partial_trailing_rows} "
                f"duplicate_rows={diagnostics.duplicate_rows} "
                f"unsupported_schema_rows={diagnostics.unsupported_schema_rows} "
                f"broken_hash_links={diagnostics.broken_hash_links}"
            )
        return rows

    def _append_row(self, row: dict[str, Any]) -> None:
        self.lifecycle_path.parent.mkdir(parents=True, exist_ok=True)
        blob = _stable_json(row) + "\n"
        fd = os.open(self.lifecycle_path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
        try:
            os.write(fd, blob.encode("utf-8"))
        finally:
            os.close(fd)
        self._cache_rows = None
        self._cache_diagnostics = None

    def _append_event(
        self,
        payload: dict[str, Any],
        *,
        created_by: str,
        source_module: str,
        source_version: str,
        created_at: str | None,
        event_type: str,
    ) -> ExperimentLifecycleAppendResult:
        rows = self._require_clean_history()
        previous_record_hash = rows[-1]["record_hash"] if rows else None
        candidate = build_experiment_lifecycle_event(
            payload,
            created_by=created_by,
            source_module=source_module,
            source_version=source_version,
            created_at=created_at,
            previous_record_hash=previous_record_hash,
            event_type=event_type,
        )

        signature = _dedupe_signature(candidate)
        for existing in rows:
            if _dedupe_signature(existing) != signature:
                continue
            return ExperimentLifecycleAppendResult(
                appended=False,
                duplicate=True,
                conflict=False,
                assignment_id=_safe_text(existing.get("assignment_id")),
                lifecycle_event_id=_safe_text(existing.get("lifecycle_event_id")),
                record_hash=_safe_text(existing.get("record_hash")),
                reason="exact_duplicate",
            )

        assignment_id = _safe_text(candidate.get("assignment_id"))
        if _safe_text(candidate.get("event_type")) == LifecycleEventType.ASSIGNMENT.value:
            for existing in rows:
                if _safe_text(existing.get("event_type")) != LifecycleEventType.ASSIGNMENT.value:
                    continue
                if _safe_text(existing.get("assignment_id")) != assignment_id:
                    continue
                if _safe_text(existing.get("assignment_hash")) != _safe_text(candidate.get("assignment_hash")):
                    raise ExperimentLifecycleConflictError("assignment_reproducibility_violation")
                if _safe_text(existing.get("assigned_variant")) != _safe_text(candidate.get("assigned_variant")):
                    raise ExperimentLifecycleConflictError("assignment_variant_conflict")

        if _safe_text(candidate.get("event_type")) == LifecycleEventType.EXPOSURE.value:
            dedupe_key = _safe_text(candidate.get("exposure_dedupe_key"))
            for existing in rows:
                if _safe_text(existing.get("event_type")) != LifecycleEventType.EXPOSURE.value:
                    continue
                if _safe_text(existing.get("exposure_dedupe_key")) != dedupe_key:
                    continue
                return ExperimentLifecycleAppendResult(
                    appended=False,
                    duplicate=True,
                    conflict=False,
                    assignment_id=_safe_text(existing.get("assignment_id")),
                    lifecycle_event_id=_safe_text(existing.get("lifecycle_event_id")),
                    record_hash=_safe_text(existing.get("record_hash")),
                    reason="duplicate_exposure_dedupe_key",
                )

        self._append_row(candidate)
        return ExperimentLifecycleAppendResult(
            appended=True,
            duplicate=False,
            conflict=False,
            assignment_id=_safe_text(candidate.get("assignment_id")),
            lifecycle_event_id=_safe_text(candidate.get("lifecycle_event_id")),
            record_hash=_safe_text(candidate.get("record_hash")),
            reason="appended",
        )

    def append_assignment_event(
        self,
        payload: dict[str, Any],
        *,
        created_by: str,
        source_module: str,
        source_version: str,
        created_at: str | None = None,
    ) -> ExperimentLifecycleAppendResult:
        return self._append_event(
            payload,
            created_by=created_by,
            source_module=source_module,
            source_version=source_version,
            created_at=created_at,
            event_type=LifecycleEventType.ASSIGNMENT.value,
        )

    def append_exposure_event(
        self,
        payload: dict[str, Any],
        *,
        created_by: str,
        source_module: str,
        source_version: str,
        created_at: str | None = None,
    ) -> ExperimentLifecycleAppendResult:
        return self._append_event(
            payload,
            created_by=created_by,
            source_module=source_module,
            source_version=source_version,
            created_at=created_at,
            event_type=LifecycleEventType.EXPOSURE.value,
        )

    def append_contamination_event(
        self,
        payload: dict[str, Any],
        *,
        created_by: str,
        source_module: str,
        source_version: str,
        created_at: str | None = None,
    ) -> ExperimentLifecycleAppendResult:
        return self._append_event(
            payload,
            created_by=created_by,
            source_module=source_module,
            source_version=source_version,
            created_at=created_at,
            event_type=LifecycleEventType.CONTAMINATION.value,
        )

    def get_rows(self) -> list[dict[str, Any]]:
        return list(self._require_clean_history())

    def replay(self) -> tuple[dict[str, Any], ExperimentLifecycleReplayDiagnostics]:
        rows = self.get_rows()
        return build_experiment_projection_from_rows(rows), self._load()[1]

    def verify_hash_chain(self) -> dict[str, Any]:
        rows = self.get_rows()
        valid, issues, last_hash = _verify_hash_chain(rows)
        return {
            "schema_version": EXPERIMENT_LIFECYCLE_SCHEMA_VERSION,
            "valid": valid,
            "row_count": len(rows),
            "issues": issues,
            "last_record_hash": last_hash,
        }


def build_experiment_lifecycle_audit_summary(*, store: ExperimentLifecycleStore) -> dict[str, Any]:
    projection, diagnostics = store.replay()
    hash_chain = store.verify_hash_chain()
    return {
        "schema_version": EXPERIMENT_LIFECYCLE_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "row_count": len(store.get_rows()),
        "malformed_rows": diagnostics.malformed_rows,
        "partial_trailing_rows": diagnostics.partial_trailing_rows,
        "duplicate_rows": diagnostics.duplicate_rows,
        "replay_errors": list(diagnostics.replay_errors),
        "hash_chain": hash_chain,
        "assignment_count": len(projection["current_assignment_by_id"]),
        "exposure_count": len(projection["exposure_events"]),
        "contamination_count": len(projection["contamination_events"]),
        "contamination_severity_counts": projection["contamination_severity_counts"],
        "assignment_reproducibility_violations": projection["assignment_reproducibility_violations"],
        "exposure_duplicates_suppressed": projection["exposure_duplicates_suppressed"],
        "projection_identity": projection["projection_identity"],
        "projection_hash": projection["projection_hash"],
        "advisory_only": True,
        "pipeline_output_changed": False,
    }
