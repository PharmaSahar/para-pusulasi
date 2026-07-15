from __future__ import annotations

import hashlib
import json
from typing import Any

from .recommendation_contract import RecommendationState


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _sha(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def build_recommendation_projection_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(
        rows,
        key=lambda item: (
            _safe_text(item.get("created_at")),
            _safe_text(item.get("recommendation_record_id")),
            _safe_text(item.get("recommendation_event_id")),
        ),
    )

    latest_by_record_id: dict[str, dict[str, Any]] = {}
    latest_valid_by_record_id: dict[str, dict[str, Any]] = {}
    timeline_by_record_id: dict[str, list[dict[str, Any]]] = {}

    state_counts = {state.value: 0 for state in RecommendationState}
    policy_status_counts: dict[str, int] = {}
    blocking_reason_counts: dict[str, int] = {}

    recommendation_eligible_count = 0
    advisory_recommendation_count = 0
    human_review_required_count = 0
    invalidated_count = 0
    replay_verification_failures = 0

    for row in ordered:
        record_id = _safe_text(row.get("recommendation_record_id"))
        latest_by_record_id[record_id] = row
        timeline_by_record_id.setdefault(record_id, []).append(row)

        state = _safe_text(row.get("recommendation_state"))
        if state in state_counts:
            state_counts[state] += 1

        if state != RecommendationState.INVALIDATED.value:
            latest_valid_by_record_id[record_id] = row

        if state in {
            RecommendationState.RECOMMENDATION_ELIGIBLE.value,
            RecommendationState.ADVISORY_RECOMMENDATION.value,
            RecommendationState.HUMAN_REVIEW_REQUIRED.value,
        }:
            recommendation_eligible_count += 1

        if state == RecommendationState.ADVISORY_RECOMMENDATION.value:
            advisory_recommendation_count += 1

        if bool(row.get("human_review_required", False)):
            human_review_required_count += 1

        if state == RecommendationState.INVALIDATED.value:
            invalidated_count += 1

        policy_status = _safe_text(row.get("recommendation_policy_status")) or "UNKNOWN"
        policy_status_counts[policy_status] = policy_status_counts.get(policy_status, 0) + 1

        reason = _safe_text(row.get("recommendation_reason")) or "unspecified"
        blocking_reason_counts[reason] = blocking_reason_counts.get(reason, 0) + 1

        for reason_item in row.get("invalidation_reasons") or ():
            reason_key = f"invalidation:{_safe_text(reason_item) or 'unspecified'}"
            blocking_reason_counts[reason_key] = blocking_reason_counts.get(reason_key, 0) + 1

        if not bool(row.get("replay_integrity", True)):
            replay_verification_failures += 1

    identity_payload = {
        "row_count": len(ordered),
        "record_ids": sorted(latest_by_record_id.keys()),
        "state_counts": state_counts,
        "policy_status_counts": policy_status_counts,
        "blocking_reason_counts": blocking_reason_counts,
    }
    projection_identity = "rcp_" + _sha(_stable_json(identity_payload))[:24]
    projection_hash = "rcph_" + _sha(_stable_json({"identity": projection_identity, "payload": identity_payload}))[:24]

    return {
        "latest_by_record_id": latest_by_record_id,
        "latest_valid_by_record_id": latest_valid_by_record_id,
        "timeline_by_record_id": timeline_by_record_id,
        "state_counts": state_counts,
        "policy_status_counts": policy_status_counts,
        "blocking_reason_counts": blocking_reason_counts,
        "recommendation_eligible_count": recommendation_eligible_count,
        "advisory_recommendation_count": advisory_recommendation_count,
        "human_review_required_count": human_review_required_count,
        "invalidated_count": invalidated_count,
        "replay_verification_failures": replay_verification_failures,
        "projection_identity": projection_identity,
        "projection_hash": projection_hash,
    }
