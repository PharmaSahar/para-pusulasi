from __future__ import annotations

import hashlib
import json
from typing import Any

from .causal_attribution_contract import CausalAttributionState


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _sha(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def build_causal_attribution_projection_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(
        rows,
        key=lambda item: (
            _safe_text(item.get("created_at")),
            _safe_text(item.get("attribution_record_id")),
            _safe_text(item.get("attribution_event_id")),
        ),
    )

    latest_by_record_id: dict[str, dict[str, Any]] = {}
    latest_valid_by_record_id: dict[str, dict[str, Any]] = {}
    timeline_by_record_id: dict[str, list[dict[str, Any]]] = {}
    state_counts = {state.value: 0 for state in CausalAttributionState}
    confounder_status_counts: dict[str, int] = {}
    counterfactual_status_counts: dict[str, int] = {}
    blocking_reason_counts: dict[str, int] = {}
    attribution_eligible_count = 0
    invalidated_count = 0
    replay_verification_failures = 0

    for row in ordered:
        record_id = _safe_text(row.get("attribution_record_id"))
        latest_by_record_id[record_id] = row
        timeline_by_record_id.setdefault(record_id, []).append(row)

        state = _safe_text(row.get("attribution_state"))
        if state in state_counts:
            state_counts[state] += 1
        if state != CausalAttributionState.INVALIDATED.value:
            latest_valid_by_record_id[record_id] = row

        if state in {
            CausalAttributionState.ATTRIBUTION_ELIGIBLE.value,
            CausalAttributionState.CAUSALLY_INCONCLUSIVE.value,
            CausalAttributionState.CAUSALLY_SUPPORTED.value,
        }:
            attribution_eligible_count += 1

        if state == CausalAttributionState.INVALIDATED.value:
            invalidated_count += 1

        confounder_status = _safe_text(row.get("confounder_status")) or "UNKNOWN"
        confounder_status_counts[confounder_status] = confounder_status_counts.get(confounder_status, 0) + 1

        counterfactual_status = _safe_text(row.get("counterfactual_status")) or "UNKNOWN"
        counterfactual_status_counts[counterfactual_status] = counterfactual_status_counts.get(counterfactual_status, 0) + 1

        reason = _safe_text(row.get("attribution_reason")) or "unspecified"
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
        "confounder_status_counts": confounder_status_counts,
        "counterfactual_status_counts": counterfactual_status_counts,
        "blocking_reason_counts": blocking_reason_counts,
    }
    projection_identity = "cap_" + _sha(_stable_json(identity_payload))[:24]
    projection_hash = "caph_" + _sha(_stable_json({"identity": projection_identity, "payload": identity_payload}))[:24]

    return {
        "latest_by_record_id": latest_by_record_id,
        "latest_valid_by_record_id": latest_valid_by_record_id,
        "timeline_by_record_id": timeline_by_record_id,
        "state_counts": state_counts,
        "confounder_status_counts": confounder_status_counts,
        "counterfactual_status_counts": counterfactual_status_counts,
        "blocking_reason_counts": blocking_reason_counts,
        "attribution_eligible_count": attribution_eligible_count,
        "invalidated_count": invalidated_count,
        "replay_verification_failures": replay_verification_failures,
        "projection_identity": projection_identity,
        "projection_hash": projection_hash,
    }
