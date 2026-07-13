from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.content_intelligence_foundation import GenerationBlueprint
from src.shadow_blueprint_prompt_alignment import (
    SHADOW_BLUEPRINT_PROMPT_ALIGNMENT_ANALYZER_VERSION,
    SHADOW_BLUEPRINT_PROMPT_ALIGNMENT_RESULTS_PATH,
    SHADOW_BLUEPRINT_PROMPT_ALIGNMENT_SCHEMA_VERSION,
    ShadowAlignmentValidationError,
    analyze_blueprint_prompt_alignment,
    append_alignment_row,
    benchmark_alignment,
    build_safe_prompt_representation,
    build_storage_row,
    load_alignment_rows,
)
from tests.fixtures.slice4_phase3_alignment_fixtures import build_phase3_calibration_fixtures


def _fixture_blueprint() -> GenerationBlueprint:
    fixtures = build_phase3_calibration_fixtures()
    return GenerationBlueprint.from_dict(fixtures[0].blueprint)


def test_safe_prompt_representation_rejects_secret_like_content() -> None:
    with pytest.raises(ShadowAlignmentValidationError):
        build_safe_prompt_representation(
            prompt_text="Authorization: Bearer secret-token",
            prompt_type="content_generation",
            template_id="test_template",
        )


def test_safe_prompt_representation_has_expected_fields() -> None:
    rep = build_safe_prompt_representation(
        prompt_text="channel audience topic hook retention thumbnail seo shorts discovery safety json",
        prompt_type="content_generation",
        template_id="test_template",
        input_field_presence={"topic": True},
        blueprint_goal_references=["hook_type", "retention_first_30s"],
    )
    payload = rep.to_dict()

    assert payload["schema_version"] == SHADOW_BLUEPRINT_PROMPT_ALIGNMENT_SCHEMA_VERSION
    assert payload["prompt_type"] == "content_generation"
    assert payload["template_id"] == "test_template"
    assert payload["prompt_hash"]
    assert payload["input_field_presence"]["topic"] is True
    assert "hook" in payload["normalized_instruction_categories"]
    assert payload["safety_instruction_presence"] is True


def test_alignment_result_invariants() -> None:
    blueprint = _fixture_blueprint()
    prompt = build_safe_prompt_representation(
        prompt_text="channel audience topic narrative hook retention thumbnail seo shorts safety json",
        prompt_type="content_generation",
        template_id="test_template",
    )

    result = analyze_blueprint_prompt_alignment(
        blueprint=blueprint,
        prompt_representation=prompt,
        run_id="run_test_align_01",
        channel_id=blueprint.channel_profile.channel_id,
        content_type="mixed",
        artifacts={"title": "Test", "script": "Test script"},
        recent_history=[],
        history_window=20,
    )

    assert result.schema_version == SHADOW_BLUEPRINT_PROMPT_ALIGNMENT_SCHEMA_VERSION
    assert result.analyzer_version == SHADOW_BLUEPRINT_PROMPT_ALIGNMENT_ANALYZER_VERSION
    assert result.advisory_only is True
    assert result.pipeline_output_changed is False
    assert 0.0 <= result.overall_coverage_score <= 1.0
    assert 0.0 <= result.overall_conflict_score <= 1.0


def test_deterministic_hashes_for_same_input() -> None:
    blueprint = _fixture_blueprint()
    prompt = build_safe_prompt_representation(
        prompt_text="channel audience topic narrative hook retention thumbnail seo shorts safety json",
        prompt_type="content_generation",
        template_id="test_template",
    )

    a = analyze_blueprint_prompt_alignment(
        blueprint=blueprint,
        prompt_representation=prompt,
        run_id="run_same",
        channel_id=blueprint.channel_profile.channel_id,
        content_type="mixed",
        artifacts={"title": "A", "script": "B"},
        recent_history=[],
        history_window=20,
    )
    b = analyze_blueprint_prompt_alignment(
        blueprint=blueprint,
        prompt_representation=prompt,
        run_id="run_same",
        channel_id=blueprint.channel_profile.channel_id,
        content_type="mixed",
        artifacts={"title": "A", "script": "B"},
        recent_history=[],
        history_window=20,
    )

    assert a.analysis_id == b.analysis_id
    assert a.prompt_hash == b.prompt_hash
    assert a.blueprint_hash == b.blueprint_hash


