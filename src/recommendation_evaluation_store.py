from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any

from .recommendation_evaluation_contract import (
    RECOMMENDATION_EVALUATION_SCHEMA_VERSION,
    build_recommendation_evaluation_record,
    validate_recommendation_evaluation_row,
)
from .recommendation_evaluation_projection import build_recommendation_evaluation_projection_from_rows


DEFAULT_RECOMMENDATION_EVALUATION_PATH = Path("logs/recommendation_evaluation.jsonl")


class RecommendationEvaluationError(RuntimeError):
    pass


class RecommendationEvaluationCorruptionError(RecommendationEvaluationError):
    pass


class RecommendationEvaluationConflictError(RecommendationEvaluationError):
    pass


@dataclass(frozen=True, slots=True)
class RecommendationEvaluationAppendResult:
    appended: bool
    duplicate: bool
    conflict: bool
    evaluation_id: str
    evaluation_event_id: str
    record_hash: str
    reason: str


@dataclass(frozen=True, slots=True)
class RecommendationEvaluationReplayDiagnostics:
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
                if key in {"record_hash", "evaluation_event_id", "created_at", "previous_record_hash"}:
                    continue
                out[key] = _strip(item)
            return out
        if isinstance(value, list):
            return [_strip(item) for item in value]
        if isinstance(value, tuple):
            return [_strip(item) for item in value]
        return value

    return _stable_json(_strip(dict(record)))


def _compute_record_hash(record: dict[str, Any]) -> str:
    payload = dict(record)
    payload.pop("record_hash", None)
    payload.pop("evaluation_event_id", None)
    payload.pop("previous_record_hash", None)
    payload.pop("created_at", None)
    return "reh_" + __import__("hashlib").sha256(_stable_json(payload).encode("utf-8")).hexdigest()[:24]


def _compute_evaluation_event_id(record: dict[str, Any]) -> str:
    payload = {
        "evaluation_id": _safe_text(record.get("evaluation_id")),
        "evaluation_state": _safe_text(record.get("evaluation_state")),
        "evaluation_fingerprint": _safe_text(record.get("evaluation_fingerprint")),
        "record_hash": _safe_text(record.get("record_hash")),
    }
    return "ree_" + __import__("hashlib").sha256(_stable_json(payload).encode("utf-8")).hexdigest()[:24]


def _validate_store_row(row: dict[str, Any], original_row: dict[str, Any] | None = None) -> dict[str, Any]:
    merged = dict(row)
    source_row = dict(original_row or row)
    if _safe_text(merged.get("evaluation_schema_version")) != RECOMMENDATION_EVALUATION_SCHEMA_VERSION:
        raise ValueError("invalid_field:evaluation_schema_version")

    for field in ("created_by", "source_module", "source_version"):
        merged[field] = _safe_text(merged.get(field))
        if not merged[field]:
            raise ValueError(f"missing_field:{field}")

    merged = validate_recommendation_evaluation_row(merged, original_row=source_row)
    merged["previous_record_hash"] = _safe_text(merged.get("previous_record_hash")) or None
    expected_record_hash = _compute_record_hash(merged)
    supplied_record_hash = _safe_text(source_row.get("record_hash"))
    if supplied_record_hash and supplied_record_hash != expected_record_hash:
        raise ValueError("invalid_field:record_hash")
    merged["record_hash"] = expected_record_hash

    expected_event_id = _compute_evaluation_event_id(merged)
    supplied_event_id = _safe_text(source_row.get("evaluation_event_id"))
    if supplied_event_id and supplied_event_id != expected_event_id:
        raise ValueError("invalid_field:evaluation_event_id")
    merged["evaluation_event_id"] = expected_event_id
    return merged


