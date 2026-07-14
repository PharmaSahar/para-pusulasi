from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

from .decision_contract import (
    DECISION_CONTRACT_SCHEMA_VERSION,
    DecisionState,
    build_decision_record,
    decision_transition_is_valid,
    is_terminal_state,
    validate_decision_record_row,
)


DEFAULT_DECISION_MEMORY_PATH = Path("logs/decision_memory.jsonl")


class DecisionMemoryError(RuntimeError):
    pass


class DecisionMemoryCorruptionError(DecisionMemoryError):
    pass


class DecisionMemoryConflictError(DecisionMemoryError):
    pass


class DecisionMemoryDuplicateError(DecisionMemoryError):
    pass


class DecisionMemoryTransitionError(DecisionMemoryError):
    pass


@dataclass(frozen=True, slots=True)
class DecisionMemoryAppendResult:
    appended: bool
    duplicate: bool
    conflict: bool
    decision_id: str
    decision_event_id: str
    record_hash: str
    reason: str


@dataclass(frozen=True, slots=True)
class DecisionMemoryReplayDiagnostics:
    malformed_rows: int
    partial_trailing_rows: int
    duplicate_rows: int
    unsupported_schema_rows: int
    broken_hash_links: int
    replay_errors: list[str]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _decision_dedupe_signature(record: dict[str, Any]) -> str:
    def _strip_volatile(value: Any) -> Any:
        if isinstance(value, dict):
            cleaned: dict[str, Any] = {}
            for key, item in value.items():
                if key in {"record_hash", "decision_event_id", "created_at", "previous_record_hash"}:
                    continue
                cleaned[key] = _strip_volatile(item)
            return cleaned
        if isinstance(value, list):
            return [_strip_volatile(item) for item in value]
        return value

    return _stable_json(_strip_volatile(dict(record)))


def _classify_evidence_type(evidence_type: str) -> str:
    text = _safe_text(evidence_type).lower()
    if not text:
        return "unknown"
    if text in {"forward_evidence", "runtime_evidence", "execution_evidence", "dashboard_evidence"}:
        return "execution"
    if text in {"planning_blueprint_lineage", "script_lineage", "thumbnail_metadata_lineage", "channel_capability_state", "channel_dna"}:
        return "lineage"
    if text in {"analytics_evidence_join", "analytics_feedback"}:
        return "feedback"
    if text in {"cqga_revalidation"}:
        return "runtime"
    if text in {"experiment_assignment"}:
        return "experimental"
    return text


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _load_raw_rows(path: Path) -> tuple[list[dict[str, Any]], DecisionMemoryReplayDiagnostics]:
    if not path.exists():
        return [], DecisionMemoryReplayDiagnostics(malformed_rows=0, partial_trailing_rows=0, duplicate_rows=0, unsupported_schema_rows=0, broken_hash_links=0, replay_errors=[])

    rows: list[dict[str, Any]] = []
    malformed = 0
    partial_trailing_rows = 0
    duplicate_rows = 0
    unsupported_schema_rows = 0
    broken_hash_links = 0
    errors: list[str] = []
    seen_signatures: set[str] = set()
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    ends_with_newline = text.endswith("\n")

    for index, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            decoded = json.loads(line)
            validated = validate_decision_record_row(decoded)
            signature = _stable_json(
                {
                    k: v
                    for k, v in validated.items()
                    if k not in {"record_hash", "decision_event_id", "created_at", "previous_record_hash"}
                }
            )
            if signature in seen_signatures:
                duplicate_rows += 1
            else:
                seen_signatures.add(signature)
            rows.append(validated)
        except Exception as exc:
            malformed += 1
            if "schema_version" in str(exc):
                unsupported_schema_rows += 1
            if index == len(lines) and not ends_with_newline:
                partial_trailing_rows += 1
            errors.append(f"line={index}:{exc}")

    if rows:
        hash_ok, issues, _last = _verify_hash_chain(rows)
        if not hash_ok:
            broken_hash_links = len(issues)

    return rows, DecisionMemoryReplayDiagnostics(
        malformed_rows=malformed,
        partial_trailing_rows=partial_trailing_rows,
        duplicate_rows=duplicate_rows,
        unsupported_schema_rows=unsupported_schema_rows,
        broken_hash_links=broken_hash_links,
        replay_errors=errors,
    )


