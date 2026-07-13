from __future__ import annotations

from src.shadow_prompt_experiment_registry import (
    SHADOW_PROMPT_VARIANT_REGISTRY_SCHEMA_VERSION,
    SHADOW_PROMPT_VARIANT_REGISTRY_VERSION,
    get_prompt_variant,
    get_prompt_variant_registry,
    list_prompt_variant_ids,
)


def test_registry_contains_required_variants() -> None:
    registry = get_prompt_variant_registry()

    assert tuple(registry.keys()) == (
        "CURRENT_PRODUCTION",
        "CONTROL",
        "CANDIDATE_A",
        "CANDIDATE_B",
        "FUTURE",
    )



def test_registry_entries_are_shadow_only_and_inactive() -> None:
    registry = get_prompt_variant_registry()

    for key, entry in registry.items():
        assert entry.schema_version == SHADOW_PROMPT_VARIANT_REGISTRY_SCHEMA_VERSION
        assert entry.registry_version == SHADOW_PROMPT_VARIANT_REGISTRY_VERSION
        assert entry.advisory_only is True
        assert entry.active is False
        assert entry.compatibility["runtime_prompt_replacement_allowed"] is False
        assert entry.compatibility["pipeline_output_mutation_allowed"] is False
        assert entry.compatibility["scheduler_changes_allowed"] is False
        assert entry.compatibility["uploader_changes_allowed"] is False
        assert key in list_prompt_variant_ids()



def test_get_prompt_variant_rejects_unknown() -> None:
    try:
        get_prompt_variant("unknown")
    except ValueError as exc:
        assert "unsupported_variant" in str(exc)
    else:
        raise AssertionError("expected ValueError")
