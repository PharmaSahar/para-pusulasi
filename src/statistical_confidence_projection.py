from __future__ import annotations

import hashlib
import json
from typing import Any

from .statistical_confidence_contract import StatisticalConfidenceState


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _sha(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def build_statistical_confidence_projection_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(
        rows,
        key=lambda item: (
            _safe_text(item.get("created_at")),
            _safe_text(item.get("confidence_id")),
        ),
    )

    current_by_confidence_id: dict[str, dict[str, Any]] = {}
    confidence_timeline_by_id: dict[str, list[dict[str, Any]]] = {}
    state_counts = {state.value: 0 for state in StatisticalConfidenceState}
    experiment_ids: list[str] = []
    sample_size_total = 0
    control_size_total = 0
    treatment_size_total = 0
    lineage_count_total = 0
    lineages_complete = 0
    replay_verification_failures = 0

    for row in ordered:
        confidence_id = _safe_text(row.get("confidence_id"))
        current_by_confidence_id[confidence_id] = row
        confidence_timeline_by_id.setdefault(confidence_id, []).append(row)

        state = _safe_text(row.get("confidence_state"))
        if state in state_counts:
            state_counts[state] += 1
        experiment_id = _safe_text(row.get("experiment_id"))
        if experiment_id and experiment_id not in experiment_ids:
            experiment_ids.append(experiment_id)
        sample_size_total += int(row.get("sample_size") or 0)
        control_size_total += int(row.get("control_size") or 0)
        treatment_size_total += int(row.get("treatment_size") or 0)
        lineage = row.get("lineage_reference") or ()
        lineage_count_total += len(lineage)
        if lineage:
            lineages_complete += 1
        if not bool(row.get("replay_integrity_verified", True)):
            replay_verification_failures += 1

    projection_identity_payload = {
        "row_count": len(ordered),
        "experiment_ids": sorted(experiment_ids),
        "confidence_ids": sorted(current_by_confidence_id.keys()),
        "state_counts": state_counts,
    }
    projection_identity = "scp_" + _sha(_stable_json(projection_identity_payload))[:24]
    projection_hash = "scph_" + _sha(_stable_json({"identity": projection_identity, "payload": projection_identity_payload}))[:24]

    return {
        "current_by_confidence_id": current_by_confidence_id,
        "confidence_timeline_by_id": confidence_timeline_by_id,
        "state_counts": state_counts,
        "experiment_ids": experiment_ids,
        "sample_size_total": sample_size_total,
        "control_size_total": control_size_total,
        "treatment_size_total": treatment_size_total,
        "lineage_count_total": lineage_count_total,
        "lineage_completeness_average": 0.0 if not ordered else round(lineages_complete / len(ordered), 4),
        "replay_verification_failures": replay_verification_failures,
        "projection_identity": projection_identity,
        "projection_hash": projection_hash,
    }
