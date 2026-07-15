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


def build_policy_registry_projection_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda item: (_safe_text(item.get("created_at")), _safe_text(item.get("policy_record_id")), _safe_text(item.get("policy_event_id"))))
    latest_by_record_id: dict[str, dict[str, Any]] = {}
    current_by_policy_key: dict[str, dict[str, Any]] = {}
    allowed_action_count = 0
    blocked_action_count = 0
    lineage_break_count = 0
    deprecated_count = 0
    active_count = 0
    policy_hashes = {_safe_text(row.get("policy_hash")) for row in ordered}
    for row in ordered:
        record_id = _safe_text(row.get("policy_record_id"))
        latest_by_record_id[record_id] = row
        policy_key = f"{_safe_text(row.get('policy_id'))}:{_safe_text(row.get('policy_version'))}"
        current_by_policy_key[policy_key] = row
        allowed_action_count += len(row.get("allowed_actions") or ())
        blocked_action_count += len(row.get("blocked_actions") or ())
        if bool(row.get("deprecated", False)):
            deprecated_count += 1
        else:
            active_count += 1
        previous_policy_hash = _safe_text(row.get("previous_policy_hash"))
        if previous_policy_hash and previous_policy_hash not in policy_hashes:
            lineage_break_count += 1
    identity_payload = {
        "row_count": len(ordered),
        "policy_keys": sorted(current_by_policy_key.keys()),
        "allowed_action_count": allowed_action_count,
        "blocked_action_count": blocked_action_count,
        "lineage_break_count": lineage_break_count,
    }
    projection_identity = "plp_" + _sha(_stable_json(identity_payload))[:24]
    projection_hash = "plph_" + _sha(_stable_json({"identity": projection_identity, "payload": identity_payload}))[:24]
    return {
        "latest_by_record_id": latest_by_record_id,
        "current_by_policy_key": current_by_policy_key,
        "allowed_action_count": allowed_action_count,
        "blocked_action_count": blocked_action_count,
        "lineage_break_count": lineage_break_count,
        "deprecated_count": deprecated_count,
        "active_count": active_count,
        "projection_identity": projection_identity,
        "projection_hash": projection_hash,
    }