def _build_store_row(
    payload: dict[str, Any],
    *,
    created_by: str,
    source_module: str,
    source_version: str,
    created_at: str | None = None,
    previous_record_hash: str | None = None,
) -> dict[str, Any]:
    evaluator_version = _safe_text(payload.get("evaluator_version"))
    if not evaluator_version:
        raise ValueError("missing_field:evaluator_version")
    record = build_recommendation_evaluation_record(
        payload,
        evaluator_version=evaluator_version,
        created_at=created_at,
    )
    record["created_by"] = _safe_text(created_by)
    record["source_module"] = _safe_text(source_module)
    record["source_version"] = _safe_text(source_version)
    record["previous_record_hash"] = previous_record_hash
    return _validate_store_row(record, original_row=record)


def _load_raw_rows(path: Path) -> tuple[list[dict[str, Any]], RecommendationEvaluationReplayDiagnostics]:
    if not path.exists():
        return [], RecommendationEvaluationReplayDiagnostics(0, 0, 0, 0, 0, [])

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
            validated = _validate_store_row(decoded)
            signature = _dedupe_signature(validated)
            if signature in seen:
                duplicate += 1
            else:
                seen.add(signature)
            rows.append(validated)
        except Exception as exc:
            malformed += 1
            if "schema_version" in str(exc) or "evaluation_schema_version" in str(exc):
                unsupported += 1
            if index == len(lines) and not ends_with_newline:
                partial += 1
            errors.append(f"line={index}:{exc}")

    if rows:
        ok, issues, _last = _verify_hash_chain(rows)
        if not ok:
            broken = len(issues)

    return rows, RecommendationEvaluationReplayDiagnostics(malformed, partial, duplicate, unsupported, broken, errors)


def _verify_hash_chain(rows: list[dict[str, Any]]) -> tuple[bool, list[str], str | None]:
    issues: list[str] = []
    previous_hash: str | None = None
    for index, row in enumerate(rows, start=1):
        row_previous = _safe_text(row.get("previous_record_hash")) or None
        if row_previous != previous_hash:
            issues.append(f"chain_break_at={index}")
        expected = _build_store_row(
            dict(row),
            created_by=_safe_text(row.get("created_by")),
            source_module=_safe_text(row.get("source_module")),
            source_version=_safe_text(row.get("source_version")),
            created_at=_safe_text(row.get("created_at")),
            previous_record_hash=row_previous,
        )
        if _safe_text(expected.get("record_hash")) != _safe_text(row.get("record_hash")):
            issues.append(f"record_hash_mismatch_at={index}")
        previous_hash = _safe_text(row.get("record_hash")) or None
    return len(issues) == 0, issues, previous_hash