def _verify_hash_chain(rows: list[dict[str, Any]]) -> tuple[bool, list[str], str | None]:
    issues: list[str] = []
    previous_hash: str | None = None
    for index, row in enumerate(rows, start=1):
        row_previous = _safe_text(row.get("previous_record_hash")) or None
        expected_previous = previous_hash
        if row_previous != expected_previous:
            issues.append(f"chain_break_at={index}")
        expected_record_hash = _safe_text(build_decision_record(
            dict(row),
            created_by=_safe_text(row.get("created_by")),
            source_module=_safe_text(row.get("source_module")),
            source_version=_safe_text(row.get("source_version")),
            created_at=_safe_text(row.get("created_at")),
            decision_timestamp=_safe_text(row.get("decision_timestamp")),
            decision_state=_safe_text(row.get("decision_state")),
            previous_record_hash=row_previous,
        ).get("record_hash"))
        if expected_record_hash and _safe_text(row.get("record_hash")) != expected_record_hash:
            issues.append(f"record_hash_mismatch_at={index}")
        previous_hash = _safe_text(row.get("record_hash")) or None
    return len(issues) == 0, issues, previous_hash


def load_decision_memory_rows(*, input_path: Path | str = DEFAULT_DECISION_MEMORY_PATH, limit: int = 0) -> tuple[list[dict[str, Any]], DecisionMemoryReplayDiagnostics]:
    path = Path(input_path)
    rows, diagnostics = _load_raw_rows(path)
    if limit > 0:
        rows = rows[-limit:]
    return rows, diagnostics


def build_decision_feature_projection(record: dict[str, Any]) -> dict[str, Any]:
    supporting = list(record.get("supporting_evidence_refs") or [])
    trend_refs = list(record.get("trend_evidence_refs") or [])
    analytics_refs = list(record.get("analytics_evidence_refs") or [])
    cqga_refs = list(record.get("cqga_evidence_refs") or [])
    execution_refs = list(record.get("execution_evidence_refs") or [])
    observed_refs = list(record.get("observed_outcome_refs") or [])
    attribution_refs = list(record.get("attribution_result_refs") or [])
    explanation = record.get("decision_explanation") or {}
    if isinstance(explanation, dict):
        supporting.extend(list(explanation.get("supporting_evidence_refs") or []))
    evidence_refs = supporting + trend_refs + analytics_refs + cqga_refs + execution_refs + observed_refs + attribution_refs
    refs_available = sum(1 for ref in evidence_refs if _safe_text((ref or {}).get("availability_state")) == "available")
    refs_total = max(1, len(evidence_refs))
    evidence_completeness_score = round(refs_available / refs_total, 4)
    evidence_class_distribution: dict[str, int] = {}
    for ref in evidence_refs:
        class_name = _classify_evidence_type(_safe_text((ref or {}).get("evidence_type")))
        evidence_class_distribution[class_name] = evidence_class_distribution.get(class_name, 0) + 1

    selected_topic = _safe_text(record.get("selected_topic"))
    selected_title = _safe_text(record.get("selected_title"))
    selected_thumbnail = _safe_text(record.get("selected_thumbnail"))
    selected_candidates = {
        "selected_topic": selected_topic or None,
        "selected_title": selected_title or None,
        "selected_thumbnail": selected_thumbnail or None,
    }

    def _count(value: Any) -> int:
        if value is None:
            return 0
        if isinstance(value, (list, tuple, set)):
            return len([item for item in value if _safe_text(item)])
        return 1 if _safe_text(value) else 0

    return {
        "decision_id": _safe_text(record.get("decision_id")),
        "decision_event_id": _safe_text(record.get("decision_event_id")),
        "correlation_id": _safe_text(record.get("correlation_id")),
        "channel_id": _safe_text(record.get("channel_id")),
        "content_id": _safe_text(record.get("content_id")),
        "content_type": _safe_text(record.get("content_type")),
        "decision_type": _safe_text(record.get("decision_type")),
        "decision_stage": _safe_text(record.get("decision_stage")),
        "decision_state": _safe_text(record.get("decision_state")),
        "topic_category": selected_topic or None,
        "topic_candidate_count": _count(record.get("topic_candidate_set")),
        "title_candidate_count": _count(record.get("title_candidates")),
        "thumbnail_candidate_count": _count(record.get("thumbnail_candidates")),
        "tag_count": _count(record.get("tag_set")),
        "hashtag_count": _count(record.get("hashtag_set")),
        "title_length": len(selected_title),
        "selected_candidate_identifiers": selected_candidates,
        "trend_evidence_available": bool(trend_refs),
        "playlist_assignment_present": bool(_safe_text(record.get("playlist_decision"))),
        "shorts_strategy_present": bool(_safe_text(record.get("shorts_strategy"))),
        "cross_channel_reuse_present": bool(_safe_text(record.get("cross_channel_reuse_decision"))),
        "experiment_assignment_present": bool(record.get("experiment_assignment_refs")),
        "policy_version": _safe_text((record.get("policy_ref") or {}).get("policy_version")) or _safe_text(record.get("policy_version")),
        "prompt_version": _safe_text((record.get("prompt_ref") or {}).get("prompt_version")) or _safe_text(record.get("prompt_version")),
        "model_version": _safe_text((record.get("model_ref") or {}).get("model_version")) or _safe_text(record.get("model_version")),
        "recommendation_confidence": record.get("recommendation_confidence"),
        "risk_score": record.get("risk_score"),
        "human_approval_state": _safe_text(record.get("human_approval_state")),
        "fallback_status": _safe_text(record.get("fallback_status")),
        "evidence_completeness_score": evidence_completeness_score,
        "evidence_class_distribution": evidence_class_distribution,
        "publish_timing_decision_present": bool(_safe_text(record.get("publish_timing_decision"))),
        "created_at": _safe_text(record.get("created_at")),
        "decision_timestamp": _safe_text(record.get("decision_timestamp")),
    }


