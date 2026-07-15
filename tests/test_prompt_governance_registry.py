from __future__ import annotations

from pathlib import Path

import pytest

from src.prompt_governance_registry import (
    PromptGovernanceRegistryCorruptionError,
    PromptGovernanceRegistryStore,
    build_prompt_governance_registry_record,
)


BASE_TIME = "2026-07-15T18:01:00+00:00"


def base_prompt_payload() -> dict[str, object]:
    return {
        "prompt_id": "content-generator",
        "prompt_version": "v9.1",
        "prompt_hash": "b" * 64,
        "purpose": "recommendation-advisory context formatting",
        "compatible_models": ["claude-sonnet:3.5.1"],
        "deprecated": False,
        "previous_prompt_hash": None,
    }


def test_build_prompt_governance_record_is_deterministic() -> None:
    payload = base_prompt_payload()
    first = build_prompt_governance_registry_record(payload, created_by="tester", source_module="tests.test_prompt_governance_registry", source_version="1.0", created_at=BASE_TIME)
    second = build_prompt_governance_registry_record(payload, created_by="tester", source_module="tests.test_prompt_governance_registry", source_version="1.0", created_at=BASE_TIME)
    assert first == second
    assert first["prompt_record_id"].startswith("pgr_")


def test_prompt_governance_store_duplicate_and_conflict(tmp_path: Path) -> None:
    store = PromptGovernanceRegistryStore(registry_path=tmp_path / "prompt_registry.jsonl")
    first = store.append_record(base_prompt_payload(), created_by="tester", source_module="tests.test_prompt_governance_registry", source_version="1.0", created_at=BASE_TIME)
    assert first.appended is True

    duplicate = store.append_record(base_prompt_payload(), created_by="tester", source_module="tests.test_prompt_governance_registry", source_version="1.0", created_at=BASE_TIME)
    assert duplicate.duplicate is True

    conflict_payload = base_prompt_payload()
    conflict_payload["purpose"] = "changed"
    conflict = store.append_record(conflict_payload, created_by="tester", source_module="tests.test_prompt_governance_registry", source_version="1.0", created_at=BASE_TIME)
    assert conflict.conflict is True


def test_prompt_governance_corruption_blocks_replay(tmp_path: Path) -> None:
    path = tmp_path / "prompt_registry.jsonl"
    path.write_text('{"broken"', encoding="utf-8")
    with pytest.raises(PromptGovernanceRegistryCorruptionError):
        PromptGovernanceRegistryStore(registry_path=path).get_rows()
