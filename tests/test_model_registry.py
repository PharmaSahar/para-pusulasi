from __future__ import annotations

from pathlib import Path

import pytest

from src.model_registry import ModelRegistryCorruptionError, ModelRegistryStore, build_model_registry_record


BASE_TIME = "2026-07-15T18:00:00+00:00"


def base_model_payload() -> dict[str, object]:
    return {
        "model_id": "claude-sonnet",
        "semantic_version": "3.5.1",
        "implementation_hash": "a" * 64,
        "provider": "anthropic",
        "family": "claude",
        "architecture": "transformer",
        "capabilities": ["text_generation", "tool_reasoning"],
        "limitations": ["offline_only"],
        "supported_features": ["content_generation", "recommendation_governance"],
        "deprecated": False,
        "previous_model_hash": None,
    }


def test_build_model_registry_record_is_deterministic() -> None:
    payload = base_model_payload()
    first = build_model_registry_record(payload, created_by="tester", source_module="tests.test_model_registry", source_version="1.0", created_at=BASE_TIME)
    second = build_model_registry_record(payload, created_by="tester", source_module="tests.test_model_registry", source_version="1.0", created_at=BASE_TIME)
    assert first == second
    assert first["model_record_id"].startswith("mdr_")
    assert first["model_event_id"].startswith("mde_")
    assert first["record_hash"].startswith("mdh_")


def test_model_registry_store_duplicate_and_conflict(tmp_path: Path) -> None:
    store = ModelRegistryStore(registry_path=tmp_path / "model_registry.jsonl")
    first = store.append_record(base_model_payload(), created_by="tester", source_module="tests.test_model_registry", source_version="1.0", created_at=BASE_TIME)
    assert first.appended is True

    duplicate = store.append_record(base_model_payload(), created_by="tester", source_module="tests.test_model_registry", source_version="1.0", created_at=BASE_TIME)
    assert duplicate.duplicate is True

    conflict_payload = base_model_payload()
    conflict_payload["provider"] = "other"
    conflict = store.append_record(conflict_payload, created_by="tester", source_module="tests.test_model_registry", source_version="1.0", created_at=BASE_TIME)
    assert conflict.conflict is True


def test_model_registry_corruption_blocks_replay(tmp_path: Path) -> None:
    path = tmp_path / "model_registry.jsonl"
    path.write_text('{"broken"', encoding="utf-8")
    store = ModelRegistryStore(registry_path=path)
    with pytest.raises(ModelRegistryCorruptionError):
        store.get_rows()