def test_storage_append_and_malformed_tolerance(tmp_path: Path) -> None:
    output = tmp_path / "shadow_blueprint_prompt_alignment.jsonl"
    blueprint = _fixture_blueprint()
    prompt = build_safe_prompt_representation(
        prompt_text="channel audience topic narrative hook retention thumbnail seo shorts safety json",
        prompt_type="content_generation",
        template_id="test_template",
    )
    result = analyze_blueprint_prompt_alignment(
        blueprint=blueprint,
        prompt_representation=prompt,
        run_id="run_storage",
        channel_id=blueprint.channel_profile.channel_id,
        content_type="mixed",
        artifacts={"title": "A", "script": "B"},
        recent_history=[],
        history_window=20,
    )
    row = build_storage_row(result).to_dict()
    append_alignment_row(row, output_path=output)

    output.write_text(output.read_text(encoding="utf-8") + "{malformed}\n", encoding="utf-8")
    rows, malformed = load_alignment_rows(input_path=output, limit=10)

    assert len(rows) == 1
    assert malformed == 1
    assert rows[0]["analysis_id"] == row["analysis_id"]


def test_no_raw_prompt_or_full_script_in_storage_row() -> None:
    blueprint = _fixture_blueprint()
    prompt = build_safe_prompt_representation(
        prompt_text="channel audience topic narrative hook retention thumbnail seo shorts safety json",
        prompt_type="content_generation",
        template_id="test_template",
    )
    result = analyze_blueprint_prompt_alignment(
        blueprint=blueprint,
        prompt_representation=prompt,
        run_id="run_privacy",
        channel_id=blueprint.channel_profile.channel_id,
        content_type="mixed",
        artifacts={"title": "A", "script": "VERY LONG SCRIPT" * 100},
        recent_history=[],
        history_window=20,
    )
    row = build_storage_row(result).to_dict()
    serialized = json.dumps(row, ensure_ascii=False)

    assert "VERY LONG SCRIPT" not in serialized
    assert "prompt_text" not in serialized


def test_benchmark_function_runs() -> None:
    blueprint = _fixture_blueprint()
    prompt = build_safe_prompt_representation(
        prompt_text="channel audience topic narrative hook retention thumbnail seo shorts safety json",
        prompt_type="content_generation",
        template_id="test_template",
    )
    metrics = benchmark_alignment(
        blueprint=blueprint,
        prompt_representation=prompt,
        artifacts={"title": "A", "script": "B"},
        runs=10,
    )

    assert metrics["one_analysis_ms"] >= 0.0
    assert metrics["hundred_analysis_ms"] >= 0.0
    assert metrics["history_window"] == 30
    assert metrics["suitability_for_201_channels"]


def test_schema_compatibility_with_existing_store(tmp_path: Path) -> None:
    output = tmp_path / "shadow_blueprint_prompt_alignment.jsonl"
    row = {
        "schema_version": SHADOW_BLUEPRINT_PROMPT_ALIGNMENT_SCHEMA_VERSION,
        "analysis_id": "align_test",
        "blueprint_id": "bp_test",
        "blueprint_hash": "hash_bp",
        "prompt_hash": "hash_prompt",
        "run_id": "run_test",
        "channel_id": "test_channel",
        "content_type": "mixed",
        "prompt_type": "content_generation",
        "template_id": "template",
        "analyzer_version": SHADOW_BLUEPRINT_PROMPT_ALIGNMENT_ANALYZER_VERSION,
        "analyzed_dimensions": 10,
        "strong_present_count": 3,
        "weak_present_count": 2,
        "missing_count": 1,
        "conflicting_count": 1,
        "unsupported_count": 1,
        "unknown_count": 2,
        "overall_coverage_score": 0.5,
        "overall_conflict_score": 0.1,
        "conflict_codes": ["UNCERTAINTY_CERTAINTY_CONFLICT"],
        "failure_source_summary": {"PROMPT_CONFLICT": 1},
        "advisory_only": True,
        "pipeline_output_changed": False,
        "created_at": "2026-07-13T10:00:00+00:00",
    }
    append_alignment_row(row, output_path=output)
    rows, malformed = load_alignment_rows(input_path=output, limit=10)

    assert malformed == 0
    assert rows[0]["schema_version"] == SHADOW_BLUEPRINT_PROMPT_ALIGNMENT_SCHEMA_VERSION


def test_default_store_path_constant_is_stable() -> None:
    assert str(SHADOW_BLUEPRINT_PROMPT_ALIGNMENT_RESULTS_PATH).endswith("shadow_blueprint_prompt_alignment.jsonl")
