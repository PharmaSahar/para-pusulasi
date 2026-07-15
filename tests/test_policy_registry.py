from __future__ import annotations

from pathlib import Path

import pytest

from src.policy_registry import PolicyRegistryCorruptionError, PolicyRegistryStore, build_policy_registry_record


BASE_TIME = "2026-07-15T18:02:00+00:00"


def base_policy_payload() -> dict[str, object]:
    return {
        "policy_id": "recommendation-advisory-policy",
        "policy_version": "v9.1",
        "policy_hash": "c" * 64,
        "governing_rules": ["human_review_required", "advisory_only"],
        "allowed_actions": ["advisory_recommendation"],
        "blocked_actions": ["deploy", "publish", "update_metadata"],
        "deprecated": False,
        "previous_policy_hash": None,
    }


def test_build_policy_registry_record_is_deterministic() -> None:
    payload = base_policy_payload()
    first = build_policy_registry_record(payload, created_by="tester", source_module="tests.test_policy_registry", source_version="1.0", created_at=BASE_TIME)
    second = build_policy_registry_record(payload, created_by="tester", source_module="tests.test_policy_registry", source_version="1.0", created_at=BASE_TIME)
    assert first == second
    assert first["policy_record_id"].startswith("plr_")


def test_policy_registry_store_duplicate_and_conflict(tmp_path: Path) -> None:
    store = PolicyRegistryStore(registry_path=tmp_path / "policy_registry.jsonl")
    first = store.append_record(base_policy_payload(), created_by="tester", source_module="tests.test_policy_registry", source_version="1.0", created_at=BASE_TIME)
    assert first.appended is True

    duplicate = store.append_record(base_policy_payload(), created_by="tester", source_module="tests.test_policy_registry", source_version="1.0", created_at=BASE_TIME)
    assert duplicate.duplicate is True

    conflict_payload = base_policy_payload()
    conflict_payload["blocked_actions"] = ["deploy", "publish"]
    conflict = store.append_record(conflict_payload, created_by="tester", source_module="tests.test_policy_registry", source_version="1.0", created_at=BASE_TIME)
    assert conflict.conflict is True


def test_policy_registry_corruption_blocks_replay(tmp_path: Path) -> None:
    path = tmp_path / "policy_registry.jsonl"
    path.write_text('{"broken"', encoding="utf-8")
    with pytest.raises(PolicyRegistryCorruptionError):
        PolicyRegistryStore(registry_path=path).get_rows()
