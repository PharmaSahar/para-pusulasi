from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

from .learning_feature_projection import build_learning_index_from_rows
from .learning_record_contract import (
    LEARNING_RECORD_SCHEMA_VERSION,
    LearningMaturityState,
    build_learning_record,
    validate_learning_record_row,
    validate_maturity_transition,
)


DEFAULT_HISTORICAL_LEARNING_PATH = Path("logs/historical_learning.jsonl")


class HistoricalLearningError(RuntimeError):
    pass


class HistoricalLearningCorruptionError(HistoricalLearningError):
    pass


class HistoricalLearningConflictError(HistoricalLearningError):
    pass


@dataclass(frozen=True, slots=True)
class HistoricalLearningAppendResult:
    appended: bool
    duplicate: bool
    conflict: bool
    learning_record_id: str
    learning_event_id: str
    record_hash: str
    reason: str


@dataclass(frozen=True, slots=True)
class HistoricalLearningReplayDiagnostics:
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
                if key in {"record_hash", "learning_event_id", "created_at", "previous_record_hash"}:
                    continue
                out[key] = _strip(item)
            return out
        if isinstance(value, list):
            return [_strip(item) for item in value]
        return value

    return _stable_json(_strip(dict(record)))


def _load_raw_rows(path: Path) -> tuple[list[dict[str, Any]], HistoricalLearningReplayDiagnostics]:
    if not path.exists():
        return [], HistoricalLearningReplayDiagnostics(0, 0, 0, 0, 0, [])

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
            validated = validate_learning_record_row(decoded)
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

    return rows, HistoricalLearningReplayDiagnostics(malformed, partial, duplicate, unsupported, broken, errors)


def _verify_hash_chain(rows: list[dict[str, Any]]) -> tuple[bool, list[str], str | None]:
    issues: list[str] = []
    previous_hash: str | None = None

    for index, row in enumerate(rows, start=1):
        row_previous = _safe_text(row.get("previous_record_hash")) or None
        if row_previous != previous_hash:
            issues.append(f"chain_break_at={index}")

        expected = build_learning_record(
            dict(row),
            created_by=_safe_text(row.get("created_by")),
            source_module=_safe_text(row.get("source_module")),
            source_version=_safe_text(row.get("source_version")),
            created_at=_safe_text(row.get("created_at")),
            previous_record_hash=row_previous,
            event_type=_safe_text(row.get("event_type")),
            maturity_state=_safe_text(row.get("maturity_state")),
        )
        if _safe_text(expected.get("record_hash")) != _safe_text(row.get("record_hash")):
            issues.append(f"record_hash_mismatch_at={index}")
        previous_hash = _safe_text(row.get("record_hash")) or None

    return len(issues) == 0, issues, previous_hash


