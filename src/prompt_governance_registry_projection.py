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


def build_prompt_governance_registry_projection_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda item: (_safe_text(item.get("created_at")), _safe_text(item.get("prompt_record_id")), _safe_text(item.get("prompt_event_id"))))
    latest_by_record_id: dict[str, dict[str, Any]] = {}
    current_by_prompt_key: dict[str, dict[str, Any]] = {}
    compatible_model_coverage_count = 0
    lineage_break_count = 0
    deprecated_count = 0
    active_count = 0
    prompt_hashes = {_safe_text(row.get("prompt_hash")) for row in ordered}
    for row in ordered:
        record_id = _safe_text(row.get("prompt_record_id"))
        latest_by_record_id[record_id] = row
        prompt_key = f"{_safe_text(row.get('prompt_id'))}:{_safe_text(row.get('prompt_version'))}"
        current_by_prompt_key[prompt_key] = row
        compatible_model_coverage_count += len(row.get("compatible_models") or ())
        if bool(row.get("deprecated", False)):
            deprecated_count += 1
        else:
            active_count += 1
        previous_prompt_hash = _safe_text(row.get("previous_prompt_hash"))
        if previous_prompt_hash and previous_prompt_hash not in prompt_hashes:
            lineage_break_count += 1
    identity_payload = {
        "row_count": len(ordered),
        "prompt_keys": sorted(current_by_prompt_key.keys()),
        "compatible_model_coverage_count": compatible_model_coverage_count,
        "lineage_break_count": lineage_break_count,
    }
    projection_identity = "ppr_" + _sha(_stable_json(identity_payload))[:24]
    projection_hash = "pprh_" + _sha(_stable_json({"identity": projection_identity, "payload": identity_payload}))[:24]
    return {
        "latest_by_record_id": latest_by_record_id,
        "current_by_prompt_key": current_by_prompt_key,
        "compatible_model_coverage_count": compatible_model_coverage_count,
        "lineage_break_count": lineage_break_count,
        "deprecated_count": deprecated_count,
        "active_count": active_count,
        "projection_identity": projection_identity,
        "projection_hash": projection_hash,
    }