def build_decision_projection_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    current_by_decision_id: dict[str, dict[str, Any]] = {}
    timeline_by_decision_id: dict[str, list[dict[str, Any]]] = {}
    decisions_by_content_id: dict[str, list[dict[str, Any]]] = {}
    decisions_by_channel_id: dict[str, list[dict[str, Any]]] = {}
    decisions_by_type: dict[str, list[dict[str, Any]]] = {}
    unresolved_review_required: list[dict[str, Any]] = []
    quarantined: list[dict[str, Any]] = []
    superseded_chain: list[dict[str, Any]] = []
    rollback_history: list[dict[str, Any]] = []
    evidence_reference_index: dict[str, list[str]] = {}
    policy_version_index: dict[str, list[str]] = {}
    prompt_version_index: dict[str, list[str]] = {}
    model_version_index: dict[str, list[str]] = {}
    decision_features: list[dict[str, Any]] = []

    def _append_index(index: dict[str, list[str]], key: str, decision_id: str) -> None:
        if not key:
            return
        bucket = index.setdefault(key, [])
        if decision_id not in bucket:
            bucket.append(decision_id)

    rows_sorted = sorted(rows, key=lambda item: (_safe_text(item.get("decision_timestamp")), _safe_text(item.get("created_at")), _safe_text(item.get("decision_event_id"))))

    for row in rows_sorted:
        decision_id = _safe_text(row.get("decision_id"))
        current_by_decision_id[decision_id] = row
        timeline_by_decision_id.setdefault(decision_id, []).append(row)

        content_id = _safe_text(row.get("content_id"))
        channel_id = _safe_text(row.get("channel_id"))
        decision_type = _safe_text(row.get("decision_type"))
        if content_id:
            decisions_by_content_id.setdefault(content_id, []).append(row)
        if channel_id:
            decisions_by_channel_id.setdefault(channel_id, []).append(row)
        if decision_type:
            decisions_by_type.setdefault(decision_type, []).append(row)

        if _safe_text(row.get("decision_state")) == DecisionState.REVIEW_REQUIRED.value:
            unresolved_review_required.append(row)
        if _safe_text(row.get("decision_state")) == DecisionState.QUARANTINED.value:
            quarantined.append(row)
        if _safe_text(row.get("supersedes_decision_id")):
            superseded_chain.append(row)
        if (
            _safe_text(row.get("rollback_state"))
            or _safe_text(row.get("decision_state")) == DecisionState.ROLLED_BACK.value
            or _safe_text(row.get("final_execution_status"))
        ):
            rollback_history.append(row)

        for ref in row.get("supporting_evidence_refs") or []:
            ref_id = _safe_text((ref or {}).get("evidence_id")) or _safe_text((ref or {}).get("source_path")) or _safe_text((ref or {}).get("evidence_type"))
            _append_index(evidence_reference_index, ref_id, decision_id)
        policy_ref = row.get("policy_ref") or {}
        _append_index(policy_version_index, _safe_text(policy_ref.get("policy_version")), decision_id)
        prompt_ref = row.get("prompt_ref") or {}
        _append_index(prompt_version_index, _safe_text(prompt_ref.get("prompt_version")), decision_id)
        model_ref = row.get("model_ref") or {}
        _append_index(model_version_index, _safe_text(model_ref.get("model_version")), decision_id)

        decision_features.append(build_decision_feature_projection(row))

    return {
        "current_state_by_decision_id": current_by_decision_id,
        "decision_timeline": timeline_by_decision_id,
        "decisions_by_content_id": decisions_by_content_id,
        "decisions_by_channel_id": decisions_by_channel_id,
        "decisions_by_type": decisions_by_type,
        "unresolved_review_required_decisions": unresolved_review_required,
        "quarantined_decisions": quarantined,
        "superseded_decision_chain": superseded_chain,
        "rollback_history": rollback_history,
        "evidence_reference_index": evidence_reference_index,
        "policy_version_index": policy_version_index,
        "prompt_version_index": prompt_version_index,
        "model_version_index": model_version_index,
        "decision_feature_projection": decision_features,
    }