class HistoricalLearningStore:
    def __init__(self, *, learning_path: Path | str = DEFAULT_HISTORICAL_LEARNING_PATH):
        self.learning_path = Path(learning_path)
        self._cache_rows: list[dict[str, Any]] | None = None
        self._cache_diagnostics: HistoricalLearningReplayDiagnostics | None = None

    def _load(self) -> tuple[list[dict[str, Any]], HistoricalLearningReplayDiagnostics]:
        if self._cache_rows is not None and self._cache_diagnostics is not None:
            return self._cache_rows, self._cache_diagnostics
        rows, diagnostics = _load_raw_rows(self.learning_path)
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
            raise HistoricalLearningCorruptionError(
                "corrupt_historical_learning: "
                f"malformed_rows={diagnostics.malformed_rows} "
                f"partial_trailing_rows={diagnostics.partial_trailing_rows} "
                f"duplicate_rows={diagnostics.duplicate_rows} "
                f"unsupported_schema_rows={diagnostics.unsupported_schema_rows} "
                f"broken_hash_links={diagnostics.broken_hash_links}"
            )
        return rows

    def _append_row(self, row: dict[str, Any]) -> None:
        self.learning_path.parent.mkdir(parents=True, exist_ok=True)
        blob = _stable_json(row) + "\n"
        fd = os.open(self.learning_path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
        try:
            os.write(fd, blob.encode("utf-8"))
        finally:
            os.close(fd)
        self._cache_rows = None
        self._cache_diagnostics = None

    def append_learning_event(
        self,
        payload: dict[str, Any],
        *,
        created_by: str,
        source_module: str,
        source_version: str,
        created_at: str | None = None,
        event_type: str | None = None,
        maturity_state: str | None = None,
    ) -> HistoricalLearningAppendResult:
        rows = self._require_clean_history()
        projection = build_learning_index_from_rows(rows)
        current_by_id = projection["current_state_by_learning_record_id"]

        previous_record_hash = rows[-1]["record_hash"] if rows else None
        candidate = build_learning_record(
            payload,
            created_by=created_by,
            source_module=source_module,
            source_version=source_version,
            created_at=created_at,
            previous_record_hash=previous_record_hash,
            event_type=event_type,
            maturity_state=maturity_state,
        )

        record_id = _safe_text(candidate.get("learning_record_id"))
        event_type_value = _safe_text(candidate.get("event_type"))
        maturity_value = _safe_text(candidate.get("maturity_state"))
        current = current_by_id.get(record_id)

        signature = _dedupe_signature(candidate)
        for existing in rows:
            if _dedupe_signature(existing) != signature:
                continue
            return HistoricalLearningAppendResult(
                appended=False,
                duplicate=True,
                conflict=False,
                learning_record_id=record_id,
                learning_event_id=_safe_text(existing.get("learning_event_id")),
                record_hash=_safe_text(existing.get("record_hash")),
                reason="exact_duplicate",
            )

        if current is not None:
            current_maturity = _safe_text(current.get("maturity_state"))
            if maturity_value != current_maturity and not validate_maturity_transition(current_maturity, maturity_value):
                raise HistoricalLearningConflictError(f"invalid_maturity_transition:{current_maturity}->{maturity_value}")
            if current_maturity == LearningMaturityState.ARCHIVED.value and event_type_value != "archival":
                raise HistoricalLearningConflictError("invalid_event_after_archived")

        self._append_row(candidate)
        return HistoricalLearningAppendResult(
            appended=True,
            duplicate=False,
            conflict=False,
            learning_record_id=record_id,
            learning_event_id=_safe_text(candidate.get("learning_event_id")),
            record_hash=_safe_text(candidate.get("record_hash")),
            reason="appended",
        )

    def get_rows(self) -> list[dict[str, Any]]:
        return list(self._require_clean_history())

    def replay(self) -> tuple[dict[str, Any], HistoricalLearningReplayDiagnostics]:
        rows = self.get_rows()
        return build_learning_index_from_rows(rows), self._load()[1]

    def verify_hash_chain(self) -> dict[str, Any]:
        rows = self.get_rows()
        valid, issues, last_hash = _verify_hash_chain(rows)
        return {
            "schema_version": LEARNING_RECORD_SCHEMA_VERSION,
            "valid": valid,
            "row_count": len(rows),
            "issues": issues,
            "last_record_hash": last_hash,
        }


def build_historical_learning_audit_summary(*, store: HistoricalLearningStore) -> dict[str, Any]:
    projection, diagnostics = store.replay()
    hash_chain = store.verify_hash_chain()
    return {
        "schema_version": LEARNING_RECORD_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "row_count": len(store.get_rows()),
        "malformed_rows": diagnostics.malformed_rows,
        "partial_trailing_rows": diagnostics.partial_trailing_rows,
        "replay_errors": list(diagnostics.replay_errors),
        "hash_chain": hash_chain,
        "current_state_count": len(projection["current_state_by_learning_record_id"]),
        "learning_index_count": len(projection["learning_index"]),
        "advisory_only": True,
        "pipeline_output_changed": False,
    }
