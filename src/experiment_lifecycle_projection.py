from __future__ import annotations

import hashlib
import json
from typing import Any

from .experiment_lifecycle_contract import ContaminationSeverity, LifecycleEventType


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _sha(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def build_experiment_projection_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(
        rows,
        key=lambda item: (
            _safe_text(item.get("created_at")),
            _safe_text(item.get("lifecycle_event_id")),
        ),
    )

    current_assignment_by_id: dict[str, dict[str, Any]] = {}
    assignment_timeline_by_id: dict[str, list[dict[str, Any]]] = {}
    assignment_by_randomization_key: dict[str, dict[str, Any]] = {}
    exposure_events: list[dict[str, Any]] = []
    exposure_by_assignment_id: dict[str, list[dict[str, Any]]] = {}
    contamination_events: list[dict[str, Any]] = []
    contamination_by_assignment_id: dict[str, list[dict[str, Any]]] = {}
    contamination_severity_counts = {
        ContaminationSeverity.LOW.value: 0,
        ContaminationSeverity.MEDIUM.value: 0,
        ContaminationSeverity.HIGH.value: 0,
    }

    assignment_hashes_by_id: dict[str, set[str]] = {}
    assignment_reproducibility_violations: list[dict[str, Any]] = []

    seen_exposure_dedupe_keys: set[str] = set()
    exposure_duplicates_suppressed = 0

    for row in ordered:
        event_type = _safe_text(row.get("event_type"))
        assignment_id = _safe_text(row.get("assignment_id"))

        if event_type == LifecycleEventType.ASSIGNMENT.value:
            current_assignment_by_id[assignment_id] = row
            assignment_timeline_by_id.setdefault(assignment_id, []).append(row)
            key = f"{_safe_text(row.get('randomization_unit'))}:{_safe_text(row.get('randomization_key'))}"
            assignment_by_randomization_key[key] = row

            assignment_hash = _safe_text(row.get("assignment_hash"))
            observed = assignment_hashes_by_id.setdefault(assignment_id, set())
            observed.add(assignment_hash)
            if len(observed) > 1:
                assignment_reproducibility_violations.append(
                    {
                        "assignment_id": assignment_id,
                        "observed_assignment_hashes": sorted(observed),
                    }
                )

        elif event_type == LifecycleEventType.EXPOSURE.value:
            dedupe_key = _safe_text(row.get("exposure_dedupe_key"))
            if dedupe_key and dedupe_key in seen_exposure_dedupe_keys:
                exposure_duplicates_suppressed += 1
                continue
            if dedupe_key:
                seen_exposure_dedupe_keys.add(dedupe_key)
            exposure_events.append(row)
            exposure_by_assignment_id.setdefault(assignment_id, []).append(row)

        elif event_type == LifecycleEventType.CONTAMINATION.value:
            contamination_events.append(row)
            contamination_by_assignment_id.setdefault(assignment_id, []).append(row)
            severity = _safe_text(row.get("contamination_severity"))
            if severity in contamination_severity_counts:
                contamination_severity_counts[severity] += 1

    projection_identity_payload = {
        "assignment_count": len(current_assignment_by_id),
        "exposure_count": len(exposure_events),
        "contamination_count": len(contamination_events),
        "rows_count": len(ordered),
        "assignment_ids": sorted(current_assignment_by_id.keys()),
        "exposure_ids": sorted(_safe_text(item.get("lifecycle_event_id")) for item in exposure_events),
        "contamination_ids": sorted(_safe_text(item.get("lifecycle_event_id")) for item in contamination_events),
    }
    projection_identity = "elp_" + _sha(_stable_json(projection_identity_payload))[:24]
    projection_hash = "elph_" + _sha(_stable_json({"identity": projection_identity, "payload": projection_identity_payload}))[:24]

    return {
        "current_assignment_by_id": current_assignment_by_id,
        "assignment_timeline_by_id": assignment_timeline_by_id,
        "assignment_by_randomization_key": assignment_by_randomization_key,
        "exposure_events": exposure_events,
        "exposure_by_assignment_id": exposure_by_assignment_id,
        "contamination_events": contamination_events,
        "contamination_by_assignment_id": contamination_by_assignment_id,
        "contamination_severity_counts": contamination_severity_counts,
        "assignment_reproducibility_violations": assignment_reproducibility_violations,
        "exposure_duplicates_suppressed": exposure_duplicates_suppressed,
        "projection_identity": projection_identity,
        "projection_hash": projection_hash,
    }
