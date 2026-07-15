from __future__ import annotations

import hashlib
import json
from typing import Any

from .experiment_evaluation_contract import ExperimentEvaluationState


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _sha(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def build_experiment_evaluation_projection_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(
        rows,
        key=lambda item: (
            _safe_text(item.get("created_at")),
            _safe_text(item.get("evaluation_event_id")),
        ),
    )

    current_by_evaluation_record_id: dict[str, dict[str, Any]] = {}
    evaluation_timeline_by_id: dict[str, list[dict[str, Any]]] = {}
    state_counts = {state.value: 0 for state in ExperimentEvaluationState}
    experiment_ids: list[str] = []
    lineage_completeness_sum = 0.0
    replay_verification_failures = 0

    for row in ordered:
        evaluation_record_id = _safe_text(row.get("evaluation_record_id"))
        current_by_evaluation_record_id[evaluation_record_id] = row
        evaluation_timeline_by_id.setdefault(evaluation_record_id, []).append(row)

        state = _safe_text(row.get("evaluation_state"))
        if state in state_counts:
            state_counts[state] += 1
        experiment_id = _safe_text(row.get("experiment_id"))
        if experiment_id and experiment_id not in experiment_ids:
            experiment_ids.append(experiment_id)
        lineage_completeness_sum += float(row.get("evidence_lineage_completeness") or 0.0)
        if not bool(row.get("replay_integrity_verified", True)):
            replay_verification_failures += 1

    projection_identity_payload = {
        "row_count": len(ordered),
        "experiment_ids": sorted(experiment_ids),
        "evaluation_record_ids": sorted(current_by_evaluation_record_id.keys()),
        "state_counts": state_counts,
    }
    projection_identity = "epr_" + _sha(_stable_json(projection_identity_payload))[:24]
    projection_hash = "eprh_" + _sha(_stable_json({"identity": projection_identity, "payload": projection_identity_payload}))[:24]

    return {
        "current_by_evaluation_record_id": current_by_evaluation_record_id,
        "evaluation_timeline_by_id": evaluation_timeline_by_id,
        "state_counts": state_counts,
        "experiment_ids": experiment_ids,
        "lineage_completeness_average": 0.0 if not ordered else round(lineage_completeness_sum / len(ordered), 4),
        "replay_verification_failures": replay_verification_failures,
        "projection_identity": projection_identity,
        "projection_hash": projection_hash,
    }
