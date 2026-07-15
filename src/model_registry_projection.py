from __future__ import annotations

import hashlib
import json
from typing import Any


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _sha(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def build_model_registry_projection_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda item: (_safe_text(item.get("created_at")), _safe_text(item.get("model_record_id")), _safe_text(item.get("model_event_id"))))
    latest_by_record_id: dict[str, dict[str, Any]] = {}
    current_by_model_key: dict[str, dict[str, Any]] = {}
    timeline_by_record_id: dict[str, list[dict[str, Any]]] = {}
    provider_counts: dict[str, int] = {}
    family_counts: dict[str, int] = {}
    lineage_break_count = 0
    deprecated_count = 0
    active_count = 0
    implementation_hashes = {_safe_text(row.get("implementation_hash")) for row in ordered}

    for row in ordered:
        record_id = _safe_text(row.get("model_record_id"))
        latest_by_record_id[record_id] = row
        timeline_by_record_id.setdefault(record_id, []).append(row)
        model_key = f"{_safe_text(row.get('model_id'))}:{_safe_text(row.get('semantic_version'))}"
        current_by_model_key[model_key] = row
        provider = _safe_text(row.get("provider")) or "UNKNOWN"
        family = _safe_text(row.get("family")) or "UNKNOWN"
        provider_counts[provider] = provider_counts.get(provider, 0) + 1
        family_counts[family] = family_counts.get(family, 0) + 1
        if bool(row.get("deprecated", False)):
            deprecated_count += 1
        else:
            active_count += 1
        previous_model_hash = _safe_text(row.get("previous_model_hash"))
        if previous_model_hash and previous_model_hash not in implementation_hashes:
            lineage_break_count += 1

    identity_payload = {
        "row_count": len(ordered),
        "model_keys": sorted(current_by_model_key.keys()),
        "provider_counts": provider_counts,
        "family_counts": family_counts,
        "lineage_break_count": lineage_break_count,
    }
    projection_identity = "mpr_" + _sha(_stable_json(identity_payload))[:24]
    projection_hash = "mprh_" + _sha(_stable_json({"identity": projection_identity, "payload": identity_payload}))[:24]
    return {
        "latest_by_record_id": latest_by_record_id,
        "current_by_model_key": current_by_model_key,
        "timeline_by_record_id": timeline_by_record_id,
        "provider_counts": provider_counts,
        "family_counts": family_counts,
        "lineage_break_count": lineage_break_count,
        "deprecated_count": deprecated_count,
        "active_count": active_count,
        "projection_identity": projection_identity,
        "projection_hash": projection_hash,
    }