class RecommendationEvaluationStore:
    def __init__(self, *, evaluation_path: Path | str = DEFAULT_RECOMMENDATION_EVALUATION_PATH):
        self.evaluation_path = Path(evaluation_path)
        self._cache_rows: list[dict[str, Any]] | None = None
        self._cache_diagnostics: RecommendationEvaluationReplayDiagnostics | None = None

    def _load(self) -> tuple[list[dict[str, Any]], RecommendationEvaluationReplayDiagnostics]:
        if self._cache_rows is not None and self._cache_diagnostics is not None:
            return self._cache_rows, self._cache_diagnostics
        rows, diagnostics = _load_raw_rows(self.evaluation_path)
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
            raise RecommendationEvaluationCorruptionError(
                "corrupt_recommendation_evaluation: "
                f"malformed_rows={diagnostics.malformed_rows} "
                f"partial_trailing_rows={diagnostics.partial_trailing_rows} "
                f"duplicate_rows={diagnostics.duplicate_rows} "
                f"unsupported_schema_rows={diagnostics.unsupported_schema_rows} "
                f"broken_hash_links={diagnostics.broken_hash_links}"
            )
        return rows

    def _append_row(self, row: dict[str, Any]) -> None:
        self.evaluation_path.parent.mkdir(parents=True, exist_ok=True)
        blob = _stable_json(row) + "\n"
        fd = os.open(self.evaluation_path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
        try:
            os.write(fd, blob.encode("utf-8"))
        finally:
            os.close(fd)
        self._cache_rows = None
        self._cache_diagnostics = None

    def append_evaluation_event(
        self,
        payload: dict[str, Any],
        *,
        created_by: str,
        source_module: str,
        source_version: str,
        created_at: str | None = None,
    ) -> RecommendationEvaluationAppendResult:
        rows = self._require_clean_history()
        previous_record_hash = rows[-1]["record_hash"] if rows else None
        candidate = _build_store_row(
            payload,
            created_by=created_by,
            source_module=source_module,
            source_version=source_version,
            created_at=created_at,
            previous_record_hash=previous_record_hash,
        )
        signature = _dedupe_signature(candidate)
        for existing in rows:
            existing_signature = _dedupe_signature(existing)
            if existing_signature == signature:
                return RecommendationEvaluationAppendResult(
                    appended=False,
                    duplicate=True,
                    conflict=False,
                    evaluation_id=_safe_text(existing.get("evaluation_id")),
                    evaluation_event_id=_safe_text(existing.get("evaluation_event_id")),
                    record_hash=_safe_text(existing.get("record_hash")),
                    reason="exact_duplicate",
                )
            same_recommendation_id = _safe_text(existing.get("recommendation_id")) == _safe_text(candidate.get("recommendation_id"))
            same_evaluation_id = _safe_text(existing.get("evaluation_id")) == _safe_text(candidate.get("evaluation_id"))
            same_event_id = _safe_text(existing.get("evaluation_event_id")) == _safe_text(candidate.get("evaluation_event_id"))
            if same_recommendation_id or same_evaluation_id or same_event_id:
                return RecommendationEvaluationAppendResult(
                    appended=False,
                    duplicate=False,
                    conflict=True,
                    evaluation_id=_safe_text(candidate.get("evaluation_id")),
                    evaluation_event_id=_safe_text(candidate.get("evaluation_event_id")),
                    record_hash=_safe_text(candidate.get("record_hash")),
                    reason="conflicting_duplicate",
                )
        self._append_row(candidate)
        return RecommendationEvaluationAppendResult(
            appended=True,
            duplicate=False,
            conflict=False,
            evaluation_id=_safe_text(candidate.get("evaluation_id")),
            evaluation_event_id=_safe_text(candidate.get("evaluation_event_id")),
            record_hash=_safe_text(candidate.get("record_hash")),
            reason="appended",
        )

    def get_rows(self) -> list[dict[str, Any]]:
        return list(self._require_clean_history())

    def replay(self) -> tuple[dict[str, Any], RecommendationEvaluationReplayDiagnostics]:
        rows = self.get_rows()
        return build_recommendation_evaluation_projection_from_rows(rows), self._load()[1]

    def verify_hash_chain(self) -> dict[str, Any]:
        rows = self.get_rows()
        valid, issues, last_hash = _verify_hash_chain(rows)
        return {
            "schema_version": RECOMMENDATION_EVALUATION_SCHEMA_VERSION,
            "valid": valid,
            "row_count": len(rows),
            "issues": issues,
            "last_record_hash": last_hash,
        }


def build_recommendation_evaluation_audit_summary(*, store: RecommendationEvaluationStore) -> dict[str, Any]:
    projection, diagnostics = store.replay()
    hash_chain = store.verify_hash_chain()
    return {
        "schema_version": RECOMMENDATION_EVALUATION_SCHEMA_VERSION,
        "row_count": len(store.get_rows()),
        "malformed_rows": diagnostics.malformed_rows,
        "partial_trailing_rows": diagnostics.partial_trailing_rows,
        "duplicate_rows": diagnostics.duplicate_rows,
        "replay_errors": list(diagnostics.replay_errors),
        "hash_chain": hash_chain,
        "state_counts": projection["counts_by_evaluation_state"],
        "advisory_result_counts": projection["counts_by_advisory_result"],
        "blocking_reason_counts": projection["counts_by_blocking_reason"],
        "advisory_pass_count": projection["advisory_pass_count"],
        "advisory_fail_count": projection["advisory_fail_count"],
        "blocked_count": projection["blocked_count"],
        "projection_fingerprint": projection["projection_fingerprint"],
        "projection_hash": projection["projection_hash"],
        "advisory_only": True,
    }