def replay_decision_memory(*, rows: list[dict[str, Any]]) -> tuple[dict[str, Any], DecisionMemoryReplayDiagnostics]:
    state_by_id: dict[str, list[dict[str, Any]]] = {}
    errors: list[str] = []
    malformed_rows = 0

    for row in rows:
        try:
            payload = validate_decision_record_row(row)
            decision_id = _safe_text(payload.get("decision_id"))
            state_by_id.setdefault(decision_id, []).append(payload)
        except Exception as exc:
            malformed_rows += 1
            errors.append(str(exc))

    for events in state_by_id.values():
        events.sort(key=lambda item: (_safe_text(item.get("decision_timestamp")), _safe_text(item.get("created_at")), _safe_text(item.get("decision_event_id"))))

    projections = build_decision_projection_from_rows([row for group in state_by_id.values() for row in group])
    diagnostics = DecisionMemoryReplayDiagnostics(
        malformed_rows=malformed_rows,
        partial_trailing_rows=0,
        duplicate_rows=0,
        unsupported_schema_rows=0,
        broken_hash_links=0,
        replay_errors=errors,
    )
    return projections, diagnostics


class DecisionMemoryStore:
    def __init__(self, *, memory_path: Path | str = DEFAULT_DECISION_MEMORY_PATH):
        self.memory_path = Path(memory_path)
        self._cache_rows: list[dict[str, Any]] | None = None
        self._cache_diagnostics: DecisionMemoryReplayDiagnostics | None = None

    def _load(self) -> tuple[list[dict[str, Any]], DecisionMemoryReplayDiagnostics]:
        if self._cache_rows is not None and self._cache_diagnostics is not None:
            return self._cache_rows, self._cache_diagnostics
        rows, diagnostics = _load_raw_rows(self.memory_path)
        self._cache_rows = rows
        self._cache_diagnostics = diagnostics
        return rows, diagnostics

    def _require_clean_history(self) -> list[dict[str, Any]]:
        rows, diagnostics = self._load()
        if diagnostics.malformed_rows or diagnostics.partial_trailing_rows or diagnostics.duplicate_rows or diagnostics.unsupported_schema_rows or diagnostics.broken_hash_links:
            raise DecisionMemoryCorruptionError(
                "corrupt_decision_memory: "
                f"malformed_rows={diagnostics.malformed_rows} "
                f"partial_trailing_rows={diagnostics.partial_trailing_rows} "
                f"duplicate_rows={diagnostics.duplicate_rows} "
                f"unsupported_schema_rows={diagnostics.unsupported_schema_rows} "
                f"broken_hash_links={diagnostics.broken_hash_links}"
            )
        hash_ok, issues, _last = _verify_hash_chain(rows)
        if not hash_ok:
            raise DecisionMemoryCorruptionError(f"corrupt_decision_memory: {';'.join(issues)}")
        return rows

    def _append_row(self, row: dict[str, Any]) -> None:
        self.memory_path.parent.mkdir(parents=True, exist_ok=True)
        line = _stable_json(row) + "\n"
        fd = os.open(self.memory_path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
        self._cache_rows = None
        self._cache_diagnostics = None

    def append_decision(
        self,
        payload: dict[str, Any],
        *,
        created_by: str,
        source_module: str,
        source_version: str,
        created_at: str | None = None,
        decision_timestamp: str | None = None,
        decision_state: str | DecisionState | None = None,
    ) -> DecisionMemoryAppendResult:
        rows = self._require_clean_history()
        current_projection = build_decision_projection_from_rows(rows)
        current_by_id = current_projection["current_state_by_decision_id"]

        previous_record_hash = rows[-1]["record_hash"] if rows else None
        candidate = build_decision_record(
            payload,
            created_by=created_by,
            source_module=source_module,
            source_version=source_version,
            created_at=created_at,
            decision_timestamp=decision_timestamp,
            decision_state=decision_state,
            previous_record_hash=previous_record_hash,
        )

        decision_id = _safe_text(candidate.get("decision_id"))
        decision_state_value = _safe_text(candidate.get("decision_state"))
        current = current_by_id.get(decision_id)

        dedupe_signature = _decision_dedupe_signature(candidate)
        for existing in rows:
            if _decision_dedupe_signature(existing) != dedupe_signature:
                continue
            if _safe_text(existing.get("decision_state")) == decision_state_value:
                return DecisionMemoryAppendResult(
                    appended=False,
                    duplicate=True,
                    conflict=False,
                    decision_id=decision_id,
                    decision_event_id=_safe_text(existing.get("decision_event_id")),
                    record_hash=_safe_text(existing.get("record_hash")),
                    reason="exact_duplicate",
                )
            raise DecisionMemoryConflictError("conflicting_duplicate_decision_state")

        if current is not None:
            current_state = _safe_text(current.get("decision_state"))
            if current_state == decision_state_value:
                if _decision_dedupe_signature(current) == dedupe_signature:
                    return DecisionMemoryAppendResult(
                        appended=False,
                        duplicate=True,
                        conflict=False,
                        decision_id=decision_id,
                        decision_event_id=_safe_text(current.get("decision_event_id")),
                        record_hash=_safe_text(current.get("record_hash")),
                        reason="exact_duplicate",
                    )
                raise DecisionMemoryConflictError("conflicting_duplicate_decision_state")
            if not decision_transition_is_valid(current_state, decision_state_value):
                raise DecisionMemoryTransitionError(
                    f"invalid_transition:{current_state}->{decision_state_value}"
                )

            if is_terminal_state(current_state):
                raise DecisionMemoryTransitionError(f"invalid_transition_from_terminal_state:{current_state}")

        if _safe_text(candidate.get("supersedes_decision_id")):
            superseded = _safe_text(candidate.get("supersedes_decision_id"))
            if superseded not in current_by_id:
                raise DecisionMemoryConflictError(f"unknown_supersedes_decision_id:{superseded}")

        self._append_row(candidate)
        return DecisionMemoryAppendResult(
            appended=True,
            duplicate=False,
            conflict=False,
            decision_id=decision_id,
            decision_event_id=_safe_text(candidate.get("decision_event_id")),
            record_hash=_safe_text(candidate.get("record_hash")),
            reason="appended",
        )

    def append_state_transition(
        self,
        decision_id: str,
        new_state: str | DecisionState,
        *,
        created_by: str,
        source_module: str,
        source_version: str,
        created_at: str | None = None,
        decision_timestamp: str | None = None,
        reviewer_ref: str | None = None,
        review_reason: str | None = None,
        human_approval_state: str | None = None,
        rollback_reason: str | None = None,
        final_execution_status: str | None = None,
    ) -> DecisionMemoryAppendResult:
        rows = self._require_clean_history()
        current_projection = build_decision_projection_from_rows(rows)
        current = current_projection["current_state_by_decision_id"].get(_safe_text(decision_id))
        if current is None:
            raise DecisionMemoryTransitionError(f"unknown_decision_id:{decision_id}")

        current_state = _safe_text(current.get("decision_state"))
        next_state = new_state.value if isinstance(new_state, DecisionState) else _safe_text(new_state)
        if current_state != next_state and not decision_transition_is_valid(current_state, next_state):
            raise DecisionMemoryTransitionError(f"invalid_transition:{current_state}->{next_state}")

        transition_payload = dict(current)
        transition_payload["decision_state"] = next_state
        if human_approval_state is not None:
            transition_payload["human_approval_state"] = human_approval_state
        if reviewer_ref is not None:
            transition_payload["reviewer_ref"] = reviewer_ref
        if review_reason is not None:
            transition_payload["review_reason"] = review_reason
        if rollback_reason is not None:
            transition_payload["rollback_reason"] = rollback_reason
        if final_execution_status is not None:
            transition_payload["final_execution_status"] = final_execution_status

        transition_payload["decision_rationale"] = transition_payload.get("decision_rationale") or _safe_text(review_reason) or f"state_transition_to_{next_state}"

        return self.append_decision(
            transition_payload,
            created_by=created_by,
            source_module=source_module,
            source_version=source_version,
            created_at=created_at,
            decision_timestamp=decision_timestamp,
            decision_state=next_state,
        )

    def get_rows(self) -> list[dict[str, Any]]:
        return list(self._require_clean_history())

    def get_by_decision_id(self, decision_id: str) -> list[dict[str, Any]]:
        return [row for row in self.get_rows() if _safe_text(row.get("decision_id")) == _safe_text(decision_id)]

    def get_by_correlation_id(self, correlation_id: str) -> list[dict[str, Any]]:
        return [row for row in self.get_rows() if _safe_text(row.get("correlation_id")) == _safe_text(correlation_id)]

    def get_by_content_id(self, content_id: str) -> list[dict[str, Any]]:
        return [row for row in self.get_rows() if _safe_text(row.get("content_id")) == _safe_text(content_id)]

    def get_by_channel_id(self, channel_id: str) -> list[dict[str, Any]]:
        return [row for row in self.get_rows() if _safe_text(row.get("channel_id")) == _safe_text(channel_id)]

    def get_by_decision_type(self, decision_type: str) -> list[dict[str, Any]]:
        return [row for row in self.get_rows() if _safe_text(row.get("decision_type")) == _safe_text(decision_type)]

    def get_by_state(self, decision_state: str | DecisionState) -> list[dict[str, Any]]:
        state_value = decision_state.value if isinstance(decision_state, DecisionState) else _safe_text(decision_state)
        return [row for row in self.get_rows() if _safe_text(row.get("decision_state")) == state_value]

    def get_by_time_range(self, start_iso: str, end_iso: str) -> list[dict[str, Any]]:
        start = datetime.fromisoformat(_safe_text(start_iso).replace("Z", "+00:00"))
        end = datetime.fromisoformat(_safe_text(end_iso).replace("Z", "+00:00"))
        out: list[dict[str, Any]] = []
        for row in self.get_rows():
            ts = datetime.fromisoformat(_safe_text(row.get("decision_timestamp")).replace("Z", "+00:00"))
            if start <= ts <= end:
                out.append(row)
        return out

    def replay(self) -> tuple[dict[str, Any], DecisionMemoryReplayDiagnostics]:
        rows = self.get_rows()
        projections = build_decision_projection_from_rows(rows)
        return projections, self._load()[1]

    def verify_hash_chain(self) -> dict[str, Any]:
        rows = self.get_rows()
        ok, issues, last_hash = _verify_hash_chain(rows)
        return {
            "schema_version": DECISION_CONTRACT_SCHEMA_VERSION,
            "valid": ok,
            "row_count": len(rows),
            "issues": issues,
            "last_record_hash": last_hash,
        }


def build_decision_memory_audit_summary(*, store: DecisionMemoryStore) -> dict[str, Any]:
    projections, diagnostics = store.replay()
    hash_chain = store.verify_hash_chain()
    return {
        "schema_version": DECISION_CONTRACT_SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "row_count": len(store.get_rows()),
        "malformed_rows": diagnostics.malformed_rows,
        "partial_trailing_rows": diagnostics.partial_trailing_rows,
        "replay_errors": list(diagnostics.replay_errors),
        "hash_chain": hash_chain,
        "current_state_count": len(projections["current_state_by_decision_id"]),
        "review_required_count": len(projections["unresolved_review_required_decisions"]),
        "quarantined_count": len(projections["quarantined_decisions"]),
        "feature_projection_count": len(projections["decision_feature_projection"]),
        "advisory_only": True,
        "pipeline_output_changed": False,
    }
