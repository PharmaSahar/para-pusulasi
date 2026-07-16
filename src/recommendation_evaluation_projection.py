from __future__ import annotations

import hashlib
import json
from typing import Any

from .recommendation_evaluation_contract import RecommendationAdvisoryResult, RecommendationEvaluationState


RECOMMENDATION_EVALUATION_PROJECTION_SCHEMA_VERSION = "v1"


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _sha(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def build_recommendation_evaluation_projection_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(
        rows,
        key=lambda item: (
            _safe_text(item.get("created_at")),
            _safe_text(item.get("evaluation_id")),
            _safe_text(item.get("evaluation_event_id")),
        ),
    )

    state_counts = {state.value: 0 for state in RecommendationEvaluationState}
    advisory_result_counts = {result.value: 0 for result in RecommendationAdvisoryResult}
    blocking_reason_counts: dict[str, int] = {}
    latest_by_recommendation_id: dict[str, dict[str, Any]] = {}
    latest_valid_by_recommendation_id: dict[str, dict[str, Any]] = {}
    timeline_by_recommendation_id: dict[str, list[dict[str, Any]]] = {}

    advisory_pass_count = 0
    advisory_fail_count = 0
    blocked_count = 0

    for row in ordered:
        recommendation_id = _safe_text(row.get("recommendation_id"))
        latest_by_recommendation_id[recommendation_id] = row
        timeline_by_recommendation_id.setdefault(recommendation_id, []).append(row)

        state = _safe_text(row.get("evaluation_state"))
        if state in state_counts:
            state_counts[state] += 1

        advisory_result = _safe_text(row.get("advisory_result"))
        if advisory_result in advisory_result_counts:
            advisory_result_counts[advisory_result] += 1

        for reason in row.get("blocking_reasons") or ():
            reason_key = _safe_text(reason)
            blocking_reason_counts[reason_key] = blocking_reason_counts.get(reason_key, 0) + 1

        if state == RecommendationEvaluationState.ADVISORY_PASS.value:
            advisory_pass_count += 1
        if state == RecommendationEvaluationState.ADVISORY_FAIL.value:
            advisory_fail_count += 1
        if state == RecommendationEvaluationState.BLOCKED.value:
            blocked_count += 1

        if state != RecommendationEvaluationState.BLOCKED.value:
            latest_valid_by_recommendation_id[recommendation_id] = row

    identity_payload = {
        "schema_version": RECOMMENDATION_EVALUATION_PROJECTION_SCHEMA_VERSION,
        "row_count": len(ordered),
        "recommendation_ids": sorted(latest_by_recommendation_id.keys()),
        "state_counts": state_counts,
        "advisory_result_counts": advisory_result_counts,
        "blocking_reason_counts": blocking_reason_counts,
    }
    projection_fingerprint = "repf_" + _sha(_stable_json(identity_payload))[:24]
    projection_hash = "reph_" + _sha(_stable_json({"identity": projection_fingerprint, "payload": identity_payload}))[:24]

    return {
        "projection_schema_version": RECOMMENDATION_EVALUATION_PROJECTION_SCHEMA_VERSION,
        "total_evaluation_count": len(ordered),
        "counts_by_evaluation_state": state_counts,
        "counts_by_advisory_result": advisory_result_counts,
        "counts_by_blocking_reason": blocking_reason_counts,
        "latest_by_recommendation_id": latest_by_recommendation_id,
        "latest_valid_by_recommendation_id": latest_valid_by_recommendation_id,
        "timeline_by_recommendation_id": timeline_by_recommendation_id,
        "advisory_pass_count": advisory_pass_count,
        "advisory_fail_count": advisory_fail_count,
        "blocked_count": blocked_count,
        "projection_fingerprint": projection_fingerprint,
        "projection_hash": projection_hash,
    }